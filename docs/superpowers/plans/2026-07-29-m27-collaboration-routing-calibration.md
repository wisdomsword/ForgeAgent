---
change: calibrate-collaboration-routing
design-doc: docs/superpowers/specs/2026-07-29-m27-collaboration-routing-calibration-design.md
base-ref: 1273e90b00adeab0b85d3db7bdc0463c82e7dc2a
archived-with: 2026-07-29-calibrate-collaboration-routing
---

# M27 协作路由校准实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把无显式选择的编程任务默认路由为 Single，仅在显式选择或可信宿主绑定冻结检查时使用 Triad，并以不可变 M25 证据完成策略裁决和公开状态修正。

**Architecture:** 路由器只消费显式 mode 与 `has_bound_checks` 布尔事实，移除不再参与决策的文本分类器。独立标准库脚本在既有 M25 严格复算之后生成加法式 M27 JSON/Markdown 派生报告；文档合同把 Memory、基线和 Linux claim 限定到已验证事实。

**Tech Stack:** Python 3.11+、Pydantic、pytest、标准库 `json/hashlib/pathlib/statistics`、OpenSpec/Comet、Ruff、uv。

## Global Constraints

- 未显式选择且无非空冻结检查时，所有任务包括编程任务 MUST 使用 Single。
- 显式 Single、Duo、Triad MUST 原样生效并优先于宿主证据，不得要求较弱模式覆盖确认。
- 只有可信宿主绑定的非空冻结检查可触发自动 Triad；候选文件要求不得触发。
- 不新增依赖、模型调用、意图分类器、用户配置或检查注册表。
- M25 protocol、raw、environment、summary 和原 report MUST 保持字节不变；新结果只写独立 M27 派生目录。
- 误完成定义固定为 `runtime_completed is True and solved is False`，必须报告 scheduled 与 runtime-completed 两种分母。
- 终止原因按原始 `runtime_reason` 精确分类，不得合并。
- M25 早于 M26 证据绑定，报告不得表述为当前 evidence-bound Triad 的质量证明。
- 不改变 M18 Memory runtime、`--no-identity` 或 `--no-memory` 行为。
- Linux verified 仅覆盖 Pipeline 50 / Job 249 已记录的 runner topology，不宣称未经记录的架构。
- 保留并不提交用户已有未跟踪文件。

archived-with: 2026-07-29-calibrate-collaboration-routing
---

### Task 1: 路由策略与入口接线

**Files:**
- Modify: `tests/test_collaboration_routing.py`
- Modify: `tests/test_collaboration_integrations.py`
- Modify: `tests/test_http_task_service.py`
- Modify: `src/forgeagent/collaboration.py`
- Modify: `src/forgeagent/cli.py`
- Modify: `src/forgeagent/http_task_service.py`

**Interfaces:**
- Consumes: `resolve_collaboration_mode(goal, requested_mode, *, allow_weaker_override=False)`、`ModeDecision`、现有 CLI/REPL/HTTP route audit。
- Produces: `resolve_collaboration_mode(goal, requested_mode, *, has_bound_checks=False, allow_weaker_override=False) -> ModeDecision`；新增稳定 reason `bound_checks`；显式模式优先；新结果 `override_required=False`。

- [x] **Step 1: 写 resolver RED 测试**

用小型参数矩阵替换旧编程正则分类大表，至少包含：

```python
@pytest.mark.parametrize("goal", ["Add a unit test", "修改 Main.java", "Explain Python"])
def test_unqualified_goals_default_to_single(goal: str) -> None:
    assert resolve_collaboration_mode(goal, None) == ModeDecision(
        mode="single", reason="default"
    )

def test_bound_checks_select_triad_without_exposing_check_content() -> None:
    decision = resolve_collaboration_mode("Add a unit test", None, has_bound_checks=True)
    assert decision == ModeDecision(mode="triad", reason="bound_checks")

@pytest.mark.parametrize("mode", ["single", "duo", "triad"])
def test_explicit_mode_wins_over_bound_checks(mode: str) -> None:
    decision = resolve_collaboration_mode(
        "Add a unit test", mode, has_bound_checks=True, allow_weaker_override=False
    )
    assert decision.mode == mode
    assert decision.reason == "explicit"
    assert decision.override_required is False
```

