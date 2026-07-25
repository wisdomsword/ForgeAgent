---
change: harden-local-persistence-boundaries
design-doc: docs/superpowers/specs/2026-07-25-harden-local-persistence-boundaries-design.md
base-ref: eb2dc8dfa053988ae9e71283fb79b02f8d176fc1
---

# 本地持久化边界加固实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 关闭 FileWrite 校验后 symlink 竞态，并让项目 Memory 与 Loop checkpoint 的本地跨进程更新具有真实原子性。

**Architecture:** FileWrite 使用 project-root directory fd、逐组件 `O_NOFOLLOW` 和最终 descriptor 写入。Memory 使用稳定 `.MEMORY.lock` 在锁内重读、合并与原子替换；Loop 使用每个 ID 独立稳定 lock file 在锁内执行 create/save CAS。所有实现仅使用 Python 标准库并保持现有公共错误、文件格式和入口不变。

**Tech Stack:** Python 3.11+、`os` directory-fd API、`stat`、POSIX `fcntl.flock`、pytest、Pydantic v2。

## Global Constraints

- 不新增依赖、配置项、公共 API、存储 schema 字段或通用 storage/lock abstraction。
- 使用 TDD；每个组件先观察目标测试在旧实现上失败，再写最小实现。
- 不触碰 CollaborationStore、exactly-once 外部副作用、分布式锁、网络文件系统强一致或 Windows 新支持。
- 所有失败继续使用既有固定、脱敏的公开结果，不披露异常、绝对路径或 lock path。
- 保留用户已有未跟踪文件，不纳入提交或格式化。

---

### Task 1: FileWrite descriptor-relative final open

**Files:**
- Modify: `tests/test_web_file_tools.py`
- Modify: `src/forgeagent/tools.py`
- Modify: `openspec/changes/harden-local-persistence-boundaries/tasks.md`

**Interfaces:**
- Consumes: `_validate_path(path: str, allowed_root: str) -> Path` 现有静态 containment 结果。
- Produces: `_write_file_safely(path: Path, allowed_root: str, content: str) -> str`，成功返回 canonical project-relative path，失败抛 `PermissionError`（静态越界）或 `OSError`/`ValueError`（安全 open/write 失败）。

- [x] **Step 1: 写失败测试**

在 `tests/test_web_file_tools.py` 增加测试注入点，分别在 `_validate_path` 返回后把最终目标替换为指向外部文件的 symlink、把父目录替换为外部目录 symlink、把 root pathname 替换为 symlink。断言 outcome 固定为 `FileWrite failed`，外部文件字节不变，成功路径仍为 `wrote nested/file.txt`。

- [x] **Step 2: 运行 RED**

Run: `uv --cache-dir /tmp/forgeagent-p1-uv-cache run --offline pytest -q tests/test_web_file_tools.py -k 'file_write and (symlink or binding)'`

Expected: 至少新增的最终目标或父目录竞态测试失败，证明旧 `Path.write_text()` 会跟随替换后的 symlink。

- [x] **Step 3: 最小实现**

在 `tools.py` 引入 `stat`，实现：

```python
def _write_file_safely(path: Path, allowed_root: str, content: str) -> str:
    root = Path(os.path.realpath(allowed_root))
    relative = path.relative_to(root)
    parts = relative.parts
    if not parts:
        raise OSError("file target required")
    no_follow = os.O_NOFOLLOW
    directory_flag = os.O_DIRECTORY
    root_fd = os.open(root, os.O_RDONLY | directory_flag | no_follow)
    # 逐组件打开父目录；最终用 dir_fd + O_NOFOLLOW 打开，fstat 必须为 regular file。
    # 在 finally 中关闭所有 descriptor，并在成功前核对 root pathname binding。
```

`FileWriteTool.run()` 保留 `_validate_path` 对静态越界的专用错误；随后调用 helper，并把其余
`PermissionError/OSError/ValueError/AttributeError` 收敛为现有 `FileWrite failed`。

