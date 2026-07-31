---
change: define-duo-acceptance-contract
design-doc: docs/superpowers/specs/2026-07-31-define-duo-acceptance-contract-design.md
base-ref: 853789103f24001a67a01de8d1ee3848da6ac35c
---

# Duo Acceptance Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让新建 Duo 从 goal 的交付形态生成确定、可直接观察且不泄漏的冻结验收契约。

**Architecture:** 在 `collaboration.py` 内保留现有 `_duo_plan(goal)` 接口和单项 `goal` ID，只增加有限关键词集合与三类固定模板。测试独立放在新的 focused 文件，旧 store/runner/tools 契约不改形状。

**Tech Stack:** Python 3.11+、Pydantic v2、pytest、Ruff、OpenSpec strict。

## Global Constraints

- 不引入 LLM 自动拆解器、新依赖、配置或动态计划项。
- 保持 `AcceptanceItem(id="goal")`、旧 snapshot 和 SubmitEvaluation 覆盖兼容。
- 模板 English-first，不包含 raw goal、绝对路径、secret 或原始 prompt。
- 不改变 Triad Planner，不执行 PyPI、tag、push 或发布自动化。

---

### Task 1: Golden acceptance templates

**Files:**
- Modify: `src/forgeagent/collaboration.py:425-434`
- Create: `tests/test_duo_acceptance_contract.py`

**Interfaces:**
- Consumes: `_duo_plan(goal: str) -> tuple[AcceptanceItem, ...]`
- Preserves: one item with `id == "goal"`
- Produces: deterministic artifact, verification, and text evidence templates

- [x] **Step 1: Write failing golden tests**

Add three parameterized cases:

```python
@pytest.mark.parametrize(
    ("goal", "behavior_fragment", "acceptance_fragment"),
    [
        ("Write report.md", "inspectable artifact", "relative artifact"),
        ("Run pytest and verify the build", "verification", "check result"),
        ("Analyze the failure and explain the cause", "concrete response", "response excerpt"),
    ],
)
def test_duo_plan_has_observable_golden_contracts(...):
    item = _duo_plan(goal)[0]
    assert item.id == "goal"
    assert behavior_fragment in item.behavior.casefold()
    assert acceptance_fragment in item.acceptance.casefold()
```

- [x] **Step 2: Verify RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m39-duo-uv-cache rtk uv run pytest -q tests/test_duo_acceptance_contract.py`

Expected: golden fragments fail because every goal still receives the old generic text.

- [x] **Step 3: Implement minimum deterministic templates**

Add bounded file/artifact and verification keyword tuples. `_duo_plan` casefolds goal, selects one of three fixed `(behavior, acceptance)` pairs, and returns the existing single item. Do not interpolate goal text.

- [x] **Step 4: Verify GREEN**

Run the focused test command; expected all golden cases pass.

### Task 2: Compatibility and leakage regression

**Files:**
- Modify: `tests/test_duo_acceptance_contract.py`
- Modify: `tests/test_collaboration_store.py:25-38`

**Interfaces:**
- Preserves: deterministic plan digest for equal inputs
- Preserves: old persisted plan loads without `_duo_plan` recomputation

- [x] **Step 1: Add safety and compatibility tests**

Assert repeated calls are equal; no template contains `original task goal`, raw goal, `/data/input.csv`, or configured secret; a serialized old Duo state with the legacy plan and digest still loads through `CollaborationStore`.

- [x] **Step 2: Run focused Collaboration suites**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m39-duo-uv-cache rtk uv run pytest -q tests/test_duo_acceptance_contract.py tests/test_collaboration_store.py tests/test_collaboration_runner.py tests/test_collaboration_tools.py`

Expected: all pass after updating the single old text assertion to the new observable contract.

### Task 3: Verification and closure

**Files:**
- Modify: `openspec/changes/define-duo-acceptance-contract/tasks.md`
- Create: `docs/superpowers/reports/2026-07-31-define-duo-acceptance-contract-verify.md`

- [x] **Step 1: Run static and strict checks**

Run Ruff check, Ruff format check and OpenSpec strict on this change.

- [x] **Step 2: Run full verification**

Run full pytest and `uv build`; record exact outcomes and confirm no publication action ran.

- [x] **Step 3: Final self-review and task completion**

Review ambiguity, classification precedence, compatibility, leakage and over-design twice. Fix any finding, rerun affected tests, check all OpenSpec and plan tasks, and write the verification report.

## Self-Review

- The plan covers all three golden categories and the no-pseudo-acceptance rule.
- It preserves the single plan item, old snapshots and existing evaluator payload shape.
- It adds no module, abstraction, dependency, configuration or LLM path.
- It verifies path/secret safety and determinism explicitly.
