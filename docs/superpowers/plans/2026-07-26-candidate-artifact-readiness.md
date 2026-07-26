---
change: enforce-candidate-artifact-readiness
design-doc: docs/superpowers/specs/2026-07-26-candidate-artifact-readiness-design.md
base-ref: c41cfa03b162b05c344f6cda7109dcc9a16e6b57
---

# Candidate Artifact Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变零载荷 `SubmitCandidate`、持久 schema 或公开 CLI 的前提下，为指定宿主增加顶层普通文件就绪门，阻止空 Candidate 进入 Evaluator。

**Architecture:** 在 `collaboration.py` 内实现一个有界文件名规范化函数和基于目录描述符的元数据检查，并把冻结的 `required_candidate_files` 从 CLI 内部环境解析一路传入 `SubmitCandidateTool`。默认空元组走现有快速路径；M22 人类冒烟仅对子进程冻结 `calc.py` 与 `test_calc.py`，Planner 和 restricted `FileWrite` 人工确认保持原样。

**Tech Stack:** Python 3.11+ 标准库 `json`/`os`/`re`/`stat`/`pathlib`、Pydantic v2、现有 `CollaborationStore`/`ToolRegistry`/`subprocess.run`、pytest、Ruff、uv、OpenSpec、Comet。

## Global Constraints

- OpenSpec delta specs under `openspec/changes/enforce-candidate-artifact-readiness/specs/` are the canonical behavior contract.
- 严格 TDD：每项生产行为先运行聚焦测试并确认因缺少该行为而 RED，再写最小实现并确认 GREEN。
- 不新增依赖、公开 CLI 参数、持久字段、`forgeagent.collaboration.v1` schema 版本、Evaluator 权限或 Candidate manifest。
- `SubmitCandidate` 仍为零载荷；门禁只检查宿主冻结的顶层名字是否对应非符号链接普通文件，不读取内容、不运行测试、不判断正确性。
- `required_candidate_files=()` 时不访问新增文件检查路径，single、普通 Duo/Triad、Loop 与 HTTP 保持现有行为。
- 私有环境值无效时使用固定配置错误，不回显原始 JSON、绝对路径、文件内容或 credential。
- 保留用户现有未提交改动和未跟踪文件；每次提交只暂存本任务明确列出的文件。

## File Map

| File | Responsibility |
|---|---|
| `src/forgeagent/collaboration.py` | 文件名规范化、安全普通文件检查、Candidate 门禁及 Runner/registry 内部传递 |
| `src/forgeagent/cli.py` | 私有 JSON 环境解析，并仅在 CLI `run` 协作路径传入冻结要求 |
| `scripts/m22-triad-human-smoke.py` | 仅对子进程注入固定 `calc.py`/`test_calc.py` 要求 |
| `tests/test_collaboration_tools.py` | 规范化、缺失/目录/符号链接、状态不推进、默认兼容合同 |
| `tests/test_collaboration_runner.py` | Runner 到 Generator registry 的传递及失败后同 Step 恢复 |
| `tests/test_cli.py` | 私有环境缺省、合法、非法和 CLI 接线合同 |
| `tests/test_m22_triad_human_smoke.py` | M22 子进程环境与人工 stdio 继承合同 |
| `README.md`, `ACTION_PLAN.md`, `tests/test_collaboration_docs.py` | 用户边界、复测方式和静态文档合同 |

---

### Task 1: Candidate 文件名合同与安全就绪门

**Files:**
- Modify: `src/forgeagent/collaboration.py`
- Modify: `tests/test_collaboration_tools.py`

**Interfaces:**
- Produces: `normalize_required_candidate_files(value: object) -> tuple[str, ...]`。
- Produces: `SubmitCandidateTool(store, state, required_candidate_files: tuple[str, ...] = ())`。
- Consumes: `ToolContext.allowed_root`, `CollaborationStore.load/save`, existing `SubmitCandidateArgs` and revision CAS.

- [x] **Step 1: 写文件名规范化 RED 测试**

在 `tests/test_collaboration_tools.py` 导入 `normalize_required_candidate_files`，覆盖 list/tuple 正常化、顺序保持，以及空串、重复、17 项、超过 128 字符、`.`/`..`、`a/b`、`a\\b`、绝对路径、非 ASCII、控制字符和非字符串项拒绝：

```python
def test_required_candidate_files_are_bounded_safe_top_level_names():
    assert normalize_required_candidate_files(["calc.py", "test_calc.py"]) == (
        "calc.py",
        "test_calc.py",
    )
    for value in (["a", "a"], ["../a"], ["a/b"], ["a\\b"], ["\u63a7\u5236.py"], ["a\n.py"]):
        with pytest.raises(ValueError, match="required candidate files are invalid"):
            normalize_required_candidate_files(value)
```

