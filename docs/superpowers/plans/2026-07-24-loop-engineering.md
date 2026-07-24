---
change: loop-engineering
design-doc: docs/superpowers/specs/2026-07-24-loop-engineering-design.md
base-ref: d24abc04fa5f92c64621b2dd5d22ee598031a860
---

# M21 Loop Engineering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 `Task` 上方交付可由 CLI/HTTP/外部调度器触发、可 checkpoint/resume、受累计预算约束且不会无限重试的轻量持久化 Loop。

**Architecture:** 新增一个集中式 `loop.py`，用严格 Pydantic snapshot、原子 JSON store、Loop-only `Checkpoint` 工具和串行 `LoopRunner` 组合现有 Task。CLI 与 HTTP 只做薄接线；普通 Task、Step、Evaluator、trusted golden 行为保持不变。

**Tech Stack:** Python 3.11+、Pydantic v2、标准库 `tempfile/os/threading/json/time`、现有 pytest/Ruff/uv/OpenSpec；不新增依赖。

## Global Constraints

- OpenSpec delta specs 是行为事实源；Design Doc 是实现事实源。
- 不修改 `Step` 的单 Task 状态机，不序列化 conversation、Runtime、CodeBlockStore、executor 或未提交副作用。
- checkpoint schema 固定为 `forgeagent.loop.v1`，默认 `max_rounds=50`、`wall_clock_seconds=3600.0`、`max_consecutive_failures=3`，新 Loop 必须显式提供正整数 `token_budget`。
- checkpoint 固定在 `<allowed_root>/.forgeagent/loops/<32-hex-loop-id>.json`；拒绝 symlink、路径逃逸、未知字段、非有限数字和超限内容；写入使用 sibling temp、flush/fsync、`os.replace`，失败保留旧 snapshot。
- 普通 `run`、REPL 和普通 HTTP `{"goal":"..."}` 不创建 checkpoint，不加载或调用 M20 Evaluator。
- 不新增 scheduler daemon、数据库、HTTP endpoint、workflow framework、worktree 自动化或跨进程 exactly-once 承诺。
- 所有生产代码任务严格 TDD：先运行聚焦测试并观察预期失败，再写最小实现，再运行聚焦及相关回归。
- 代码、标识符和公开稳定枚举使用英文；用户文档以中文为主。

---

### Task 1: Strict checkpoint models, store, and Loop-only tool

**Files:**
- Create: `src/forgeagent/loop.py`
- Create: `tests/test_loop_checkpoint.py`
- Modify: `openspec/changes/loop-engineering/tasks.md`

**Interfaces:**
- Produces `LOOP_SCHEMA`, default/size constants, `LoopCheckpointError`, `LoopBudgets`, `LoopCheckpoint`, `LoopReport`, `CheckpointArgs`, `LoopCheckpointStore`, `CheckpointTool`, and `build_loop_registry(...)`.
- `LoopCheckpointStore(allowed_root: str, *, audit_sink: AuditSink | None = None, task_id: str | None = None)` exposes `create(goal, budgets, *, loop_id=None)`, `load(loop_id)`, and revision-checked `save(checkpoint, *, expected_revision)`.
- `build_loop_registry(*, store, checkpoint, with_mcp, skills)` returns current default tools plus one `Checkpoint` tool; it must not mutate global/default registries.

- [x] **Step 1: Write model and validation RED tests**

Add table-driven tests for defaults, explicit token budget, bool-as-int, zero/negative/nonfinite values, invalid loop IDs, extra fields, control characters, item limits, active/terminal status invariants, and safe `LoopReport` projection.

- [x] **Step 2: Run model tests and verify RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_loop_checkpoint.py -k 'model or budget or report'`

Expected: collection/import failure because `forgeagent.loop` does not exist.

- [x] **Step 3: Implement minimal strict models and constants**

Use frozen/forbid models where mutation is not required. Normalize item tuples with ordered deduplication and fixed limits. Keep validation local to `loop.py`; do not add generic validation helpers elsewhere.

- [x] **Step 4: Run model tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass with pristine output.

- [x] **Step 5: Write store/tool RED tests**

Cover create/load, stable JSON, unknown schema, malformed/nonfinite/oversize input, root/file symlink rejection, path escape prevention, atomic replacement, failed replacement preserving old bytes, temp cleanup, stale revision, completed-item deletion refusal, successful tool commit before return, bounded detail, and registry isolation from ordinary `default_registry()`.

- [x] **Step 6: Run store/tool tests and verify RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_loop_checkpoint.py -k 'store or atomic or symlink or checkpoint_tool or registry'`

