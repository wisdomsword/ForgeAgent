---
change: triad-mode
design-doc: docs/superpowers/specs/2026-07-24-triad-mode-design.md
base-ref: 2433b7689f275caef4e42c991317934d615aeb36
---

# Triad Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in Duo and Planner-confirmed Triad runtime collaboration so independent evaluation, not Generator self-assessment, determines completion.

**Architecture:** Add one Task-level `CollaborationRunner` with strict structured Planner/Evaluator submissions and a symlink-safe atomic state store. Keep every role in a fresh Task/client/runtime/registry, expose the runner through existing CLI/REPL/HTTP/Loop boundaries, and leave single-role Task/Step behavior unchanged.

**Tech Stack:** Python 3.11+, Pydantic v2, existing ForgeAgent Task/ToolRegistry/Audit/Loop abstractions, pytest, Ruff, uv, OpenSpec.

## Global Constraints

- OpenSpec delta specs under `openspec/changes/triad-mode/specs/` are the canonical behavior contract.
- Follow strict TDD: each production behavior starts with a focused failing test that is observed failing for the intended reason.
- Do not add dependencies, endpoints, daemons, databases, workflow frameworks, provider-specific logic, or public resume APIs.
- Do not modify `Step` completion semantics or the existing `TaskOutcome` shape for single mode.
- Planner, Generator and Evaluator use fresh Task/client/runtime/registry instances; role conversations and mutable runtime state never cross roles.
- Evaluator v1 registers only `FileRead`, `FileList` and `SubmitEvaluation`; it has no Exec, write, edit, web, MCP, Skill or Survey tool.
- Confirmed Planner items and their digest are immutable; any deletion, reorder, replacement or lowered standard fails closed.
- Programming-task routing is deterministic and table-driven; no model call is used for classification.
- Public reports and audit events never contain full goals, plan/verdict text, prompts, raw replies, tool arguments, file contents, credentials or absolute host paths.
- Preserve all pre-existing untracked user/auxiliary files and do not stage them.

---

### Task 1: Collaboration Models, Store, Tools, and Routing

**Files:**
- Create: `src/forgeagent/collaboration.py`
- Create: `tests/test_collaboration_models.py`
- Create: `tests/test_collaboration_store.py`
- Create: `tests/test_collaboration_tools.py`
- Create: `tests/test_collaboration_routing.py`

**Interfaces:**
- Produces: `CollaborationMode`, `CollaborationRole`, `AcceptanceItem`, `EvaluationItem`, `CollaborationUsage`, `CollaborationState`, `CollaborationReport`, `ModeDecision`.
- Produces: `CollaborationStore.create/load/save/close`, `SubmitPlanTool`, `SubmitEvaluationTool`, `build_planner_registry()`, `build_evaluator_registry()`, `resolve_collaboration_mode()`.
- Consumes: `AuditSink`, `AuditEvent`, secret masking, `FileReadTool`, `FileListTool`, `ToolRegistry`, `ToolOutcome`, `ToolContext`.

- [x] **Step 1: Write strict model and report tests**

Add tests for strict bool/int rejection, non-finite values, control/format characters, item/byte limits, unique plan IDs, exact evaluation coverage, completed-state invariants, digest stability and public evidence masking.

- [x] **Step 2: Run model tests and observe RED**

Run: `uv run pytest -q tests/test_collaboration_models.py`
Expected: collection/import failure because `forgeagent.collaboration` does not exist.

- [x] **Step 3: Implement the minimum strict models and helpers**

Implement the exact public types listed above, bounded `_safe_text()`, stable plan digest, normalized usage accumulation, state validators and `CollaborationReport.from_state()`.

- [x] **Step 4: Run model tests and observe GREEN**

Run: `uv run pytest -q tests/test_collaboration_models.py`
Expected: all tests pass.

- [x] **Step 5: Write store RED tests**

Cover create/load/save, 0600 atomic replacement, stale revision, symlink root/file, directory inode replacement, corrupt/oversize/unknown schema, replace failure preserving old state and idempotent close. Mirror M21 checkpoint threat vectors without importing its private methods.

- [x] **Step 6: Run store tests and observe RED**

Run: `uv run pytest -q tests/test_collaboration_store.py`
Expected: failures for missing `CollaborationStore` behavior.

- [x] **Step 7: Implement the minimum store**