- [x] **Step 2: 运行规范化测试并确认 RED**

Run: `rtk uv run pytest -q tests/test_collaboration_tools.py -k required_candidate_files`

Expected: FAIL during import because `normalize_required_candidate_files` does not exist.

- [x] **Step 3: 实现最小有界规范化**

在 `src/forgeagent/collaboration.py` 增加内部常量与公开给内部调用者使用的函数；只接受 list/tuple，最多 16 项，每项匹配 1-128 字符 ASCII 顶层名，拒绝重复：

```python
MAX_REQUIRED_CANDIDATE_FILES = 16
_REQUIRED_CANDIDATE_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def normalize_required_candidate_files(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_REQUIRED_CANDIDATE_FILES:
        raise ValueError("required candidate files are invalid")
    names = tuple(value)
    if any(
        type(name) is not str
        or not name.isascii()
        or _REQUIRED_CANDIDATE_FILE_RE.fullmatch(name) is None
        for name in names
    ) or len(set(names)) != len(names):
        raise ValueError("required candidate files are invalid")
    return names
```

- [x] **Step 4: 写 SubmitCandidate 门禁 RED 测试**

增加以下独立合同：两个文件均缺失时 detail 按冻结顺序列名且持久 state 与调用前完全相等；创建 `calc.py` 后只报告 `test_calc.py`；两个普通文件就绪后成功、phase 变 `evaluator` 且 attempt 只增一次；同名目录和指向普通文件的符号链接失败；默认空配置在空目录仍成功。构造真实 `ToolContext` 时复用测试已有 context helper，确保 `allowed_root=str(tmp_path)`。

```python
tool = SubmitCandidateTool(
    store,
    state,
    required_candidate_files=("calc.py", "test_calc.py"),
)
before = store.load(state.collaboration_id)
outcome = tool.run(SubmitCandidateArgs(), _tool_context(tmp_path))
assert outcome.success is False
assert outcome.detail.endswith("calc.py, test_calc.py")
assert store.load(state.collaboration_id) == before
```

- [x] **Step 5: 运行门禁测试并确认 RED**

Run: `rtk uv run pytest -q tests/test_collaboration_tools.py -k 'submit_candidate and (required or symlink or directory or default)'`

Expected: FAIL because `SubmitCandidateTool.__init__` does not accept `required_candidate_files` and empty Candidate still advances state.

- [x] **Step 6: 实现基于目录描述符的最小门禁**

在 `src/forgeagent/collaboration.py` 增加 `_unready_candidate_files(allowed_root, names) -> tuple[str, ...]`。空 names 立即返回；非空时要求 `O_NOFOLLOW`、`O_DIRECTORY`、`O_CLOEXEC`，打开 `Path(allowed_root).resolve(strict=True)` 的目录 fd，逐个以 `dir_fd` + `O_NOFOLLOW` 打开并用 `fstat` 接受 `stat.S_ISREG`，检查前后 root 路径 `stat(follow_symlinks=False)` 的 `(st_dev, st_ino)` 相同，所有 fd 用 `finally` 关闭。平台 flag 缺失、root/文件 `OSError` 或 root 重绑定均 fail closed；只返回冻结名字，不返回 host error/path。

将 `SubmitCandidateTool.run` 排序为：校验 args → phase 与 `store.load()` revision 一致 → 文件门禁 → 现有 CAS 保存。门禁失败返回：

```python
return ToolOutcome(
    tool=self.name,
    success=False,
    detail="required candidate files are missing or unsafe: " + ", ".join(unready),
)
```

不得改变失败时的 phase、revision、attempt、旧 verdict 或 rejections。

- [x] **Step 7: 运行 Task 1 GREEN 与 Ruff**

Run: `rtk uv run pytest -q tests/test_collaboration_tools.py && rtk uv run ruff check src/forgeagent/collaboration.py tests/test_collaboration_tools.py`

Expected: all collaboration tool tests PASS; Ruff exits 0.

- [x] **Step 8: 提交 Task 1**

Run: `rtk git add src/forgeagent/collaboration.py tests/test_collaboration_tools.py && rtk git commit -m "fix: gate candidate submission on required files"`

### Task 2: Runner 与 Generator registry 传递及恢复

**Files:**
- Modify: `src/forgeagent/collaboration.py`
- Modify: `tests/test_collaboration_runner.py`