Expected: failures for missing store/tool behavior, not fixture errors.

- [x] **Step 7: Implement the atomic store and Checkpoint tool**

Reuse existing project patterns from `evaluation.py`/`identity.py` for `NamedTemporaryFile` + replace and from `tools.py` for `ToolOutcome`. Audit only schema/revision/counters; never goal/path/item/handoff text. Use one store lock and expected revision to prevent lost updates.

- [x] **Step 8: Run Task 1 tests and related regressions**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q \
  tests/test_loop_checkpoint.py tests/test_tools.py tests/test_evaluator.py
```

Expected: all pass.

- [x] **Step 9: Mark OpenSpec tasks 1.1-1.3 complete and commit**

Commit only Task 1 files with message `feat: add durable loop checkpoints`.

### Task 2: LoopRunner, resume, budgets, convergence, and audit

**Files:**
- Modify: `src/forgeagent/loop.py`
- Create: `tests/test_loop_runner.py`
- Modify: `openspec/changes/loop-engineering/tasks.md`

**Interfaces:**
- Produces `LoopRunner.create(...)`, `LoopRunner.resume(...)`, `LoopRunner.run(goal="", *, cancel_event=None) -> LoopReport`, and `LoopRunner.close()`.
- Task construction is injected with a callable receiving iteration number, remaining max rounds, Loop system-prompt suffix, and Loop registry; each returned Task is fresh and is always closed.
- Stop reasons are stable strings: `completed`, `cancelled`, `wall_clock`, `token_usage_unavailable`, `token_budget`, `max_rounds`, `consecutive_failures`, `unrecoverable_failure`, `checkpoint_error`.

- [x] **Step 1: Write basic create/resume/convergence RED tests**

Use real `Task` + MockClient where practical and focused fake Task objects only for clocks/cancellation/process interruption. Cover single-iteration completion, failure summary injected into the next fresh Task, correct failure then success, terminal resume causing zero calls, frozen goal/budgets, completed items in resume prompt, and ordinary prose not counting as completed.

- [x] **Step 2: Run convergence tests and verify RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_loop_runner.py -k 'create or resume or convergence or completed'`

Expected: failures because `LoopRunner` is absent.

- [x] **Step 3: Implement minimal serial runner and bounded handoff**

Build each Task with a fresh registry and prompt suffix, persist an automatic snapshot after every returned Task, and return a report from the terminal snapshot. Mask secrets/control characters in `last_failure`; summarize only stable reason/counts/safe detail.

- [x] **Step 4: Run convergence tests and verify GREEN**

Run the Step 2 command. Expected: pass.

- [x] **Step 5: Write stop-condition and lifecycle RED tests**

Cover exact boundary and resume accumulation for rounds/tokens/wall clock/failures, all-zero successful usage, external cancellation, watchdog cancellation, simultaneous-condition priority, auth/invalid-request unrecoverable classification, network/rate-limit recoverability, run reentrancy, Task/client close on every branch, revision conflicts, and all five audit event types with forbidden-text assertions.

- [x] **Step 6: Run stop tests and verify RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_loop_runner.py -k 'budget or wall or cancel or failure or audit or close or priority'`

Expected: targeted behavior failures.

- [x] **Step 7: Implement stop accounting, timer, failure classification, and audit**

Use one fixed priority function at every safe boundary. Sum `input_tokens + output_tokens + cached_tokens + reasoning_tokens`; do not alter `TokenUsage`. Use `threading.Timer` only for cooperative cancellation and always cancel it in `finally`.

- [x] **Step 8: Run Task 2 and core regressions**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q \
  tests/test_loop_checkpoint.py tests/test_loop_runner.py \
  tests/test_task.py tests/test_step.py tests/test_audit.py
```

Expected: all pass.

- [x] **Step 9: Mark OpenSpec tasks 2.1-2.3 complete and commit**

Commit with message `feat: run bounded resumable loops`.

### Task 3: CLI loop command