同时添加 audit 断言：`bound_checks` 事件不含 goal、argv、path、check id；兼容参数 true/false 不改变显式结果。

- [x] **Step 2: 运行 resolver RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q tests/test_collaboration_routing.py`

Expected: FAIL，因为当前编程目标返回 Triad、函数不接受 `has_bound_checks`、reason 不接受 `bound_checks`。

- [x] **Step 3: 写入口 RED 测试**

修改集成合同：

```python
def test_repl_programming_goal_uses_single(monkeypatch):
    single_calls = []
    monkeypatch.setattr(cli_module, "run_once", lambda goal, **kwargs: single_calls.append(goal))
    # 输入 Add a unit test 后断言 single_calls == ["Add a unit test"]，
    # run_collaboration_once 未调用，console 不含 programming task。

def test_repl_explicit_duo_does_not_read_override_confirmation(monkeypatch):
    # /duo Add a unit test 后下一个输入直接是 quit，断言 Duo 被调用一次。

def test_cli_programming_goal_uses_run_once(monkeypatch):
    # forgeagent run Add a unit test 无 --mode 时断言 run_once，非 collaboration。
```

把 HTTP 普通编程提交的公开 mode 从 `triad` 改为 `task`/Single 投影，并断言 route reason 为
`default`、mode 为 `single`、不泄露 PRIVATE_GOAL。保留显式 Duo/Triad 与 Loop checkpoint 测试。

- [x] **Step 4: 运行入口 RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q tests/test_collaboration_integrations.py tests/test_http_task_service.py`

Expected: FAIL，当前 REPL/CLI/HTTP 仍自动 Triad或要求覆盖确认。

- [x] **Step 5: 实现最小 GREEN**

在 `collaboration.py`：

```python
class ModeDecision(BaseModel):
    mode: CollaborationMode
    reason: Literal["explicit", "bound_checks", "default", "override_required"]
    override_required: bool = False

def resolve_collaboration_mode(
    goal: str,
    requested_mode: CollaborationMode | None,
    *,
    has_bound_checks: bool = False,
    allow_weaker_override: bool = False,
) -> ModeDecision:
    del goal, allow_weaker_override
    if requested_mode is not None:
        return ModeDecision(mode=requested_mode, reason="explicit")
    if has_bound_checks:
        return ModeDecision(mode="triad", reason="bound_checks")
    return ModeDecision(mode="single", reason="default")
```

删除 `_CLAUSE_SPLIT` 到 `_programming_signal` 之间仅供旧路由使用的常量/helper，但保留
`unicodedata` 若安全文本 helper 仍使用。把 `_confirmed_collaboration_mode` 简化为一次 resolver
调用，并删除 REPL/CLI 的 `reason == "programming"` 输出和 factory 的不可达
`override_required` 拒绝。HTTP 不再为无 mode 请求注入 triad。不要给普通用户 options 增加
`has_bound_checks`。