**Interfaces:**
- Consumes: Task 1 `normalize_required_candidate_files()` and `SubmitCandidateTool(..., required_candidate_files=...)`.
- Produces: `build_generator_registry(..., required_candidate_files: tuple[str, ...] = ()) -> ToolRegistry`。
- Produces: `CollaborationRunner.__init__/create(..., required_candidate_files: tuple[str, ...] = ())`，内部保存规范化 tuple。

- [x] **Step 1: 写 Runner 传递与同 Step 恢复 RED 测试**

在 `tests/test_collaboration_runner.py` 增加专用 `_ArtifactRoleBuilder`：只为该测试创建 `Task(..., tier="trusted", allowed_root=str(tmp_path))`，避免 restricted `FileWrite` 的人工确认门掩盖 Candidate 门禁；生产 M22 路径仍保持 restricted。Runner 配置 `("calc.py", "test_calc.py")`；同一个 Generator Task 第 1 轮先 `SubmitCandidate` 得到缺失反馈，第 2 轮在同一响应中按顺序调用两个 `FileWrite` 和 `SubmitCandidate`；断言 Evaluator 只在成功提交后启动，Generator attempt 为 1 而不是 2，最终 completed。另加默认空 tuple 的现有脚本继续一次提交成功，以及非法嵌入配置在创建 Runner 时 `ValueError`。

```python
runner = _runner(
    tmp_path,
    builder,
    required_candidate_files=("calc.py", "test_calc.py"),
)
report = runner.run("write PRIVATE_GOAL artifact")
assert report.status == "completed"
assert [role for role, _attempt, _prompt in builder.calls] == ["generator", "evaluator"]
assert report.generator_attempts == 1
```

- [x] **Step 2: 运行 Runner 测试并确认 RED**

Run: `rtk uv run pytest -q tests/test_collaboration_runner.py -k 'required_candidate or candidate_readiness'`

Expected: FAIL because `CollaborationRunner.create()` has no `required_candidate_files` parameter and its Generator registry cannot configure the tool gate.

- [x] **Step 3: 实现最小内部传递**

给 `build_generator_registry`、`CollaborationRunner.__init__` 和 `.create()` 增加默认空 tuple 参数；Runner 构造边界再次调用 `normalize_required_candidate_files`，`_run_duo` 构造 Generator registry 时传入冻结值：

```python
registry = build_generator_registry(
    registry=self._generator_registry or default_registry(),
    store=self._store,
    state=generator_state,
    required_candidate_files=self._required_candidate_files,
)
```

保持 Loop/HTTP/其他直接调用者不传参数时的行为不变；不要新增 state 字段或审计字段。

- [x] **Step 4: 运行 Runner/工具 GREEN**

Run: `rtk uv run pytest -q tests/test_collaboration_tools.py tests/test_collaboration_runner.py tests/test_collaboration_planner.py tests/test_collaboration_integrations.py`

Expected: all focused collaboration tests PASS, including existing rejection/resume/Loop registry coverage.

- [x] **Step 5: 提交 Task 2**

Run: `rtk git add src/forgeagent/collaboration.py tests/test_collaboration_runner.py && rtk git commit -m "fix: propagate candidate readiness requirements"`

### Task 3: CLI 私有配置与 M22 子进程接线

**Files:**
- Modify: `src/forgeagent/cli.py`
- Modify: `scripts/m22-triad-human-smoke.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_m22_triad_human_smoke.py`

**Interfaces:**
- Consumes: `normalize_required_candidate_files(value)` and `run_collaboration_once(..., required_candidate_files=())`.
- Produces: `_load_required_candidate_files_from_environment() -> tuple[str, ...]` using `FORGEAGENT_INTERNAL_CANDIDATE_REQUIRED_FILES_JSON`.
- Produces: M22 child environment value exactly `["calc.py","test_calc.py"]` while continuing to inherit stdin/stdout/stderr.

- [x] **Step 1: 写 CLI 私有环境 RED 测试**

在 `tests/test_cli.py` 覆盖：缺省返回 `()`；合法 JSON array 返回 tuple；`{`、对象、字符串、重复、不安全名字、17 项、递归异常都抛固定 `RegistryError("Invalid candidate file configuration")`，异常文本不含输入值。再 monkeypatch `run_collaboration_once`，执行 `main(["run", "--mode", "duo", ...])`，断言其收到冻结 tuple；single 路径不新增公开参数。

```python
monkeypatch.setenv(
    cli_module._CANDIDATE_FILES_ENVIRONMENT,
    '["calc.py","test_calc.py"]',
)
assert cli_module._load_required_candidate_files_from_environment() == (
    "calc.py",
    "test_calc.py",
)
```

- [x] **Step 2: 运行 CLI 测试并确认 RED**

