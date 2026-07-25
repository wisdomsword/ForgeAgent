---
change: harden-runtime-resilience-and-evidence
design-doc: docs/superpowers/specs/2026-07-25-harden-runtime-resilience-and-evidence-design.md
base-ref: d61ccb875463c380b2501bc7f4a5ab078dec0963
---

# 运行时韧性与证据收尾实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Evaluator 增加宿主冻结的隔离检查，补齐 MCP hung-call 与搜索 fallback，并形成 P2/P3 的真实证据和延期裁决。

**Architecture:** 新建聚焦的 `check_runner.py` 承担临时副本与子进程生命周期；`collaboration.py` 只定义 `RunCheck` 工具并按宿主映射选择性注册。MCP 保持现有实现，仅把永久 skip 改为真实回归；搜索把单引擎请求提取为私有函数，由公开函数固定尝试两个内置引擎。

**Tech Stack:** Python 3.11+、Pydantic v2、stdlib `subprocess`/`tempfile`/`shutil`/`threading`、pytest、Ruff、OpenSpec。

## Global Constraints

- 不新增第三方依赖、公共请求字段、任意 shell/argv API、数据库或 daemon。
- 所有产品行为严格 RED→GREEN；未知检查不得启动进程，取消与 timeout 必须清理子进程和临时副本。
- 模型只能提供 `check_id`；argv、env、cwd、timeout 与输出上限由宿主冻结。
- 默认无 checks 时不得广告 `RunCheck`，普通 Evaluator 权限不变。
- 不承诺异步强杀 Python 线程；provider/MCP 继续依赖自身 timeout。

---

### Task 1: Evaluator 隔离检查模型、执行器与 registry

**Files:**
- Create: `src/forgeagent/check_runner.py`
- Modify: `src/forgeagent/collaboration.py`
- Modify: `src/forgeagent/tools.py`
- Modify: `src/forgeagent/step.py`
- Test: `tests/test_check_runner.py`
- Test: `tests/test_collaboration_tools.py`

**Interfaces:**
- Produces: `CheckDefinition`, `CheckResult`, `run_check(definition, allowed_root, cancel_event) -> CheckResult`。
- Produces: `RunCheckArgs(check_id: str)`、`RunCheckTool(checks)`；`build_evaluator_registry(..., checks=None)` 仅在非空时注册。
- Consumes: `ToolContext.allowed_root`、新增 `ToolContext.cancel_event`、现有 `mask_secrets()`。

- [ ] **Step 1: 写模型、默认 registry 和注入拒绝的失败测试**

在 `tests/test_collaboration_tools.py` 增加：空 checks 时工具名仍精确为 `FileRead/FileList/SubmitEvaluation`；非空时新增 `RunCheck`；`RunCheckArgs.model_validate({"check_id":"unit", "argv":["rm"]})` 因 extra field 失败；未知 ID 返回失败且 monkeypatched runner 未调用。

- [ ] **Step 2: 运行 RED**

Run: `rtk uv run pytest -q tests/test_collaboration_tools.py -k 'run_check or evaluator_registry'`

Expected: FAIL，原因是 `CheckDefinition`、`RunCheckArgs`、`RunCheckTool` 或 checks 参数尚不存在。

- [ ] **Step 3: 写隔离副本和执行生命周期的失败测试**

在 `tests/test_check_runner.py` 创建测试：

```python
def test_run_check_uses_copy_and_keeps_project_unchanged(tmp_path): ...
def test_run_check_rejects_escaping_symlink_and_special_file(tmp_path): ...
def test_run_check_uses_frozen_argv_cwd_and_minimal_env(tmp_path): ...
def test_run_check_reports_pass_and_failure_with_bounded_masked_output(tmp_path): ...
def test_run_check_timeout_kills_process_group_and_cleans_copy(tmp_path): ...
def test_run_check_cancel_kills_process_group_before_timeout(tmp_path): ...
```

测试使用 `sys.executable -c <fixed code>` 作为宿主 argv；通过 marker 文件证明 cwd 位于副本、真实项目未改变；secret 通过 monkeypatch 注入；timeout/cancel 子进程再启动一个 child，并断言两者均停止。临时目录位置通过注入 `temporary_directory_factory` 或模块级最小 seam 观察，结束后必须不存在。

- [ ] **Step 4: 运行第二组 RED**

Run: `rtk uv run pytest -q tests/test_check_runner.py`

Expected: collection/import FAIL，因为 `forgeagent.check_runner` 尚不存在。

- [ ] **Step 5: 实现最小执行器**

`check_runner.py` 只包含冻结 Pydantic 模型、小型复制校验 helper、进程组终止 helper 和 `run_check`。使用 `TemporaryDirectory`、`copytree`、`Popen(shell=False, start_new_session=True)`；以短轮询检查 `cancel_event` 和 monotonic deadline；stdout/stderr 各截断 16 KiB并掩码。POSIX `killpg(SIGTERM/SIGKILL)`，Windows `terminate/kill`。