Use fixed `.forgeagent/collaborations` directory fd, `O_NOFOLLOW`, relative open/replace/fsync, revision compare, size bounds and masked fixed public errors.

- [x] **Step 8: Run store tests and observe GREEN**

Run: `uv run pytest -q tests/test_collaboration_store.py`
Expected: all tests pass.

- [x] **Step 9: Write tools and routing RED tests**

Test plan tool commit-before-success, duplicate/HOW-only rejection, immutable plan digest, evaluation exact ID coverage, read-only evaluator registry, bilingual programming table, explicit-mode conflict and no false positive for explanation/review prose.

- [x] **Step 10: Run tools/routing tests and observe RED**

Run: `uv run pytest -q tests/test_collaboration_tools.py tests/test_collaboration_routing.py`
Expected: failures for missing tools/registries/router.

- [x] **Step 11: Implement tools, registries, and router**

Planner registry contains only `SubmitPlan`; evaluator registry contains only `FileRead`, `FileList`, `SubmitEvaluation`. Implement NFKC/lower/bounded deterministic routing with `allow_weaker_override`.

- [x] **Step 12: Run all Task 1 tests and Ruff**

Run: `uv run pytest -q tests/test_collaboration_models.py tests/test_collaboration_store.py tests/test_collaboration_tools.py tests/test_collaboration_routing.py && uv run ruff check src/forgeagent/collaboration.py tests/test_collaboration_*.py`
Expected: all tests pass and Ruff exits 0.

- [x] **Step 13: Commit Task 1**

Run: `git add src/forgeagent/collaboration.py tests/test_collaboration_models.py tests/test_collaboration_store.py tests/test_collaboration_tools.py tests/test_collaboration_routing.py && git commit -m "feat: add collaboration state foundation"`

### Task 2: Duo Runner and Independent Evaluation Loop

**Files:**
- Modify: `src/forgeagent/collaboration.py`
- Create: `tests/test_collaboration_runner.py`
- Modify: `openspec/changes/triad-mode/tasks.md`

**Interfaces:**
- Consumes: Task 1 state/store/tools and existing `Task`, `TaskOutcome`, `TokenUsage`, `AuditSink`.
- Produces: `RoleTaskBuilder`, `CollaborationRunner.create()`, `.run()`, `.close()` and stable Duo stop reasons.

- [x] **Step 1: Write Duo RED mock replays**

Use real `Task` + `MockClient` role builders to cover Generator strict completion -> Evaluator reject -> fresh Generator fix -> Evaluator pass; wrong completion interception; exact rejection limit; missing/invalid verdict; evaluator refused/failed/client error; cancellation precedence; fresh clients/registries; all resources closed; rounds/usage aggregation.

- [x] **Step 2: Run Duo tests and observe RED**

Run: `uv run pytest -q tests/test_collaboration_runner.py -k duo`
Expected: failures for missing runner.

- [x] **Step 3: Implement minimum Duo state machine**

Create the system `goal` acceptance item, build fresh Generator/Evaluator Tasks, treat Generator completed as submission, require committed evaluator verdict plus standalone completion, persist each boundary, revalidate every item on every attempt and stop at `max_rejections`.

- [x] **Step 4: Run Duo tests and observe GREEN**

Run: `uv run pytest -q tests/test_collaboration_runner.py -k duo`
Expected: all Duo tests pass.

- [x] **Step 5: Add Duo audit and safe prompt tests**

Assert role/evaluation/rejection/stop events contain allowlisted counters and no goal/plan/evidence/path content; assert reject evidence is JSON task data and Generator conversations are fresh.

- [x] **Step 6: Run Task 2 focused regression**

Run: `uv run pytest -q tests/test_collaboration_runner.py tests/test_task.py tests/test_evaluator.py tests/test_audit.py && uv run ruff check src/forgeagent/collaboration.py tests/test_collaboration_runner.py`
Expected: all tests pass and Ruff exits 0.

- [x] **Step 7: Mark OpenSpec Duo tasks and commit**

Mark tasks 1.1-1.4 and 2.1-2.3 complete only after their evidence passes. Commit with `feat: add duo evaluation loop`.

### Task 3: Planner Confirmation and Triad State Machine