**Files:**
- Modify: `src/forgeagent/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `openspec/changes/loop-engineering/tasks.md`

**Interfaces:**
- Adds `forgeagent loop [GOAL] --token-budget INT [--max-rounds INT] [--wall-clock-seconds FLOAT] [--max-consecutive-failures INT] [--resume LOOP_ID]`.
- Adds `run_loop_once(...) -> LoopReport` using current client/identity/memory/skills/MCP/context/tier assembly.
- Output contains only loop ID/status/stop reason/counters; exit codes are completed=0, non-completed terminal=1, validation/checkpoint/preflight=2.

- [ ] **Step 1: Write parser/dispatch/output RED tests**

Cover new goal + required token budget, resume mutual exclusion, bool/zero/negative/nonfinite rejection, defaults, real MockClient completion, resume, no absolute path/goal/handoff/secret output, exit codes, and confirmation that `run`/REPL do not create `.forgeagent/loops` or import Evaluator.

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_cli.py -k 'loop'`

Expected: argparse/attribute failures for missing command.

- [ ] **Step 3: Implement the smallest CLI wiring**

Reuse the existing `run` branch assembly even if a small amount of direct code remains; do not refactor unrelated CLI commands. Catch only documented Loop validation/persistence errors and render fixed safe diagnostics.

- [ ] **Step 4: Run CLI and ordinary command regressions**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q \
  tests/test_cli.py tests/test_task.py tests/test_startup_information.py
```

Expected: all pass.

- [ ] **Step 5: Mark OpenSpec task 3.1 complete and commit**

Commit with message `feat: expose loop CLI`.

### Task 4: HTTP loop mode on the existing task endpoint

**Files:**
- Modify: `src/forgeagent/http_task_service.py`
- Modify: `src/forgeagent/http_server.py`
- Modify: `src/forgeagent/cli.py`
- Modify: `tests/test_http_task_service.py`
- Modify: `tests/test_http_server.py`
- Modify: `tests/test_cli.py`
- Modify: `openspec/changes/loop-engineering/tasks.md`

**Interfaces:**
- Existing `POST /tasks` accepts exactly ordinary Task, new Loop, or resume Loop key sets described by the Design Doc.
- `TaskRecord.public_view()` always adds `mode`; Loop terminal views add bounded report counters only.
- The worker factory may return `Task` or `LoopRunner`, both exposing compatible `run(..., cancel_event=...)` and `close()`.

- [ ] **Step 1: Write service runner/public-view RED tests**

Cover ordinary Task compatibility, Loop result projection, running Loop view, queued/running/terminal cancellation, TTL/capacity, two Loop isolation, same-ID overlapping resume fail closed, resource close, and no checkpoint text/path in public snapshots.

- [ ] **Step 2: Run service tests and verify RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_http_task_service.py -k 'loop or mode or ordinary'`

Expected: missing mode/Loop support failures.

- [ ] **Step 3: Generalize the worker without duplicating registry logic**

Introduce the smallest local protocol/type union required. Preserve existing Task branches and error projection. Store LoopReport privately; do not convert it into fake `TaskOutcome` rounds.

- [ ] **Step 4: Write strict HTTP body RED tests**

Cover all three accepted key sets, unknown/security-sensitive fields, bool-as-int/nonfinite/range errors, resume with goal/budgets, server-owned checkpoint root, submit/query/cancel audit and safe response.

- [ ] **Step 5: Run handler tests and verify RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_http_server.py -k 'loop or submit or invalid_request'`

Expected: Loop bodies rejected before implementation.

- [ ] **Step 6: Implement handler parsing and server factory selection**

Keep `/tasks` as the only submit endpoint. Validate exact key sets before calling service. `serve_http` derives Loop store from existing `allowed_root`; HTTP callers never pass checkpoint paths, tier, model, identity, confirmer or credentials.

- [ ] **Step 7: Run HTTP/CLI integration regressions**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q \
  tests/test_http_task_service.py tests/test_http_server.py tests/test_cli.py \
  tests/test_http_config.py tests/test_headless.py
```

Expected: all pass; loopback-only tests may require the already-approved elevated rerun for final verification, not test weakening.

- [ ] **Step 8: Mark OpenSpec task 3.2 complete and commit**

Commit with message `feat: submit loops over HTTP`.

### Task 5: User documentation, example, security/spec synchronization

**Files:**
- Modify: `README.md`
- Modify: `docs/text-protocol-spec.md`
- Modify: `docs/threat-model.md`
- Modify: `docs/golden-tasks-seed.md`
- Modify: `ACTION_PLAN.md`
- Create: `examples/loop/dependency-report.md`
- Create: `examples/loop/README.md`
- Create: `tests/test_loop_docs.py`
- Modify: `openspec/changes/loop-engineering/tasks.md`