- [x] **Step 6: 运行 GREEN 与相邻回归**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q tests/test_collaboration_routing.py tests/test_collaboration_integrations.py tests/test_http_task_service.py tests/test_loop_runner.py tests/test_http_config.py tests/test_collaboration_models.py`

Expected: 全部 PASS。

- [x] **Step 7: 提交 Task 1**

```bash
git add src/forgeagent/collaboration.py src/forgeagent/cli.py src/forgeagent/http_task_service.py tests/test_collaboration_routing.py tests/test_collaboration_integrations.py tests/test_http_task_service.py
git commit -m "feat: default collaboration routing to single"
```

### Task 2: M25 冻结证据派生分析

**Files:**
- Create: `scripts/m27_m25_routing_analysis.py`
- Create: `tests/test_m27_m25_routing_analysis.py`
- Create: `docs/evaluation/m25/derived/m27-collaboration-routing/analysis.json`
- Create: `docs/evaluation/m25/derived/m27-collaboration-routing/report.md`
- Modify: `docs/evaluation/m25/README.md`

**Interfaces:**
- Consumes: `scripts.m25_independent_recompute.verify_summary(protocol_path, run_dir)`、冻结 M25 raw 字段。
- Produces: `derive(protocol_path: Path, run_dir: Path) -> dict[str, object]`、`render_report(analysis) -> str`、CLI `--protocol --run-dir --output-dir`。

- [x] **Step 1: 写派生分析 RED 测试**

复用 `tests/test_m25_independent_recompute.py::write_complete_evidence` 构造 270-run evidence，修改一条
合法记录使 `runtime_completed=True`、checks/artifacts 不全通过、`solved=False`，并断言：

```python
analysis = module.derive(M25_PROTOCOL_PATH, output)
bucket = analysis["models"]["claude-haiku-4-5"]["single"]
assert bucket["false_completions"] == 1
assert bucket["false_completion_rate_scheduled"] == {
    "numerator": 1, "denominator": 45, "value": 1 / 45,
}
assert bucket["false_completion_rate_runtime_completed"]["numerator"] == 1
assert bucket["termination_reasons"][record["runtime_reason"]] >= 1
```

另断言 family/mode 为跨模型聚合、包含 calls/attempts/latency/tokens sum 与 mean，
`automatic_triad_restored_for == []`，且报告包含“M25 早于 M26”。添加负例：raw identity/summary
篡改被既有复算拒绝；output-dir 位于 run-dir 内时拒绝；失败时不产生半成品。

- [x] **Step 2: 运行派生 RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q tests/test_m27_m25_routing_analysis.py`

Expected: FAIL，因为脚本不存在。

- [x] **Step 3: 实现最小派生脚本**

脚本加载 sibling `m25_independent_recompute.py`，先调用 `verify_summary`。逐 raw 严格验证新增字段：
布尔必须为 bool，整数非负，latency 为有限非负数，reason 为非空字符串。Bucket 保存计数与 sum，
最终转换为带 numerator/denominator/value 的率和 sum/mean。family/mode 跨两个模型聚合。

冻结 manifest 至少包含 protocol、environment.json、summary.json、report.md 和 270 个 raw 的相对路径
及 SHA-256，再计算 canonical manifest digest。写出前确认 `output_dir.resolve()` 不等于或位于
`run_dir.resolve()` 内。JSON 使用 `sort_keys=True` 和换行；两个文件先写入预先命名事务目录，再
逐文件 `replace`。普通 I/O 异常尽力完整回滚；逐文件发布不是跨文件原子事务，异步中断或回滚/
探测不确定时必须报错并保留 `old/staged/failed-new` 恢复证据，不得输出成功标记。

策略裁决按 family 比较 Triad 与 Single solved rate；仅严格更高者进入 quality eligible。真实 M25
结果应令 eligible 与 restored 均为空。

- [x] **Step 4: 运行派生 GREEN**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q tests/test_m27_m25_routing_analysis.py tests/test_m25_independent_recompute.py`

Expected: 全部 PASS。

- [x] **Step 5: 对真实冻结 M25 生成派生产物**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run python scripts/m27_m25_routing_analysis.py \
  --protocol docs/evaluation/m25/protocol.json \
  --run-dir docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini \
  --output-dir docs/evaluation/m25/derived/m27-collaboration-routing
```

Expected: `M27_ROUTING_ANALYSIS_OK runs=270 restored=none`。

更新 M25 README，仅增加派生目录链接与解释边界，不改原报告含义。

- [x] **Step 6: 独立复算并检查冻结输入未变**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run python scripts/m25_independent_recompute.py \
  --protocol docs/evaluation/m25/protocol.json \
  --output docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini
