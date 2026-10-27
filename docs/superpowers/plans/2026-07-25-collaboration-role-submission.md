---
change: fix-collaboration-role-protocol
design-doc: docs/superpowers/specs/2026-07-25-collaboration-role-submission-design.md
base-ref: 1ba638b7fce626908e3dfe79cc9baf4f15a705c4
archived-with: 2026-07-25-fix-collaboration-role-protocol
---

# Collaboration Role Submission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Planner、Generator、Evaluator 只能通过结构化 Submit 完成角色，并为 Generator 增加与当前 attempt 绑定的零载荷 Candidate 门。

**Architecture:** `ToolOutcome` 提供通用成功终止信号，`ToolRegistry` 声明唯一 required completion tool，Step 负责有界恢复与顺序截断。协作工具通过现有 revision CAS 持久化 phase、attempt 和 verdict，Runner 负责 invariant、统计、拒绝和恢复。

**Tech Stack:** Python 3.12、Pydantic v2、pytest、ruff、ForgeAgent 文本 ToolCall 协议。

## Global Constraints

- 不新增依赖，不新增 collaboration state 字段，不迁移 `forgeagent.collaboration.v1`。
- `single` 和 Loop single 行为保持不变。
- Evaluator 保持只读 registry，并独占验收。
- 所有生产逻辑先写失败测试并观察 RED。
- 保留当前 change 已有实验性 diff，仅以批准设计替换其过时的 standalone completion 与硬编码 Submit 逻辑。

### Task 1: 通用工具终止与 required completion 元数据

**Files:**
- Modify: `src/forgeagent/tools.py`
- Modify: `src/forgeagent/step.py`
- Test: `tests/test_tools.py`
- Test: `tests/test_step.py`

**Interfaces:**
- Produces: `ToolOutcome.completes_task: bool = False`
- Produces: `ToolRegistry.required_completion_tool: str | None`
- Produces: `ToolRegistry.require_completion(tool_name: str) -> None`
- Consumes: 现有 `Tool.run() -> ToolOutcome`、`Termination.COMPLETED`

- [x] **Step 1: 写 ToolOutcome 与 ToolRegistry 的失败测试**

```python
def test_tool_outcome_completion_defaults_off():
    assert ToolOutcome(tool="Probe", success=True).completes_task is False

def test_registry_allows_one_registered_required_completion_tool():
    registry = ToolRegistry()
    registry.register(ProbeTool("SubmitOne"))
    registry.require_completion("SubmitOne")
    assert registry.required_completion_tool == "SubmitOne"
    with pytest.raises(ValueError):
        registry.require_completion("Missing")
```

- [x] **Step 2: 运行测试并确认 RED**

Run: `rtk uv run pytest -q tests/test_tools.py -k 'completion or required'`

Expected: FAIL，原因是字段或 registry API 尚不存在。

- [x] **Step 3: 最小实现 ToolOutcome 与 ToolRegistry 契约**

在 `ToolOutcome` 增加默认 false 字段；registry 保存可选 required name，要求 name 已注册，并拒绝与已有不同的第二个 required name。

- [x] **Step 4: 写 Step 顺序截断与双通道失败测试**

覆盖：成功 completion tool 立即 `COMPLETED`；提交前工具执行；提交后文本/原生调用均不执行；被截断调用无审计；成功提交不受同响应非致命 parse error 影响。

- [x] **Step 5: 运行 Step 测试并确认 RED**

Run: `rtk uv run pytest -q tests/test_step.py -k 'completion_tool or required_submission or dual_channel'`

Expected: FAIL，原因是 Step 仍会分派 Submit 后调用或等待 standalone status。

- [x] **Step 6: 最小实现 Step 终止与一次恢复**

按 parser 输出顺序分派；首个 `success and completes_task` outcome 设置 `COMPLETED` 并 break。`task_status.completed` 缺 required tool 时首次反馈、第二次 FAILED；从 registry 元数据取名称，删除硬编码 Submit 名称。