- [ ] **Step 6: 透传 cancel_event 并接线工具**

给 `ToolContext` 增加 `cancel_event: threading.Event | None = None`，`Step` 构造 context 时传入现有 `_cancel_event`。在 `collaboration.py` 中定义严格 `RunCheckArgs` 和工具；工具只查映射后调用 runner。`build_evaluator_registry` 的 checks 默认 `None`，避免改动所有调用方。

- [ ] **Step 7: 运行 GREEN 与相邻回归**

Run: `rtk uv run pytest -q tests/test_check_runner.py tests/test_collaboration_tools.py tests/test_collaboration_runner.py tests/test_step.py tests/test_tools.py`

Expected: PASS，无新 skip。

- [ ] **Step 8: 勾选 OpenSpec 1.1-1.4 并提交**

Run: `rtk git add src/forgeagent/check_runner.py src/forgeagent/collaboration.py src/forgeagent/tools.py src/forgeagent/step.py tests/test_check_runner.py tests/test_collaboration_tools.py openspec/changes/harden-runtime-resilience-and-evidence/tasks.md && rtk git commit -m "feat: add isolated evaluator checks"`

### Task 2: 协作取消安全边界与 MCP hung-call 回归

**Files:**
- Modify: `src/forgeagent/collaboration.py`
- Modify: `tests/test_collaboration_runner.py`
- Modify: `tests/test_mcp_manager.py`

**Interfaces:**
- Consumes: existing `cancel_event` and `CollaborationRunner._stop()` terminal path。
- Consumes: `MCPManager(call_timeout=...)`、loop-owned `_sessions/_holders` test fixtures。

- [ ] **Step 1: 写取消前不构造下一角色的失败测试**

覆盖 Planner→Generator、Generator rejection→下一 Generator、Generator→Evaluator 三个安全边界：前一角色返回时设置 event，断言 builder 没有收到下一角色且 report 为 cancelled。现有 role 内取消路径保持不变。

- [ ] **Step 2: 运行 RED**

Run: `rtk uv run pytest -q tests/test_collaboration_runner.py -k 'cancel and (before or next or rejection)'`

Expected: 至少一个测试 FAIL，显示当前 runner 在取消后仍构造下一角色。

- [ ] **Step 3: 在每个角色/attempt 构造前增加同一最小守卫**

在 `CollaborationRunner.run()` 的角色转换点调用现有 `_cancelled(cancel_event)`/`_stop("cancelled")` 逻辑；不新增 cancellation manager，不改变已终态 report 发布。

- [ ] **Step 4: 把 MCP 占位改为真实短超时测试并先运行**

用真实本地 stdio fixture 的 `hang_on_call` 模式：server 接受调用后永不返回，manager 使用短 `call_timeout`。调用 facade 后断言 `ok=False`、固定失败文本、状态失效且 `close()` 墙钟有界；另用受控 session 回归证明替换 generation 后的迟到成功被丢弃。先运行现有实现，若 PASS 仅视为测试债务修复；若 FAIL 再进入 Step 5。

Run: `rtk uv run pytest -q tests/test_mcp_manager.py::test_hung_call_times_out`

Expected: 新测试执行而非 SKIP；PASS 或暴露具体 timeout/close 缺陷。

- [ ] **Step 5: 仅在 RED 时修复现有 MCP deadline/ownership 路径**

限定修改 `_call_tool_on_loop` 或 facade timeout 文本/cleanup，不新增线程池、watchdog 或 server 重启框架。迟到结果必须通过 generation/session/holder 匹配被丢弃。

- [ ] **Step 6: 运行 GREEN 与回归**

Run: `rtk uv run pytest -q tests/test_collaboration_runner.py tests/test_mcp_manager.py`

Expected: PASS；原永久 skip 数减少 1。

- [ ] **Step 7: 勾选 OpenSpec 1.3、2.1 并提交**

Run: `rtk git add src/forgeagent/collaboration.py src/forgeagent/mcp_manager.py tests/test_collaboration_runner.py tests/test_mcp_manager.py openspec/changes/harden-runtime-resilience-and-evidence/tasks.md && rtk git commit -m "test: enforce bounded cancellation and MCP timeout"`

### Task 3: 搜索固定双引擎 fallback

**Files:**
- Modify: `src/forgeagent/web_search.py`
- Modify: `tests/test_web_search.py`

**Interfaces:**
- Produces private `_search_engine(query, max_results, engine) -> tuple[list[SearchResult], str | None]`。
- Preserves public `search_with_status()` and `search()` signatures。