git diff --exit-code -- docs/evaluation/m25/protocol.json docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini
```

Expected: `INDEPENDENT_RECOMPUTE_OK runs=270`；冻结路径无 diff。

- [x] **Step 7: 提交 Task 2**

```bash
git add scripts/m27_m25_routing_analysis.py tests/test_m27_m25_routing_analysis.py docs/evaluation/m25/README.md docs/evaluation/m25/derived/m27-collaboration-routing
git commit -m "feat: derive m25 collaboration routing evidence"
```

### Task 3: 文档合同与公开状态

**Files:**
- Modify: `tests/test_collaboration_docs.py`
- Modify: `tests/test_continuous_verification.py`
- Modify: `README.md`
- Modify: `ACTION_PLAN.md`
- Modify: `docs/http-task-service.md`
- Modify: `docs/threat-model.md`
- Modify: `docs/platform-support.md`

**Interfaces:**
- Consumes: Task 1 路由合同、Task 2 派生报告、最终前一轮 pytest/OpenSpec/Golden 数字。
- Produces: 一致的 Single 默认、Memory 行为、M27 路由裁决、Linux verified 和当前基线公开合同。

- [x] **Step 1: 写文档 RED 合同**

在协作文档测试中断言 README/HTTP 文档包含：默认 Single、显式模式优先、非空冻结检查可 Triad、
`allow_weaker_override` 仅兼容无行为；不再包含编程任务强制 Triad、needs_confirmation 或较弱覆盖。

在持续验证测试中：

```python
assert "Linux Docker runner topology" in matrix
assert "Linux amd64/arm64 + Docker Engine" not in matrix
assert "Linux runner remains\n`configured`" not in matrix
assert ".forgeagent/MEMORY.md" in readme
assert "原子" in readme and "用户" in readme and "编辑" in readme
```

提取 README 与 platform-support 的当前 pytest/OpenSpec/Golden 数字并断言完全相等。

- [x] **Step 2: 运行文档 RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q tests/test_collaboration_docs.py tests/test_continuous_verification.py`

Expected: FAIL，因为旧强制 Triad、Memory 只读、旧 baseline 和 Linux 矛盾仍存在。

- [x] **Step 3: 更新文档至 GREEN**

README 改为新路由与 Memory 真相；HTTP 文档删除 headless override confirmation，保留显式 Duo/Triad
和 Planner 确认策略；threat-model 说明自动 Triad 只来自可信宿主绑定检查，布尔事实不是用户输入。
ACTION_PLAN 新增/完成 M27 行并链接派生报告，明确没有类别恢复自动 Triad。

platform-support 第一行写为 `Linux Docker runner topology (Pipeline 50 / Job 249)` 或同等收窄文字，
保留 verified 与 10/10 JUnit，删除最后 configured 句。此步骤先使用当时最近一次完整验证数字；Task 4
最终全量结果若变化，再同步精确数字。

- [x] **Step 4: 运行文档 GREEN**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q tests/test_collaboration_docs.py tests/test_continuous_verification.py`

Expected: 全部 PASS。

- [x] **Step 5: 提交 Task 3**

```bash
git add README.md ACTION_PLAN.md docs/http-task-service.md docs/threat-model.md docs/platform-support.md tests/test_collaboration_docs.py tests/test_continuous_verification.py
git commit -m "docs: publish m27 collaboration routing policy"
```

### Task 4: 全量验证、基线定稿与里程碑收尾

**Files:**
- Modify: `README.md`
- Modify: `docs/platform-support.md`
- Modify: `openspec/changes/calibrate-collaboration-routing/tasks.md`
- Create: `docs/superpowers/reports/2026-07-29-m27-collaboration-routing-calibration-verify.md`
- Create: `milestones/milestone_027.md`
- Modify: `milestones/latest`

**Interfaces:**
- Consumes: Task 1-3 提交与全部验证命令。
- Produces: 精确当前基线、验证报告、完成的 OpenSpec tasks 和 M27 续接记录。

- [x] **Step 1: 运行完整验证**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run ruff format --check .
openspec validate --all --strict
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run python -m tests.golden.runner
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv build --out-dir /tmp/forgeagent-m27-build
git diff --check
```