- [x] **Step 4: 运行 GREEN 与回归**

Run: `uv --cache-dir /tmp/forgeagent-p1-uv-cache run --offline pytest -q tests/test_web_file_tools.py tests/test_headless.py tests/test_tools.py`

Expected: 全部通过。

- [x] **Step 5: 更新任务状态并提交**

勾选 OpenSpec 1.1-1.3，运行 Ruff focused check，然后提交：

```bash
git add src/forgeagent/tools.py tests/test_web_file_tools.py openspec/changes/harden-local-persistence-boundaries/tasks.md
git commit -m "fix: harden FileWrite descriptor boundary"
```

### Task 2: Memory lock-scoped merge

**Files:**
- Modify: `tests/test_memory.py`
- Modify: `src/forgeagent/memory.py`
- Modify: `openspec/changes/harden-local-persistence-boundaries/tasks.md`

**Interfaces:**
- Produces: `_locked_project_update(candidate: MemoryCandidate) -> tuple[dict[str, MemoryCandidate], bool]`，在稳定 lock file 的排他锁内重载并持久化，返回最新 map 与 candidate 是否替换已有 key。
- Internal helper: `_load_project_entries(path: Path, *, diagnose: bool) -> dict[str, MemoryCandidate]`，让 `load()` 与锁内重读共享相同解析行为而不重复诊断策略。

- [x] **Step 1: 写失败测试**

增加两个独立 `MemoryManager` 在相同 root 先 `load()` 后分别写不同 key 的测试；旧实现最终只保留后写 key，因此 RED。增加同 key 后写覆盖、`.MEMORY.lock` symlink、monkeypatch `fcntl.flock` 失败，以及失败后 manager render 与文件字节不变测试。

- [x] **Step 2: 运行 RED**

Run: `uv --cache-dir /tmp/forgeagent-p1-uv-cache run --offline pytest -q tests/test_memory.py -k 'concurrent or lock'`

Expected: 不同 key 合并测试失败；lock 安全测试因功能缺失失败。

- [x] **Step 3: 最小实现**

在 `memory.py` 导入 `fcntl`、`stat`，增加固定 lock path。安全打开要求 `O_RDWR|O_CREAT|O_NOFOLLOW`、`0o600`、regular file、`fchmod(0o600)`。在 `LOCK_EX` 内重新安全读取最新 MEMORY.md，应用 candidate 与大小限制，调用现有 `_write_project()`；成功后才更新 `_project`。所有 lock/read/write `OSError` 收敛为现有 persistence_error。

- [x] **Step 4: 运行 GREEN 与回归**

Run: `uv --cache-dir /tmp/forgeagent-p1-uv-cache run --offline pytest -q tests/test_memory.py tests/test_golden_candidates_memory.py tests/test_identity.py tests/test_cli.py -k 'memory or remember or reload'`

Expected: 全部通过。

- [x] **Step 5: 更新任务状态并提交**

勾选 OpenSpec 2.1-2.3，提交：

```bash
git add src/forgeagent/memory.py tests/test_memory.py openspec/changes/harden-local-persistence-boundaries/tasks.md
git commit -m "fix: serialize project memory updates"
```

### Task 3: Loop per-ID cross-process CAS

**Files:**
- Modify: `tests/test_loop_checkpoint.py`
- Modify: `src/forgeagent/loop.py`
- Modify: `openspec/changes/harden-local-persistence-boundaries/tasks.md`

**Interfaces:**
- Produces: `_locked(loop_id: str)` private context manager，安全打开 `.<id>.lock` 并持有 `LOCK_EX`。
- Produces: `_load_unlocked(loop_id: str) -> LoopCheckpoint`，仅在 store 的线程锁或 per-ID lock 已按调用点持有时读取。

- [x] **Step 1: 写失败测试**

用两个独立 store 和 barrier/monkeypatch 在旧 `load` 与 `_write` 间交错两个 `expected_revision=0` 保存，断言旧实现错误地两个都成功；增加 overlapping create、symlink lock、flock 失败和不同 ID 能同时进入锁内测试。