Run: `rtk uv run pytest -q tests/test_cli.py -k 'candidate_file_configuration or required_candidate_files'`

Expected: FAIL because the private environment constant/loader and `run_collaboration_once` argument do not exist.

- [x] **Step 3: 实现 CLI 解析和 `run` 接线**

在 `src/forgeagent/cli.py` 增加常量与固定错误翻译：

```python
_CANDIDATE_FILES_ENVIRONMENT = "FORGEAGENT_INTERNAL_CANDIDATE_REQUIRED_FILES_JSON"


def _load_required_candidate_files_from_environment() -> tuple[str, ...]:
    raw = os.environ.get(_CANDIDATE_FILES_ENVIRONMENT)
    if raw is None:
        return ()
    try:
        return normalize_required_candidate_files(json.loads(raw))
    except (json.JSONDecodeError, RecursionError, ValueError, TypeError):
        raise RegistryError("Invalid candidate file configuration") from None
```

给 `run_collaboration_once` 增加默认空 tuple 并传入 `CollaborationRunner.create`。仅在 `main()` 的 CLI `run` 协作分支、任何 client probe/角色创建之前加载并传入；普通 single、REPL、Loop 和 HTTP 不读取该私有环境。

- [x] **Step 4: 写 M22 环境接线 RED 测试**

扩展 `test_run_smoke_prints_stable_success_summary_and_inherits_forgeagent_stdio`：fake runner 捕获 `env`，断言既有 context budget 保留，同时新值 JSON 解码为固定两项；继续断言没有 `stdin`、`stdout`、`stderr`、`capture_output`，从而证明 Planner/FileWrite 人工输入未被预填或管道化。

```python
assert json.loads(environment[smoke._CANDIDATE_FILES_ENVIRONMENT]) == [
    "calc.py",
    "test_calc.py",
]
assert not {"stdin", "stdout", "stderr", "capture_output"}.intersection(kwargs)
```

- [x] **Step 5: 运行 M22 测试并确认 RED**

Run: `rtk uv run pytest -q tests/test_m22_triad_human_smoke.py -k 'run_smoke and environment'`

Expected: FAIL because `run_smoke` only injects the context budget environment.

- [x] **Step 6: 注入 M22 固定 Candidate 文件要求**

在 `scripts/m22-triad-human-smoke.py` 增加与 CLI 完全一致的私有环境名和紧凑 JSON 常量，并在复制后的 child `environment` 中设置；不修改父进程 `os.environ`，不改变命令数组、cwd、stdio 继承、人工确认或 credential 来源。

```python
_CANDIDATE_FILES_ENVIRONMENT = "FORGEAGENT_INTERNAL_CANDIDATE_REQUIRED_FILES_JSON"
_CANDIDATE_FILES_JSON = '["calc.py","test_calc.py"]'
```

- [x] **Step 7: 运行 Task 3 GREEN 与 Ruff**

Run: `rtk uv run pytest -q tests/test_cli.py tests/test_m22_triad_human_smoke.py -k 'candidate or context_config or run_smoke' && rtk uv run ruff check src/forgeagent/cli.py scripts/m22-triad-human-smoke.py tests/test_cli.py tests/test_m22_triad_human_smoke.py`

Expected: focused tests PASS; Ruff exits 0; fake subprocess records both private overrides and inherited stdio.

- [x] **Step 8: 提交 Task 3**

Run: `rtk git add src/forgeagent/cli.py scripts/m22-triad-human-smoke.py tests/test_cli.py tests/test_m22_triad_human_smoke.py && rtk git commit -m "fix: require M22 candidate artifacts before evaluation"`

### Task 4: 文档、全量验证与审查收尾

**Files:**
- Modify: `README.md`
- Modify: `ACTION_PLAN.md`
- Modify: `tests/test_collaboration_docs.py`
- Modify: `openspec/changes/enforce-candidate-artifact-readiness/tasks.md`

**Interfaces:**
- Consumes: Tasks 1-3 implemented behavior and existing M22 command `uv run --offline python scripts/m22-triad-human-smoke.py`.
- Produces: 用户可见职责边界、人工复测方法、自动验证证据和完成的 OpenSpec task checklist.

- [x] **Step 1: 写文档合同 RED 测试**

在 `tests/test_collaboration_docs.py` 断言 README M22 冒烟段明确包含：仅本次子进程冻结 `calc.py`/`test_calc.py`；门禁只检查非符号链接普通文件存在、不读取内容或替代 Evaluator；Planner 与 restricted `FileWrite` 仍需人工批准；普通 CLI/Loop/HTTP 默认不启用。断言 `ACTION_PLAN.md` 记录真实复测仍需人工执行，不把离线回归写成真实模型 PASS。