Expected: pytest 全通过且只保留环境依赖 skip；Ruff 两项通过；OpenSpec 全部 strict 通过；Golden
`20/20`；wheel/sdist 构建成功；diff check 无输出。

- [x] **Step 2: 用实际结果定稿基线并复验合同**

把 Step 1 的精确 pytest、OpenSpec、Golden 数字同时写入 README 与 platform-support。Run:

`UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q tests/test_continuous_verification.py tests/test_collaboration_docs.py`

Expected: PASS，两个公开文件数字一致。

- [x] **Step 3: 两轮最终自审**

第一轮检查：逐条映射三份 delta spec 与新 capability，确认没有恢复自动类别、没有把 candidate files
当证据、M25 冻结树无 diff、Linux/Memory claim 精确。第二轮检查：搜索
`programming task|override_required|needs_confirmation|MEMORY.*只读|Linux amd64/arm64|remains configured`
并逐项判断剩余出现是否为历史归档；检查显式 Single/Duo/Triad、bound_checks audit、HTTP/Loop 兼容。
发现问题立即添加失败测试、修复并复验。

- [x] **Step 4: 写验证报告与里程碑**

验证报告记录命令、实际输出摘要、M25 派生关键数字、两轮自审结论、独立审查结论和已知边界。
`milestone_027.md` 按 `MILESTONE_GUIDE.md` 包含状态、范围、设计、任务、交付物、评审、验证、遗留和
续接指引；`milestones/latest` 指向 `milestone_027.md`。

- [x] **Step 5: 勾选 OpenSpec 与计划任务并提交**

勾选本计划和 `openspec/changes/calibrate-collaboration-routing/tasks.md` 的对应完成项。Run:

```bash
git add README.md docs/platform-support.md openspec/changes/calibrate-collaboration-routing docs/superpowers/specs/2026-07-29-m27-collaboration-routing-calibration-design.md docs/superpowers/plans/2026-07-29-m27-collaboration-routing-calibration.md docs/superpowers/reports/2026-07-29-m27-collaboration-routing-calibration-verify.md milestones/milestone_027.md milestones/latest
git commit -m "chore: complete m27 collaboration routing calibration"
```

- [x] **Step 6: 运行最终状态检查**

Run:

```bash
openspec validate calibrate-collaboration-routing --strict
git diff --check HEAD^ HEAD
git status --short
```

Expected: change strict valid；提交 diff 无空白错误；状态仅显示用户原有未跟踪文件。

### Task 5: 最终独立评审修复

**Files:**
- Modify: `scripts/m27_m25_routing_analysis.py`
- Modify: `tests/test_m27_m25_routing_analysis.py`
- Modify: `src/forgeagent/cli.py`
- Modify: `tests/test_collaboration_integrations.py`

**Interfaces:**
- Preserves: `write_outputs(output_dir, analysis)` 的普通 I/O 失败回滚与可观察失败合同；逐文件
  `replace` 不承诺任意异步中断下的跨文件原子性，状态不确定时保留预命名恢复目录。
- Produces: CLI/REPL Single 路由与协作路由一致的 `collaboration.route` 审计，且不记录 goal/argv/path。

- [x] **Step 1: 写两个独立 RED 合同**

模拟第一个既有目标从 destination 移到 backup 时失败，断言两个旧产物都保持原字节；为 CLI 和 REPL
默认/显式 Single 注入 audit sink，断言各发出一次 `collaboration.route`，mode/reason 稳定且 payload
不包含 goal、argv 或 path。

- [x] **Step 2: 运行 RED**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q \
  tests/test_m27_m25_routing_analysis.py tests/test_collaboration_integrations.py
