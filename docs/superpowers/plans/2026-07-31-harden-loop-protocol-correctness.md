---
change: harden-loop-protocol-correctness
design-doc: docs/superpowers/specs/2026-07-31-harden-loop-protocol-correctness-design.md
base-ref: 6a304bc6273a3acfd06aae81dd265ce3eeef6347
---

# Hardening Loop Protocol Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 收紧 Loop checkpoint/report、双通道工具调用、文本安全和模型反馈边界，同时保持旧 JSON 与 M27 迁移兼容。

**Architecture:** 保持现有模块边界：protocol 在解析阶段合并调用，loop 负责 durable model alias，`text_safety.py` 提供纯内部安全 helper，collaboration 仅增加无敏感内容的 projection 日志。Step 继续只分发 parser 输出，不新增 dispatch 重试或启发式去重。

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, Ruff, OpenSpec strict。

## Global Constraints

- 保持公开 JSON 键 `schema` 与旧 checkpoint 加载能力。
- 不改变 M27 Duo/Triad 缺失 source 迁移语义。
- 只对显式相同 tool-call ID 去重；冲突 ID 不执行。
- 不新增依赖，不处理 Loop handoff 结构化或 Collaboration stop-reason 映射。
- 不执行 PyPI、tag、push 或发布自动化。

### Task 1: Loop schema aliases and legacy compatibility

**Files:**
- Modify: `src/forgeagent/loop.py:170-370`
- Test: `tests/test_loop_checkpoint.py`

**Interfaces:**
- Produces `LoopCheckpoint` and `LoopReport` models that accept and emit the public `schema` key through Pydantic aliases.

- [x] **Step 1: Write the failing tests**

Add tests that validate a legacy JSON dict with `schema`, assert `model_dump(by_alias=True)` contains `schema` and not `schema_`, and assert the existing M27 migration test still maps legacy collaborative checkpoints to `explicit`.

- [x] **Step 2: Run tests to verify they fail**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m39-review-uv-cache rtk uv run pytest -q tests/test_loop_checkpoint.py`
Expected: alias serialization assertions fail before implementation.

- [x] **Step 3: Write minimal implementation**

Remove warning suppression, set `model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True, serialize_by_alias=True)`, and replace both `schema` declarations with `schema_: Literal[LOOP_SCHEMA] = Field(default=LOOP_SCHEMA, alias="schema")`.

- [x] **Step 4: Run tests to verify they pass**

Run the same focused command; expected all checkpoint tests pass.

- [x] **Step 5: Commit**

`git add src/forgeagent/loop.py tests/test_loop_checkpoint.py && git commit -m "fix: use stable loop schema aliases"`

### Task 2: Dual-channel tool-call identity

**Files:**
- Modify: `src/forgeagent/protocol.py:45-220, 430-470`
- Test: `tests/test_protocol.py`

**Interfaces:**
- `parse()` returns at most one dispatchable call per explicit ID and emits a bounded `ParseError` for conflicting duplicate IDs.

- [x] **Step 1: Write the failing tests**

Add text/native tests for equivalent duplicate IDs (one call), conflicting same IDs (parse error and zero calls for that ID), and distinct IDs (both calls).

- [x] **Step 2: Run tests to verify they fail**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m39-review-uv-cache rtk uv run pytest -q tests/test_protocol.py`
Expected: duplicate currently yields two calls and conflict has no error.

- [x] **Step 3: Write minimal implementation**

Add a deterministic post-parse merge helper comparing `name` and `arguments.model_dump(mode="python")`; preserve first-seen order, append `INVALID_FORMAT` with a bounded message for conflicts, and remove conflicted IDs from the final list.

- [x] **Step 4: Run tests to verify they pass**

Run the same command; expected protocol tests pass.

- [x] **Step 5: Commit**

`git add src/forgeagent/protocol.py tests/test_protocol.py && git commit -m "fix: deduplicate dual-channel tool calls"`

### Task 3: Empty prose and private helper ownership

**Files:**
- Modify: `src/forgeagent/step.py:50-80`
- Test: `tests/test_step.py`

**Interfaces:**
- Empty/whitespace prose remains `EMPTY_RESPONSE`; `_apply_edit` is imported from `forgeagent.tools`, not re-exported by `step`.

- [x] **Step 1: Write the failing tests**

Add a two-round Step regression where both bodies are empty/whitespace and assert no `ANSWERED_IN_PROSE`; update the import ownership assertion to `forgeagent.tools._apply_edit`.