- [x] **Step 2: 运行 RED**

Run: `uv --cache-dir /tmp/forgeagent-p1-uv-cache run --offline pytest -q tests/test_loop_checkpoint.py -k 'overlap or lock or cross_process'`

Expected: 同 revision 重叠提交测试失败，证明当前 revision CAS 只在单 store 对象内有效。

- [x] **Step 3: 最小实现**

在 `loop.py` 导入 `fcntl` 与 `contextmanager`。安全 lock file 使用 loops directory fd、
`O_RDWR|O_CREAT|O_NOFOLLOW`、`0o600`、regular-file 验证和 `fchmod`。`create()` 在 per-ID lock 内
检查不存在并写入；`save()` 在 per-ID lock 内调用 `_load_unlocked()`、比较 revision、写 N+1。
`load()` 保持只读且不要求排他锁。不同 ID 使用不同文件名。

- [x] **Step 4: 运行 GREEN 与回归**

Run: `uv --cache-dir /tmp/forgeagent-p1-uv-cache run --offline pytest -q tests/test_loop_checkpoint.py tests/test_loop_runner.py tests/test_loop_cli.py tests/test_loop_http.py tests/test_collaboration_integrations.py`

Expected: 全部通过。

- [x] **Step 5: 更新任务状态并提交**

勾选 OpenSpec 3.1-3.3，提交：

```bash
git add src/forgeagent/loop.py tests/test_loop_checkpoint.py openspec/changes/harden-local-persistence-boundaries/tasks.md
git commit -m "fix: make loop checkpoint CAS cross-process"
```

### Task 4: Contracts, reviews, and completion gates

**Files:**
- Modify: `docs/threat-model.md`
- Modify: `openspec/changes/harden-local-persistence-boundaries/tasks.md`
- Create: `docs/superpowers/reports/2026-07-25-harden-local-persistence-boundaries-verify.md`

**Interfaces:** None.

- [x] **Step 1: 更新契约**

更新 T10、T18 和 Memory 投毒/持久化相关行：声明本地 POSIX descriptor 与 advisory-lock 保证；明确外部不协作 writer、网络文件系统、目录被移动后的旧 inode 写入和 external side-effect exactly-once 仍不承诺。

- [x] **Step 2: 两轮自审**

第一轮逐 requirement/scenario 映射实现与测试；第二轮检查 descriptor 泄漏、lock inode 身份、死锁顺序、固定错误披露、不同 ID 并行、用户未跟踪文件和无新依赖。

- [x] **Step 3: thorough code review**

按 `requesting-code-review` 审查 `base_ref..HEAD`。Critical/Important 必须修复并复跑专项；Minor 仅在不扩大范围时处理。

- [x] **Step 4: 完整门禁**

运行：

```bash
uv --cache-dir /tmp/forgeagent-p1-uv-cache run --offline ruff format --check .
uv --cache-dir /tmp/forgeagent-p1-uv-cache run --offline ruff check .
uv --cache-dir /tmp/forgeagent-p1-uv-cache run --offline pytest -q
uv --cache-dir /tmp/forgeagent-p1-uv-cache run --offline python -m tests.golden.runner --output-dir /tmp/forgeagent-p1-golden
uv --cache-dir /tmp/forgeagent-p1-uv-cache build --out-dir /tmp/forgeagent-p1-dist
openspec validate --all --strict
git diff --check eb2dc8dfa053988ae9e71283fb79b02f8d176fc1..HEAD
```

Expected: 全部退出 0；pytest 只保留已记录环境 skip；golden 20/20。

- [x] **Step 5: 完成报告与提交**

记录原始结果、两轮自审和 review 结论，勾选 4.1-4.3 并提交：

```bash
git add docs/threat-model.md docs/superpowers/reports/2026-07-25-harden-local-persistence-boundaries-verify.md openspec/changes/harden-local-persistence-boundaries/tasks.md
git commit -m "docs: verify local persistence hardening"
```