**Files:**
- Modify: `src/forgeagent/collaboration.py`
- Modify: `tests/test_collaboration_runner.py`
- Create: `tests/test_collaboration_planner.py`
- Modify: `openspec/changes/triad-mode/tasks.md`

**Interfaces:**
- Produces: `PlanConfirmer`, Triad `CollaborationRunner.create()` path, headless `deny|preauthorize` adapter and stable plan phases.
- Consumes: frozen plan tool/store/digest from Task 1 and Duo loop from Task 2.

- [x] **Step 1: Write Planner/Triad RED tests**

Cover valid plan approve, deny/no confirmer, headless preauthorize, duplicate/HOW-only correction, tool commit + standalone completion, freeze after confirm, delete/reorder/change/digest mismatch, Planner role failures, full Triad reject/fix/pass and all-role context isolation.

- [x] **Step 2: Run Triad tests and observe RED**

Run: `uv run pytest -q tests/test_collaboration_planner.py tests/test_collaboration_runner.py -k triad`
Expected: failures for missing Planner flow.

- [x] **Step 3: Implement minimum Planner and confirmation flow**

Run Planner Task with only `SubmitPlan`, render bounded summary to `PlanConfirmer`, persist approved/denied state, require exact digest at every later boundary and reuse Duo Generator/Evaluator loop after approval.

- [x] **Step 4: Run Triad tests and observe GREEN**

Run: `uv run pytest -q tests/test_collaboration_planner.py tests/test_collaboration_runner.py -k triad`
Expected: all Triad tests pass.

- [x] **Step 5: Run complete collaboration core regression**

Run: `uv run pytest -q tests/test_collaboration_models.py tests/test_collaboration_store.py tests/test_collaboration_tools.py tests/test_collaboration_routing.py tests/test_collaboration_runner.py tests/test_collaboration_planner.py && uv run ruff check src/forgeagent/collaboration.py tests/test_collaboration_*.py`
Expected: all tests pass and Ruff exits 0.

- [x] **Step 6: Mark OpenSpec Triad core tasks and commit**

Mark 3.1-3.3 complete. Commit with `feat: add planner confirmed triad mode`.

### Task 4: CLI, REPL, HTTP, Loop, and Audit Integration

**Files:**
- Modify: `src/forgeagent/cli.py`
- Modify: `src/forgeagent/http_config.py`
- Modify: `src/forgeagent/http_server.py`
- Modify: `src/forgeagent/http_task_service.py`
- Modify: `src/forgeagent/loop.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_http_config.py`
- Modify: `tests/test_http_server.py`
- Modify: `tests/test_http_task_service.py`
- Modify: `tests/test_loop_checkpoint.py`
- Modify: `tests/test_loop_runner.py`
- Create: `tests/test_collaboration_integrations.py`
- Modify: `openspec/changes/triad-mode/tasks.md`

**Interfaces:**
- Consumes: `CollaborationRunner`, `CollaborationReport`, `resolve_collaboration_mode`, `PlanConfirmer`.
- Produces: CLI flags, `/duo`, `/triad`, strict HTTP mode/config, report projections and Loop frozen collaboration fields.

- [x] **Step 1: Write CLI/REPL RED tests**

Cover parser defaults/validation, programming auto-route notice, weaker-mode interactive override, role model preflight, exit codes, safe report output, slash help/completion/missing goal, non-TTY compatibility and ordinary run zero change.

- [x] **Step 2: Run CLI/REPL tests and observe RED**

Run: `uv run pytest -q tests/test_cli.py tests/test_collaboration_integrations.py -k 'collaboration or duo or triad'`
Expected: failures for missing entry wiring.

- [x] **Step 3: Implement CLI/REPL integration**

Add arguments and shared command metadata, construct role clients/backends/tasks without refactoring `run_once`, render only bounded report fields and close all owners.

- [x] **Step 4: Write HTTP RED tests**

Cover strict task/duo/triad/loop bodies, server-owned forbidden fields, plan deny/preauthorize, programming auto-route, public running/terminal phase, cancellation/capacity/TTL/concurrency and no sensitive projection.

- [x] **Step 5: Run HTTP tests and observe RED**

Run: `uv run pytest -q tests/test_http_config.py tests/test_http_task_service.py tests/test_http_server.py -k 'collaboration or duo or triad or mode'`
Expected: failures for missing HTTP support.

- [x] **Step 6: Implement HTTP integration**