```

Expected: 新增合同失败，分别暴露既有文件误删和 Single 路由漏审计。

- [x] **Step 3: 实现最小 GREEN**

派生输出使用固定 `staged/old/failed-new` rename 状态机：普通 I/O 失败尽力回滚；异步中断、restore
或 probe 不确定时立即停止该文件的后续破坏性 rename，保留恢复目录并抛出聚合异常。Single 分支在调用 `run_once`
前使用既有 `emit_collaboration_route`，复用当前 decision、audit sink 与 task id 语义，不改变
`run_once` 的通用接口，也不重复发出 Duo/Triad 审计。

- [x] **Step 4: 运行 GREEN 与相邻回归**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q \
  tests/test_m27_m25_routing_analysis.py tests/test_collaboration_integrations.py \
  tests/test_collaboration_routing.py tests/test_http_task_service.py
```

Expected: 全部 PASS。

- [x] **Step 5: 重新完整验证、更新证据并提交**

重复 Task 4 的 pytest、OpenSpec、Golden、Ruff、离线打包和 diff 检查；用实际数字同步 README、
platform-support、验证报告与 milestone，完成两轮自审和独立复审后提交。

### Task 6: 最终路由审计一致性修复

**Files:**
- Modify: `src/forgeagent/cli.py`
- Modify: `src/forgeagent/loop.py`
- Modify: `tests/test_collaboration_integrations.py`
- Modify: `tests/test_loop_checkpoint.py`
- Modify: `tests/test_loop_runner.py`
- Modify: `tests/test_http_server.py`

**Interfaces:**
- Preserves: Single/Duo/Triad 路由决策本身、旧 checkpoint 可加载性和 Duo/Triad 单次审计语义。
- Produces: CLI/REPL Single 复用调用方 audit sink；未注入时生产 CLI 写入
  `~/.forgeagent/audit.jsonl`；REPL `/single <goal>`；Loop default/explicit 来源冻结与恢复。

- [x] **Step 1: 写 RED 合同**

CLI/REPL 测试注入真实 sink，断言 Single 只产生一个 `collaboration.route` 且不含 goal/argv/path；
Loop create/resume 测试断言 default/explicit 来源；旧 Duo/Triad 缺字段时迁移为 explicit，旧 Single/
缺 mode 为 default；HTTP 无字段与显式 `single` 分别投影 default/explicit。真实 `main()` 无注入时
必须创建默认 JSONL audit，初始化失败必须在任务前明确失败且不泄漏路径。

- [x] **Step 2: 实现最小 GREEN**

CLI main、REPL 和 Loop 复用既有 audit sink；`run`、`loop` 和 REPL 未注入时创建既有
`JsonlAuditSink`，固定路径为 `~/.forgeagent/audit.jsonl`，初始化失败返回 2；serve/evaluate 保持原有
路径。新增 `/single` 命令元数据；checkpoint 新增带默认值的 `collaboration_mode_source`，create 时
冻结、resume 时复用，并在 model before validator 中迁移 legacy collaborative checkpoint。

- [x] **Step 3: 受影响验证与两轮自审**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q \
  tests/test_collaboration_integrations.py tests/test_loop_checkpoint.py \
  tests/test_loop_runner.py tests/test_cli.py tests/test_http_server.py \
  tests/test_http_task_service.py
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run ruff check \
  src/forgeagent/cli.py src/forgeagent/loop.py \
  tests/test_collaboration_integrations.py tests/test_loop_checkpoint.py \
  tests/test_loop_runner.py tests/test_http_server.py
git diff --check
```

Result: `532 passed, 10 skipped`；Ruff 与 diff check 通过。第一轮修复 `/single` 帮助/补全遗漏；
第二轮复审继续修复生产 CLI 默认 audit 目的地与 legacy Duo/Triad 来源迁移，确认注入 sink 优先、
serve/evaluate 不冲突、Single 无重复审计、Loop 恢复不改变来源。
