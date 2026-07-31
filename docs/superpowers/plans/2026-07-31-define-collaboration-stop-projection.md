---
change: define-collaboration-stop-projection
design-doc: docs/superpowers/specs/2026-07-31-define-collaboration-stop-projection-design.md
base-ref: cb5efb6ce33d55f3264e4607ec0b4a902a8afeb9
archived-with: 2026-07-31-define-collaboration-stop-projection
---

# Collaboration Stop Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Collaboration 建立完整、可恢复且不泄漏的 Task/Loop 停止原因投影，并分离内部执行 goal 与公开 handoff goal。

**Architecture:** 在 `collaboration.py` 内增加一个小型纯投影函数和固定原因集合；CollaborationState/Report 只附加可选 Attention。角色执行 JSON 继续携带 validated raw goal，HandoffPacket 构造点显式生成 public goal；不新增模块、依赖或配置。

**Tech Stack:** Python 3.11+、Pydantic v2、pytest、Ruff、OpenSpec strict。

## Global Constraints

- 保留具体资源原因，不压缩为通用 `resource_exhausted`。
- `needs_info` 映射 `needs_input`；`blocked` 与 `external_action_pending` 保持可恢复阻塞。
- 旧 Collaboration JSON 缺 attention 时继续加载；single TaskOutcome 不变。
- 内部执行 goal 可保留合法绝对路径；公开 handoff/report/audit 不得包含绝对路径、secret、raw goal、原始 prompt 或异常正文。
- 不新增依赖、通用状态机、Loop 嵌套、HTTP endpoint、PyPI、tag、push 或发布自动化。

archived-with: 2026-07-31-define-collaboration-stop-projection
---

### Task 1: Stop projection contract

**Files:**
- Modify: `src/forgeagent/collaboration.py:430-475, 518-900, 2361-2403`
- Test: `tests/test_collaboration_models.py`
- Test: `tests/test_collaboration_runner.py`

**Interfaces:**
- Produces: `_project_collaboration_stop(reason: str, attention: Attention | None = None) -> tuple[Literal["stopped", "cancelled", "failed"], str, Attention | None]`
- Produces: optional `CollaborationState.attention` and `CollaborationReport.attention`

- [x] **Step 1: Write failing mapping and model tests**

Add a parameterized matrix for needs input, blocked, external action, five resource reasons, cancellation, unrecoverable reasons and unknown failure. Add state/report validation tests for matching attention and legacy JSON without the field.

- [x] **Step 2: Verify RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m39-review-uv-cache rtk uv run pytest -q tests/test_collaboration_models.py tests/test_collaboration_runner.py`
Expected: import/field/reason assertions fail because the projection helper and report attention do not exist.

- [x] **Step 3: Implement the minimum projection**

Add fixed reason sets and the pure helper; extend `_STOP_REASONS`, State/Report fields and validators; make `_task_failure()` call the helper and pass attention to `_finish()`.

- [x] **Step 4: Verify GREEN**

Run the same focused command; expected all tests pass.

### Task 2: Execution/public goal separation

**Files:**
- Modify: `src/forgeagent/collaboration.py:136-148, 732-790, 1723-1755`
- Test: `tests/test_collaboration_handoff.py`

**Interfaces:**
- Produces: `_public_handoff_goal(goal: str) -> str`
- Preserves: `_role_task_data(...)["goal"] == state.goal`

- [x] **Step 1: Write failing trust-boundary tests**

Create a goal containing `/data/input.csv`, a configured secret and a control character. Assert internal role task data retains the validated execution path, public handoff masks it, and audit/report contain neither path, secret nor raw goal.

- [x] **Step 2: Verify RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m39-review-uv-cache rtk uv run pytest -q tests/test_collaboration_handoff.py`
Expected: explicit execution/public projection contract assertion fails before the named boundary exists.

- [x] **Step 3: Implement explicit public projection**

Use one named helper at `build_handoff_packet()` while leaving `_role_task_data` and `_planner_task_data` on `state.goal`. Do not add a second persisted goal field.

- [x] **Step 4: Verify GREEN**

Run the same focused command; expected all handoff tests pass.

### Task 3: Integration and verification

**Files:**
- Modify: `openspec/changes/define-collaboration-stop-projection/tasks.md`
- Create: `docs/superpowers/reports/2026-07-31-define-collaboration-stop-projection-verify.md`

- [x] **Step 1: Run integration tests**

Run Collaboration, Loop and HTTP focused suites to confirm stable reason/attention projection and no compatibility regression.

- [x] **Step 2: Run static and strict checks**

Run Ruff check, Ruff format check and OpenSpec strict validation.

- [x] **Step 3: Run full verification**

Run full pytest and `uv build`; record exact evidence and confirm no publication action ran.

- [x] **Step 4: Final self-review and task completion**

Review the diff twice for ambiguity, incorrect grouping, over-conservatism, inconsistency and leakage; fix any issue, rerun affected tests, then check all OpenSpec tasks.

## Self-Review

- The plan covers both modified capabilities and every M39 second-change acceptance condition.
- No new helper/module is added beyond one private pure function; no new dependency or configuration surface exists.
- Resource reasons remain observable, while unknown reasons fail closed.
- The execution/public goal test prevents both path loss and public leakage.