**Interfaces:**
- Documents CLI new/resume, HTTP bodies, checkpoint commit semantics, scheduler examples, stop reasons, cost boundary, cooperative timeout, cross-process overlap limitation, and M20/M22 exclusions.
- Adds an M21 threat entry for checkpoint injection/path/race/replay risks and mitigations.
- The example only reports dependency state; it does not install/update dependencies, create branches, commit, push, or open PRs.

- [ ] **Step 1: Write documentation assertion RED tests or extend existing static tests**

Create `tests/test_loop_docs.py` with direct text assertions against `README.md`, `docs/text-protocol-spec.md`, `docs/threat-model.md`, `docs/golden-tasks-seed.md`, `ACTION_PLAN.md`, and both `examples/loop/` files. Assert command syntax, `forgeagent.loop.v1`, every stable stop reason, Loop-only Checkpoint, no scheduler daemon, explicit Evaluator/Triad exclusions, and that the example contains no install/update/commit/push/PR action.

- [ ] **Step 2: Run documentation tests and verify RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_loop_docs.py`

Expected: assertions fail because M21 documentation/example text is absent.

- [ ] **Step 3: Write minimal synchronized documentation and example**

Provide cron, launchd plist command arguments, systemd timer/service command, and HTTP examples without credentials. Mark scheduler snippets as user-installed examples. Update ACTION_PLAN M21 evidence only with commands actually run later; until Task 6, state implementation pending or omit final counts.

- [ ] **Step 4: Run documentation/static tests and verify GREEN**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q \
  tests/test_loop_docs.py tests/test_protocol.py tests/test_golden_runner.py
```

Expected: all pass.

- [ ] **Step 5: Mark OpenSpec tasks 3.3 and 4.3 complete and commit**

Commit with message `docs: explain loop engineering`.

### Task 6: M21 verification, reviews, evidence, and build handoff

**Files:**
- Modify: `openspec/changes/loop-engineering/tasks.md`
- Modify: `ACTION_PLAN.md`
- Create: `docs/superpowers/reports/2026-07-24-loop-engineering-verify.md`
- Do not create `milestones/milestone_021.md` until verify and archive are complete.

**Interfaces:**
- Verification report maps every delta requirement/scenario and OpenSpec task to implementation/test evidence, includes exact outputs, accepted limitations, review findings/fixes, and verified commit.

- [ ] **Step 1: Run focused M21 tests**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q \
  tests/test_loop_checkpoint.py tests/test_loop_runner.py \
  tests/test_cli.py tests/test_http_task_service.py tests/test_http_server.py
```

Expected: all pass.

- [ ] **Step 2: Run Ruff and diff checks**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run ruff format --check .
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run ruff check .
git diff --check d24abc04fa5f92c64621b2dd5d22ee598031a860..HEAD
```

Expected: exit 0.

- [ ] **Step 3: Run complete suite with required permissions**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q`

If sandbox output shows loopback or nested build permission failures, rerun the exact command with approved escalation. Expected final evidence: zero failures.

- [ ] **Step 4: Run trusted golden, package build, and OpenSpec validation**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run python -m tests.golden.runner \
  --output-dir /tmp/forgeagent-m21-golden
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv build \
  --out-dir /tmp/forgeagent-m21-dist
openspec validate --all --strict
```

Expected: trusted golden reports 20/20 and both remaining commands exit 0.

- [ ] **Step 5: Perform independent whole-change code review**

Review the full diff from base-ref for correctness, checkpoint security/data loss, cancellation/concurrency, budget off-by-one, public disclosure, ordinary-path regression, tests, and YAGNI. Fix every Critical/Important finding with a failing regression test first; rerun relevant verification and request re-review until clean.

- [ ] **Step 6: Perform two final self-reviews**

First pass: requirement-by-requirement OpenSpec/Design/plan coverage and internal consistency. Second pass: code/data-flow review for stale revision, duplicate side effects, timer races, close paths, secret/path leaks, M20/M22 scope creep, missing docs/tests. Immediately fix and verify any issue.

- [ ] **Step 7: Write verification report and final evidence**

Record exact command outputs, review findings/fixes, known limitations, final HEAD, and confirmation that evaluator is not automatic. Update ACTION_PLAN M21 status using only fresh evidence.

- [ ] **Step 8: Mark all remaining OpenSpec tasks complete and commit**

Commit with message `chore: verify M21 loop engineering`. Then run the Comet build guard; archive/milestone work occurs only after verify passes.