- [x] **Step 7: 验证 Task 1 GREEN**

Run: `rtk uv run pytest -q tests/test_tools.py tests/test_step.py`

Expected: PASS。

### Task 2: 三个结构化 Submit 工具与 Candidate 原子状态

**Files:**
- Modify: `src/forgeagent/collaboration.py`
- Test: `tests/test_collaboration_tools.py`

**Interfaces:**
- Produces: `SubmitCandidateArgs`（零字段、extra forbid）
- Produces: `SubmitCandidateTool(store, state)`
- Produces: `build_generator_registry(registry, store, state) -> ToolRegistry`
- Consumes: Task 1 的 `completes_task` 与 `require_completion`

- [x] **Step 1: 写 Submit 工具原子状态失败测试**

覆盖：SubmitPlan 成功即 completes；SubmitCandidate 执行 `phase=evaluator`、Generator attempt +1、清空旧 verdict；SubmitEvaluation 保存排序后的完整 verdict、Evaluator attempt +1 并保持 evaluator phase；错误 phase、stale revision、重复提交失败且状态不变。

- [x] **Step 2: 运行工具测试并确认 RED**

Run: `rtk uv run pytest -q tests/test_collaboration_tools.py`

Expected: FAIL，原因是 Candidate 工具不存在且现有 Submit 未终止/计数。

- [x] **Step 3: 最小实现 Args、工具和 registry 组合**

三个 registry 各登记唯一 required Submit。Generator registry 在调用方提供的现有 registry 上注册本 attempt 的 Candidate 工具，不移除 Checkpoint、FileWrite、MCP 或 Skill。

- [x] **Step 4: 验证 Task 2 GREEN**

Run: `rtk uv run pytest -q tests/test_collaboration_tools.py tests/test_tools.py tests/test_step.py`

Expected: PASS。

### Task 3: Runner 成功/失败边界与恢复状态机

**Files:**
- Modify: `src/forgeagent/collaboration.py`
- Test: `tests/test_collaboration_runner.py`
- Test: `tests/test_collaboration_planner.py`

**Interfaces:**
- Consumes: Task 2 的三个 Submit 原子状态
- Produces: 成功提交不双计 attempt；失败角色仍计数；evaluator+verdict 恢复直接判定

- [x] **Step 1: 将 Runner replay 测试改为 Submit 即完成并观察 RED**

Generator script 使用 `SubmitCandidate`，Evaluator script 只需 `SubmitEvaluation`。断言 rounds 减少、attempt 精确、拒绝反馈保留、下一 Candidate 清空旧 verdict。

- [x] **Step 2: 增加三条恢复路径失败测试**

覆盖 `generator + old verdict`、`evaluator + empty verdict`、`evaluator + non-empty verdict`；最后一种不得创建 Evaluator Task 或增加 attempt。

- [x] **Step 3: 运行 Runner/Planner 测试并确认 RED**

Run: `rtk uv run pytest -q tests/test_collaboration_runner.py tests/test_collaboration_planner.py`

Expected: FAIL，原因是 Runner 仍以普通 Task completion 推进、重复计数或重复运行 Evaluator。

- [x] **Step 4: 最小重构 Runner 边界**

角色开始前保存 state。成功 Submit 后加载并验证 phase/attempt/verdict invariant，只补 rounds/usage；无成功 Submit 的失败角色补 attempt。把 verdict 判定抽成 Runner 内部路径，恢复时先消费已持久 verdict。

- [x] **Step 5: 验证 Task 3 GREEN**

Run: `rtk uv run pytest -q tests/test_collaboration_runner.py tests/test_collaboration_planner.py tests/test_collaboration_tools.py`

Expected: PASS。

### Task 4: 提示协议、Loop 组合与兼容回归