- [ ] **Step 1: 写失败矩阵测试**

使用 URL 顺序驱动 fake：首选 OSError→备用成功；首选 503→备用成功；首选 200 零结果→备用成功；首选 blocked+备用 unavailable→blocked；两个 unavailable→unavailable；两个零结果→`([], None)`；首选成功有结果时只请求一次。

- [ ] **Step 2: 运行 RED**

Run: `rtk uv run pytest -q tests/test_web_search.py -k 'fallback or only_requests_preferred'`

Expected: FAIL，当前实现只请求一个 URL。

- [ ] **Step 3: 提取单引擎 helper 并实现最多两次尝试**

保持现有 URL 构造、decode、异常捕获和 parser；公开函数只负责顺序和最终错误优先级。不要新增配置或动态 host。

- [ ] **Step 4: 运行 GREEN 与 SSRF 相邻回归**

Run: `rtk uv run pytest -q tests/test_web_search.py tests/test_ssrf_guard.py tests/test_cli.py -k 'search or ssrf or redirect'`

Expected: PASS，无公网访问。

- [ ] **Step 5: 勾选 OpenSpec 2.2-2.3 并提交**

Run: `rtk git add src/forgeagent/web_search.py tests/test_web_search.py openspec/changes/harden-runtime-resilience-and-evidence/tasks.md && rtk git commit -m "fix: add bounded search fallback"`

### Task 4: 真实证据、P3 裁决、文档与完成门禁

**Files:**
- Modify: `README.md`
- Modify: `ACTION_PLAN.md`
- Modify: `docs/threat-model.md`
- Modify: `docs/http-task-service.md`
- Modify: `milestones/milestone_022.md`
- Create: `docs/superpowers/reports/2026-07-25-runtime-resilience-and-evidence-verify.md`
- Modify: `openspec/changes/harden-runtime-resilience-and-evidence/tasks.md`

**Interfaces:**
- Consumes: existing `tests.golden.runner`, CLI `evaluate`/`run --mode`, Docker container tests。
- Produces: exact command/result evidence; no product API。

- [ ] **Step 1: 运行 container 与 MCP 环境矩阵**

Run authorized: `rtk uv run pytest -q tests/test_container_backend.py tests/test_mcp_manager.py`

Expected: Docker 可用则真实 container tests PASS；否则 only documented Docker/image skips。记录 OS、Docker server/image availability；Podman/Linux 缺失明确记为未验证。

- [ ] **Step 2: 运行真实模型证据**

先用 `rtk uv run forgeagent models`/现有 config resolver 确认可用模型 ID，不输出 key。对每个实际可用 provider 运行既有 real-model golden 5 项；再运行一个固定小型任务的 single/Triad 和一次 credentialed Evaluator。给每次调用设置已有 timeout/round/rejection 上限。失败原样记录稳定 error kind，不循环重试扩大费用。

- [ ] **Step 3: 复核 P3 已完成/延期证据**

Run: `rtk uv run pytest -q tests/test_streaming.py -k 'tool_calls_trigger_silent_aggregation_fallback'`

Expected: PASS，证明 native tool-call fragment aggregation 已完成。文档列出其余四项的重启触发条件，不创建空实现。

- [ ] **Step 4: 更新公开文档与验证报告**

README/威胁模型说明 `RunCheck` 的宿主冻结、临时副本、timeout/cancel 和非硬杀边界；ACTION_PLAN 只追加 P2/P3 收尾状态；M22 遗留项更新为只读隔离检查已交付及真实模型当次证据。报告区分离线门禁、Docker、真实模型和仍未验证环境。

- [ ] **Step 5: 运行完整完成门禁**

Run:

```bash
rtk uv run ruff format --check .
rtk uv run ruff check .
rtk uv run pytest -q
rtk uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-p2-p3-golden
rtk uv build --out-dir /tmp/forgeagent-p2-p3-build
rtk openspec validate --all --strict
rtk git diff --check d61ccb875463c380b2501bc7f4a5ab078dec0963..HEAD
rtk git diff --check
```

Expected: 全部退出 0；golden 20/20；skip 仅为精确记录的环境能力。

- [ ] **Step 6: 两轮自审、thorough review、勾选 3.1-4.3 并提交**

第一轮逐 scenario 对应实现/测试；第二轮核对安全边界、公开文档、证据数字和延期触发条件。独立 reviewer 覆盖完整 diff，修复所有 Critical/High/Important。

Run: `rtk git add README.md ACTION_PLAN.md docs/threat-model.md docs/http-task-service.md milestones/milestone_022.md docs/superpowers/reports/2026-07-25-runtime-resilience-and-evidence-verify.md openspec/changes/harden-runtime-resilience-and-evidence && rtk git commit -m "docs: close P2 and P3 resilience work"`