- [x] **Step 2: 运行文档测试并确认 RED**

Run: `rtk uv run pytest -q tests/test_collaboration_docs.py -k 'candidate or human_smoke'`

Expected: FAIL because README/ACTION_PLAN do not yet describe the Candidate artifact readiness boundary.

- [x] **Step 3: 更新 README 与 ACTION_PLAN**

在 README `M22 真实模型 Triad 人类冒烟` 小节追加上述精确边界和不变命令；在 ACTION_PLAN 的 M22 人类冒烟记录后追加本 change 状态、自动验证口径与人工复测命令。不得声明尚未执行的真实模型结果，不新增 CLI 用法或配置文件字段。

- [x] **Step 4: 运行完整自动质量门**

Run: `rtk uv run pytest -q tests/test_collaboration_tools.py tests/test_collaboration_runner.py tests/test_collaboration_planner.py tests/test_collaboration_integrations.py tests/test_cli.py tests/test_m22_triad_human_smoke.py tests/test_collaboration_docs.py`

Expected: all targeted tests PASS.

Run: `rtk uv run pytest -q`

Expected: full suite PASS with only documented skips; no real model/network call is made.

Run: `rtk uv run ruff format --check src tests scripts && rtk uv run ruff check src tests scripts && rtk uv build && rtk openspec validate --all --strict && rtk git diff --check`

Expected: format/check/build/OpenSpec all exit 0; `git diff --check` prints nothing.

- [x] **Step 5: 完成标准代码审查并复验 findings**

Run: `rtk codex review --base c41cfa03b162b05c344f6cda7109dcc9a16e6b57`

Expected: review completes. For every concrete finding, add a focused regression test, observe RED, apply the smallest fix, rerun the affected focused command and then rerun Step 4. Record “no findings” when applicable; do not treat review text as test evidence.

- [x] **Step 6: 记录人工真实模型验证边界**

记录以下命令仍由用户在真实 TTY 中执行，并需要人工批准 Planner 与每个 restricted `FileWrite`；本实现任务不自动运行或伪造该结果：

```bash
uv run --offline python scripts/m22-triad-human-smoke.py
```

预期人工成功证据：首次空 Candidate 在当前 Generator Step 收到缺失文件反馈，Evaluator 不启动；文件获批写入后同一 Generator 成功提交，最终脚本打印 `M22 TRIAD HUMAN SMOKE: PASS` 并保留 workdir。

- [x] **Step 7: 勾选 OpenSpec tasks 并提交收尾**

在 `openspec/changes/enforce-candidate-artifact-readiness/tasks.md` 仅将已经由命令证据完成的 1.1-3.3 项改为 `[x]`；若人工真实模型复测未执行，只在文档中保留“需人工批准执行”的诚实说明，但不阻塞 delta spec 要求的自动回归。

Run: `rtk git add README.md ACTION_PLAN.md tests/test_collaboration_docs.py openspec/changes/enforce-candidate-artifact-readiness/tasks.md && rtk git commit -m "docs: document candidate artifact readiness"`

## OpenSpec Task Coverage

| OpenSpec task | Plan coverage |
|---|---|
| 1.1 SubmitCandidate RED matrix | Task 1 Steps 4-5 |
| 1.2 CLI private JSON RED matrix | Task 3 Steps 1-2 |
| 1.3 M22 child environment RED | Task 3 Steps 4-5 |
| 2.1 normalization + safe fd check | Task 1 Steps 3 and 6 |
| 2.2 Runner/registry/tool propagation | Task 2 Steps 1-4 |
| 2.3 CLI + M22 injection | Task 3 Steps 3 and 6 |
| 3.1 README/ACTION_PLAN/spec boundary | Task 4 Steps 1-3 and 7 |
| 3.2 full quality gates | Task 4 Step 4 |
| 3.3 review + honest real-model status | Task 4 Steps 5-7 |

## Self-Review Results

- Spec coverage: runtime-collaboration 的四个 scenarios 与 triad-human-smoke 的两个 modified scenarios 均映射到 Task 1-4；OpenSpec 1.1-3.3 无缺口。
- Placeholder scan: plan contains no deferred implementation placeholders; every production edit has an exact signature or minimal code shape, an observed RED command and a GREEN command.
- Type consistency: `required_candidate_files` is consistently `tuple[str, ...] = ()` from CLI/Runner/registry/tool; normalization returns the same type; M22 environment decodes to the same two names.
- Scope check: change is one coherent internal data path plus its M22 opt-in consumer，不需要拆分子项目；无新依赖、公开 CLI/schema、内容验收或额外抽象。