**Files:**
- Modify: `src/forgeagent/collaboration.py`
- Modify: `tests/test_collaboration_integrations.py`
- Modify: `tests/test_loop_runner.py`
- Modify: `tests/test_collaboration_planner.py`

**Interfaces:**
- Consumes: `SubmitCandidate` 的零载荷 ToolCall schema
- Produces: 三角色准确 prompt；Loop collaboration 保留 loop registry 并增加 Candidate 门

- [x] **Step 1: 写提示与模式失败测试**

断言三个 prompt 说明 Submit 成功即完成且不要求 standalone status；Generator 展示 `{}` schema 和 Evaluator 独占验收。Loop duo/triad 的 Generator registry 同时包含 Checkpoint 与 SubmitCandidate；single/Loop single 无 required completion tool。

- [x] **Step 2: 运行模式测试并确认 RED**

Run: `rtk uv run pytest -q tests/test_collaboration_integrations.py tests/test_loop_runner.py tests/test_collaboration_planner.py`

Expected: FAIL，原因是 prompt/registry 仍是旧协议。

- [x] **Step 3: 最小更新提示与组合逻辑**

删除“等待反馈后 standalone completed”文案；Generator 明确 restricted Exec/FileWrite 视图边界。不得修改权限、默认工具或 Loop budget/checkpoint 语义。

- [x] **Step 4: 验证 Task 4 GREEN**

Run: `rtk uv run pytest -q tests/test_collaboration_integrations.py tests/test_loop_runner.py tests/test_collaboration_planner.py tests/test_collaboration_runner.py`

Expected: PASS。

### Task 5: 全量验证、真实模型验收与收尾

**Files:**
- Modify: `openspec/changes/fix-collaboration-role-protocol/tasks.md`
- Create: `docs/superpowers/reports/2026-07-25-collaboration-role-submission-verify.md`

**Interfaces:**
- Consumes: Tasks 1-4 完整实现
- Produces: 自动测试、代码审查与两次真实 Triad 的可审计证据

- [x] **Step 1: 运行静态与完整自动验证**

Run: `rtk uv run ruff check src tests`

Run: `rtk uv run ruff format --check src tests`

Run: `rtk uv run pytest -q`

Expected: 全部 PASS；记录精确计数。

- [x] **Step 2: 请求标准代码审查并修复 Critical/Important 发现**

以 base-ref `1ba638b7fce626908e3dfe79cc9baf4f15a705c4` 到当前 diff 为范围，重点审查 Step 通用性、CAS invariant、attempt 双计、恢复和 single/Loop 兼容。

- [x] **Step 3: 在两个新临时目录连续运行真实模型 Triad**

每次运行用户原始 calc.py/test_calc.py 任务，要求最终 `completed`，且无 `invalid_role_submission`。

- [x] **Step 4: 独立验证每个真实产物目录**

Run: `~/ForgeAgent/.venv/bin/python -m pytest -q`

Run: `~/ForgeAgent/.venv/bin/python calc.py '[1,2,3,4]' 2`

Expected: pytest PASS；CLI 精确输出 `[1.5,2.5,3.5]`。

- [x] **Step 5: 写验证报告并勾选 OpenSpec tasks**

报告记录命令、结果、真实 collaboration id、计数和任何限制，不保存模型原始回复或 secret。

- [x] **Step 6: 运行 Comet build guard**

Run: `rtk node .agents/skills/comet/scripts/comet-guard.mjs fix-collaboration-role-protocol build --apply`

Expected: 全部 PASS 并进入 verify。

## Plan Self-Review

- Spec coverage：三个 delta requirements 分别由 Tasks 1-4 实现，Task 5 覆盖全部验收门。
- Placeholder scan：无 TBD/TODO/“稍后实现”；每项包含精确文件、命令和预期结果。
- Type consistency：统一使用 `completes_task`、`required_completion_tool`、`require_completion`、`SubmitCandidateArgs/Tool`；后续任务不另造同义接口。