- [x] **Step 2: Run tests to verify they fail**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m39-review-uv-cache rtk uv run pytest -q tests/test_step.py`
Expected: the ownership assertion fails while the empty-body behavior remains covered.

- [x] **Step 3: Write minimal implementation**

Remove `_apply_edit` from `step` imports and `__all__`; retain the existing `if not rr.body` guard and add no new completion path.

- [x] **Step 4: Run tests to verify they pass**

Run the same command; expected all step tests pass.

- [x] **Step 5: Commit**

`git add src/forgeagent/step.py tests/test_step.py && git commit -m "refactor: keep edit helper private to tools"`

### Task 4: Shared safe text and English feedback

**Files:**
- Create: `src/forgeagent/text_safety.py`
- Modify: `src/forgeagent/loop.py:8-115`, `src/forgeagent/collaboration.py:1-130`, `src/forgeagent/external_actions.py:1-70`, `src/forgeagent/tools.py:55-85`
- Test: `tests/test_loop_checkpoint.py`, `tests/test_collaboration_handoff.py`, `tests/test_tools.py`, `tests/test_step.py`

**Interfaces:**
- `forgeagent.text_safety.safe_text(value, field, maximum, allow_empty)` preserves existing caller semantics.

- [x] **Step 1: Write the failing tests**

Add direct helper tests for control/format characters, maximum length, blank rejection, and allow-empty preservation; update continuation assertions to English-first phrases.

- [x] **Step 2: Run tests to verify they fail**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m39-review-uv-cache rtk uv run pytest -q tests/test_loop_checkpoint.py tests/test_collaboration_handoff.py tests/test_tools.py tests/test_step.py`
Expected: helper import/English assertions fail.

- [x] **Step 3: Write minimal implementation**

Move the shared Unicode category check into `text_safety.py`, replace three local implementations, and rewrite only model-facing continuation constants in `tools.py` to concise English while retaining symbolic names and length limits.

- [x] **Step 4: Run tests to verify they pass**

Run the same focused command; expected all tests pass.

- [x] **Step 5: Commit**

`git add src/forgeagent/text_safety.py src/forgeagent/loop.py src/forgeagent/collaboration.py src/forgeagent/external_actions.py src/forgeagent/tools.py tests && git commit -m "refactor: share safe text and normalize feedback"`

### Task 5: Fixed-type projection diagnostics

**Files:**
- Modify: `src/forgeagent/collaboration.py:1-20, 686-730`
- Test: `tests/test_collaboration_handoff.py`

**Interfaces:**
- Capability and receipt projection fallbacks emit stable warning records with event name and exception type only.

- [x] **Step 1: Write the failing tests**

Use failing registry/receipt doubles and `caplog` to assert fixed event names, exception type presence, and absence of exception text, absolute paths, or secret values.

- [x] **Step 2: Run tests to verify they fail**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m39-review-uv-cache rtk uv run pytest -q tests/test_collaboration_handoff.py`
Expected: no projection log records exist.

- [x] **Step 3: Write minimal implementation**

Add a module logger and warning calls such as `handoff.capability_projection_failed` and `handoff.receipt_projection_failed`, passing only `type(exc).__name__`; preserve safe empty/unavailable fallback.

- [x] **Step 4: Run tests to verify they pass**

Run the same command; expected collaboration handoff tests pass.

- [x] **Step 5: Commit**

`git add src/forgeagent/collaboration.py tests/test_collaboration_handoff.py && git commit -m "fix: make handoff projection failures observable"`

### Task 6: Final change verification

**Files:**
- Modify: `openspec/changes/harden-loop-protocol-correctness/tasks.md`

- [x] **Step 1: Run focused and static checks**

Run focused pytest, `rtk ruff check src tests`, `rtk ruff format --check src tests`, and `rtk openspec validate --strict`.

- [x] **Step 2: Run full pytest with temporary uv cache**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m39-review-uv-cache rtk uv run pytest -q`
Record any environment-only loopback/offline build failures without changing product code.

- [x] **Step 3: Mark tasks complete**

Check off Tasks 1-6 only after their tests and checks pass; preserve evidence in the Comet verification report.

- [x] **Step 4: Commit task state**

`git add openspec/changes/harden-loop-protocol-correctness/tasks.md && git commit -m "chore: complete loop protocol hardening tasks"`

## Self-Review

- All three delta specs map to Tasks 1-4.
- M27 migration compatibility is explicitly tested and unchanged.
- No task introduces dependencies, publication, or unrelated handoff/stop-reason redesign.
- Full-suite environment failures are evidence to record, not reasons to alter runtime behavior.