Extend config with conservative defaults, strict request parser and runner union; keep endpoint set unchanged and client authority limited to mode/low-risk Loop fields.

- [x] **Step 7: Write Loop RED tests**

Cover old checkpoint defaults to single, new frozen mode/ID/digest, collaborative runner report accumulation, resume mismatch rejection, single Loop no collaboration import/call, and cancellation/usage accounting.

- [x] **Step 8: Run Loop tests and observe RED**

Run: `uv run pytest -q tests/test_loop_checkpoint.py tests/test_loop_runner.py -k collaboration`
Expected: failures for missing frozen fields/runner path.

- [x] **Step 9: Implement Loop integration**

Add optional backwards-compatible checkpoint fields, freeze on create, verify on resume, route each iteration to Task or CollaborationRunner and add all role rounds/tokens to existing cumulative budgets.

- [x] **Step 10: Run Task 4 regression**

Run: `uv run pytest -q tests/test_cli.py tests/test_http_config.py tests/test_http_task_service.py tests/test_http_server.py tests/test_loop_checkpoint.py tests/test_loop_runner.py tests/test_collaboration_integrations.py tests/test_audit.py && uv run ruff check src/forgeagent/cli.py src/forgeagent/http_config.py src/forgeagent/http_server.py src/forgeagent/http_task_service.py src/forgeagent/loop.py tests/test_collaboration_integrations.py`
Expected: all tests pass and Ruff exits 0.

- [x] **Step 11: Mark integration tasks and commit**

Mark 4.1-4.4 complete. Commit with `feat: expose duo and triad runtime modes`.

### Task 5: Documentation, Static Contracts, and Completion Gates

**Files:**
- Modify: `README.md`
- Modify: `docs/text-protocol-spec.md`
- Modify: `docs/http-task-service.md`
- Modify: `docs/threat-model.md`
- Modify: `ACTION_PLAN.md`
- Create: `docs/superpowers/reports/2026-07-24-triad-mode-verify.md`
- Create: `milestones/milestone_022.md`
- Modify: `milestones/latest`
- Modify: documentation/static contract tests selected by repository conventions
- Modify: `openspec/changes/triad-mode/tasks.md`

**Interfaces:**
- Documents all public behavior already implemented; adds no new runtime behavior.

- [ ] **Step 1: Write/update static contract RED tests**

Assert README/HTTP/protocol/threat model state M22 mode names, completion ownership, Planner confirmation, evaluator read-only tools, headless policy, cost boundary, Loop freeze/resume and no new endpoint/dependency.

- [ ] **Step 2: Run static contract tests and observe RED**

Run the focused documentation contract test files discovered via `rg -n 'ACTION_PLAN|README|threat-model|text-protocol|http-task-service' tests`.
Expected: failures for missing M22 documentation.

- [ ] **Step 3: Update documentation and ACTION_PLAN**

Document exact CLI/REPL/HTTP examples, routing precedence, report fields, costs, security boundaries, opt-in real-model comparison and known limitations. Mark M22 in progress until final verification passes.

- [ ] **Step 4: Run focused and full quality gates**

Run, in order:

```bash
uv run pytest -q tests/test_collaboration_models.py tests/test_collaboration_store.py tests/test_collaboration_tools.py tests/test_collaboration_routing.py tests/test_collaboration_runner.py tests/test_collaboration_planner.py tests/test_collaboration_integrations.py
uv run pytest -q
uv run python -m tests.golden.runner --trusted-core
uv run ruff format --check .
uv run ruff check .
uv build
openspec validate --all --strict
git diff --check
```

Expected: every command exits 0; record exact counts/output in the verification report.

- [ ] **Step 5: Complete independent reviews and repair loops**

Run a whole-diff code review, then two explicit self-reviews for requirements/code/docs consistency. For every Critical/Important or self-review defect, add a failing regression test, fix, re-run affected focused tests, then repeat the full gates.

- [ ] **Step 6: Write verification report and milestone**

Create the report with exact commands/results, review findings/fixes, unverified opt-in real-model work and residual risks. Create M22 milestone using `MILESTONE_GUIDE.md`, update `milestones/latest`, mark ACTION_PLAN and all OpenSpec tasks complete only after evidence exists.

- [ ] **Step 7: Commit Task 5**

Commit with `docs: complete M22 triad mode`.
