---
change: external-action-receipts
design-doc: docs/superpowers/specs/2026-07-30-external-action-receipts-design.md
base-ref: 1645e889962739b24afc5becae3675388500b2f6
---

# External Action Receipts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为纳入范围的 MCP 外部动作建立可恢复的 `prepared`/`dispatched`/`confirmed`/`unknown` 收据协议，使结果不确定时 fail closed、暂停 Loop，并要求显式 reconciliation 后才能继续。

**Architecture:** 新增独立的 `forgeagent.external_actions` Pydantic 模型和本地、allowed-root 绑定的原子 JSON 收据存储，复用 `LoopCheckpointStore` 的目录 fd、锁、revision CAS、临时文件 fsync 与脱敏原则。MCP manager 只补充内部 dispatch certainty，`MCPTool` 负责收据状态迁移和审计投影，`LoopRunner` 在构造 Task/模型前检查未决收据；无 MCP 的 Task、auto-approved MCP 路径和现有 confirmation/HTTP allowlist 保持兼容。

**Tech Stack:** Python 3.11、Pydantic v2、标准库 `json`/`hashlib`/`os`/`fcntl`/`uuid`/`datetime`、pytest、Ruff、现有 audit/Loop/MCP 实现；不新增依赖或数据库。

## Global Constraints

- 仅处理 MCP 宿主调用可能造成的外部副作用；不收据化 `FileWrite`、`Exec`、`Edit`、`WebFetch`。
- 不承诺远端 exactly-once、自动补偿编排或 HTTP reconciliation endpoint。
- 收据存储只能位于当前 Task/Loop 的 canonical allowed root 下，拒绝符号链接、目录替换、越界路径、未知 schema/字段和超限文本。
- `unknown` 表示 dispatch 后宿主不能证明远端是否完成；不得在恢复或 `retry_approved` 后静默重放。
- audit sink 失败沿用 degraded 语义；receipt transition 失败必须阻止受保护 MCP dispatch，不能回退到 audit。
- PyPI 发布保持暂停：不上传包、不创建/推送 tag、不推进或归档发布 change。
- 所有实现步骤遵循 TDD、Ponytail/YAGNI；每个任务先写失败测试，再写最小实现，再运行对应 focused tests。
- **兼容性决策必须先锁定：** 当前 `ToolCall.id`/`ToolContext.operation_id` 允许任意非空字符串，而设计中的 `action_id` 要求 32 位十六进制。执行前以回归测试确认不破坏既有调用 ID；推荐 receipt 自行生成 32 位 hex ID，并在 `external_action.receipt` 参数中记录脱敏的 `source_operation_id`，而不是收紧现有 ToolCall ID 或修改所有旧审计事件。

## File Map

- Create: `src/forgeagent/external_actions.py` — 严格收据模型、phase/resolution/certainty 类型、canonical request digest 和安全文件存储。
- Modify: `src/forgeagent/tools.py` — `ToolContext.receipt_store`、MCPTool 收据迁移、固定 unknown feedback、receipt audit 关联。
- Modify: `src/forgeagent/mcp_manager.py` — 保留 `{ok, text}`，增加内部 `dispatch_certainty` 与 no-dispatch/confirmed/unknown 判定。
- Modify: `src/forgeagent/task.py`, `src/forgeagent/step.py` — 可选 store 装配并传入 ToolContext；无 MCP Task 不创建/读取 store。
- Modify: `src/forgeagent/loop.py` — `external_action_pending` 停止语义、create/resume 注入 store、模型/Task 构造前和迭代边界 gate。
- Modify: `src/forgeagent/cli.py`, `src/forgeagent/http_task_service.py` — allowed-root 下创建/传递 store 与 receipts 子命令。
- Create: `tests/test_external_actions.py` — 模型、迁移、并发、文件安全、脱敏和 action-ID 兼容测试。
- Modify: `tests/test_mcp_manager.py`, `tests/test_tools.py`, `tests/test_step.py` — MCP certainty、MCPTool 集成和旧 operation ID 回归。
- Modify: `tests/test_loop_runner.py`, `tests/test_loop_checkpoint.py`, `tests/test_cli.py`, `tests/test_http_task_service.py` — Loop gate、入口装配和 CLI/HTTP 兼容测试。
- Modify: `docs/threat-model.md`, `docs/m7-tools-mcp-survey.md`, `docs/http-task-service.md` — unknown/reconciliation/禁止重放用户契约。

---

### Task 1: 收据模型、ID 兼容决策与安全持久化

**Files:**
- Create: `src/forgeagent/external_actions.py`
- Create: `tests/test_external_actions.py`
- Modify: `docs/superpowers/specs/2026-07-30-external-action-receipts-design.md` only if the action-ID compatibility decision changes the canonical design wording; do not broaden scope.

**Interfaces:**
- Produces `ExternalActionReceipt`, `ExternalActionReceiptStore`, `ReceiptError`, `canonical_request_digest(arguments)`, and typed phase/resolution/certainty literals. The model includes the design's optional `parent_action_id`; a retry creates a new receipt and links it to the prior action.
- `ExternalActionReceiptStore(allowed_root: str, *, audit_sink: AuditSink | None = None, task_id: str | None = None, loop_id: str | None = None)` owns `.forgeagent/receipts` and provides a bounded `load(action_id)`/listing path so CLI resolution can obtain the current revision without reading files directly.
- Store methods are exactly `create_prepared(...)`, `mark_dispatched(action_id, expected_revision)`, `mark_confirmed(action_id, expected_revision, certainty, remote_ok, evidence)`, `mark_unknown(action_id, expected_revision, evidence)`, `list_pending(loop_id=None, task_id=None)`, and `resolve(action_id, expected_revision, decision, evidence)`.

- [x] **Step 1: Write failing model and compatibility tests.**

```python
def test_receipt_id_is_hex_but_existing_operation_id_stays_arbitrary():
    receipt = ExternalActionReceipt.new_prepared(
        task_id="task-1",
        action_type="mcp",
        server_label="fixture",
        tool_label="write",
        request_digest=canonical_request_digest({"value": 1}),
    )
    assert re.fullmatch(r"[0-9a-f]{32}", receipt.action_id)
    ToolCall(id="model-generated-id", name="MCP", arguments=MCPArgs(server="s", tool="t"))
```

  Add tests for every design field (`schema`, optional `parent_action_id`, bounded task/loop IDs, public labels, digest, phase/resolution/certainty, remote result, evidence, revision, timestamps), defaults (`prepared` + `open`), UTC timestamps, 64-hex SHA-256 digest, max lengths, rejection of extra fields, invalid phase transitions, and the no-raw-arguments/no-secret storage contract.

- [x] **Step 2: Run the focused tests and confirm they fail for missing symbols.**

Run: `uv run pytest tests/test_external_actions.py -q`

Expected: FAIL because `forgeagent.external_actions` does not exist yet.

- [x] **Step 3: Implement the strict Pydantic model and canonical digest.**

Use `ConfigDict(extra="forbid", strict=True)` and explicit bounded `Field` constraints. Generate receipt IDs with `uuid4().hex`; canonicalize only the arguments object using sorted, compact JSON and SHA-256. Store only public labels, digest, bounded evidence code/summary, timestamps, task/loop IDs, revision, and state fields. Do not add an idempotency promise or raw identity field.

- [x] **Step 4: Add the symlink-safe atomic store.**

  Mirror `LoopCheckpointStore` rather than introducing a generic persistence abstraction: create `.forgeagent/receipts`, open a directory fd with `O_DIRECTORY|O_NOFOLLOW`, use one `.<action_id>.lock` per receipt, re-read under lock, enforce expected revision, write strict JSON to an exclusive `0600` temporary file, flush/fsync, `os.replace`, fsync the directory, and re-check directory binding. `load/list_pending` must reject malformed JSON, non-finite values, unknown fields/schema, path substitutions, oversized files, and records whose filename/action ID disagree. The public `load` helper must use the same descriptor-relative checks; callers never read receipt JSON directly.

- [x] **Step 5: Implement transitions and resolution separation.**

Permit only `prepared -> dispatched`, `dispatched -> confirmed`, `prepared|dispatched -> unknown`, and resolution changes `open -> confirmed|abandoned|retry_approved` without changing `phase`. `retry_approved` is authorization metadata only; it never calls MCP. `mark_confirmed` accepts `certainty=confirmed|not_dispatched`; `unknown` always records `dispatch_certainty=unknown` and `remote_ok=None`.

- [x] **Step 6: Run the complete storage test set.**

Run: `uv run pytest tests/test_external_actions.py -q`

Expected: PASS for normal transitions, protocol error (`confirmed` with `remote_ok=False`), pre/post-dispatch crash simulations, timeout/cancel evidence, stale revisions, concurrent writes, symlink/directory replacement, bounds, and secret/control-character masking.

### Task 2: MCP dispatch certainty without changing the public result contract

**Files:**
- Modify: `src/forgeagent/mcp_manager.py:1097-1163`
- Modify: `tests/test_mcp_manager.py`

**Interfaces:**
- `MCPManager.call_tool()` continues to return a dict containing `ok` and `text`; add internal `dispatch_certainty` with values `not_dispatched`, `confirmed`, or `unknown`.
- `_call_tool_on_loop()` must distinguish pre-session/no-generation/no-entry paths (`not_dispatched`), any MCP protocol response including `isError=True` (`confirmed`), and exception/cancel/timeout/facade uncertainty (`unknown`).

- [x] **Step 1: Add failing certainty tests around existing fixture sessions.**

Cover unknown server, unavailable server, no live session, generation mismatch, successful MCP response, protocol `isError`, SDK exception, cancellation, and outer facade timeout. Assert old `ok`/`text` values remain masked and stable while certainty is correct.

- [x] **Step 2: Run the focused MCP tests to establish the red state.**

Run: `uv run pytest tests/test_mcp_manager.py -q`

Expected: new certainty assertions fail while existing MCP tests remain the compatibility baseline.

- [x] **Step 3: Implement the smallest internal result extension.**

Return `{"ok": ..., "text": ..., "dispatch_certainty": ...}` from all manager paths. Do not expose SDK exception text. Ensure only a response object proves `confirmed`; an error after entering `session.call_tool` is always `unknown`. Preserve generation invalidation and current timeout ownership.

- [x] **Step 4: Run MCP focused and regression tests.**

Run: `uv run pytest tests/test_mcp_manager.py tests/test_tools.py -q`

Expected: PASS with no changes to existing `ok`/`text`, masking, lifecycle, generation, or timeout tests.

### Task 3: MCPTool receipt state machine and audit projection

**Files:**
- Modify: `src/forgeagent/tools.py:136-165,413-475`
- Modify: `src/forgeagent/task.py:83-145,187-231`
- Modify: `src/forgeagent/step.py:190-264`
- Modify: `tests/test_tools.py`, `tests/test_step.py`, `tests/test_task.py`

**Interfaces:**
- Add optional `receipt_store: ExternalActionReceiptStore | None` to `ToolContext`, `Task`, and `Step`; preserve all existing constructor defaults.
- `MCPTool.run()` creates a receipt only for non-auto-approved, approved MCP calls; rejected confirmation creates no receipt; auto-approved calls retain their direct compatibility path and create no receipt.
- Receipt audit events use `event_type="external_action.receipt"`; parameters contain action ID, phase, resolution, certainty, masked server/tool labels, bounded evidence code, task ID, and source operation ID where needed. No raw arguments, credentials, full exception, or absolute path.

- [ ] **Step 1: Add failing MCPTool tests for gate ordering and four phases.**

Use a fake manager returning each certainty and a temporary store. Assert: missing store denies protected dispatch; store create/transition failure denies manager entry; confirmation denial creates no receipt; auto-approve creates no receipt; response creates `confirmed`; protocol error creates `confirmed` + `remote_ok=False`; timeout/exception creates `unknown` and fixed `result unknown` feedback; `ToolOutcome.success` remains the manager `ok` value.

- [ ] **Step 2: Add operation-ID regression tests.**

Dispatch an MCP `ToolCall` with IDs such as `t1`, `missing-call`, and `model-generated-id`; assert the call succeeds through existing audit/tool dispatch without requiring a 32-hex ID. Assert the receipt has its own valid hex ID and the receipt audit parameters carry the bounded source operation correlation.

- [ ] **Step 3: Run the red focused tests.**

Run: `uv run pytest tests/test_tools.py tests/test_step.py tests/test_task.py -q`

Expected: new receipt assertions fail while existing tool/step/task tests show the compatibility surface.

- [ ] **Step 4: Thread the optional store through Task → Step → ToolContext.**

Pass the exact object without creating a store in ordinary no-MCP Tasks. In `MCPTool.run`, perform confirmation first, then `create_prepared`, then `mark_dispatched`; call manager; map certainty to `mark_confirmed` or `mark_unknown`; on receipt transition errors return a stable failed outcome and never continue an unrecorded protected action. Keep the existing confirmation event and tool operation audit events.

- [ ] **Step 5: Add receipt audit emission after each successful transition.**

Emit only bounded projections. Audit failure must not change pending receipt state; receipt transition failure must fail closed. Use `action_id` as the receipt event operation ID and preserve the original ToolCall operation ID as a masked correlation parameter.

- [ ] **Step 6: Run the focused integration suite.**

Run: `uv run pytest tests/test_external_actions.py tests/test_tools.py tests/test_step.py tests/test_task.py tests/test_mcp_manager.py -q`

Expected: PASS and no regression in confirmation, masking, existing operation IDs, auto-approve, HTTP allowlist, or Task status behavior.

### Task 4: Loop pending gate and entry-point store ownership

**Files:**
- Modify: `src/forgeagent/loop.py:48-58,745-917,925-1011`
- Modify: `src/forgeagent/cli.py:897-1165,2300-2625`
- Modify: `src/forgeagent/http_task_service.py` only where Task/Loop factories need the already resolved allowed root store.
- Modify: `tests/test_loop_runner.py`, `tests/test_loop_checkpoint.py`, `tests/test_cli.py`, `tests/test_http_task_service.py`

**Interfaces:**
- Add `"external_action_pending"` to `LoopStopReason` and the stopped-reason validation set.
- `LoopRunner.create/resume(..., receipt_store: ExternalActionReceiptStore | None = None)` accepts an optional store; when `with_mcp=False` the caller passes `None` and behavior is unchanged.
- `LoopRunner.run()` checks `list_pending(loop_id=checkpoint.loop_id)` after the run lock and before the first `_run_iteration`, then after each `_record_outcome` and before the next iteration. A pending `resolution=open` receipt returns an existing `LoopReport` projection with the new stop reason and must not call a task builder, collaboration builder, model client, or tool.

- [x] **Step 1: Write failing Loop gate tests.**

Create a receipt under the same root/loop ID and assert both fresh `run()` and `resume()` stop with `external_action_pending`, builder call count remains zero, and no fake client/model is constructed. Resolve the receipt as `confirmed`, `abandoned`, or `retry_approved` and assert the next run proceeds. During a multi-iteration fake task, create a pending receipt after the first outcome and assert the next iteration is blocked.

- [x] **Step 2: Run the red Loop suite.**

Run: `uv run pytest tests/test_loop_runner.py tests/test_loop_checkpoint.py -q`

Expected: new gate tests fail because the stop reason and store checks are absent.

- [x] **Step 3: Implement the stop reason and pre-model gate.**

Keep receipt reads outside model/task construction. Treat only `resolution=open` as blocking; historical resolved receipts do not block. Do not add a prompt-level instruction as a substitute for the host gate. Ensure checkpoint save/stop audit remains valid and `LoopReport.from_checkpoint` handles the new reason.

- [x] **Step 4: Own one store per CLI/HTTP allowed root and inject it consistently.**

For `run`/REPL/HTTP loop paths with MCP, construct one `ExternalActionReceiptStore` under the resolved allowed root and pass it to every relevant Task/Generator Task and LoopRunner. Planner/Evaluator tasks remain without MCP/store. Resume binds the same root and loads the same store; do not create a new Task before pending check. Close the store exactly once with the owning service/runner and preserve existing MCP shutdown order.

- [x] **Step 5: Run entry-point compatibility tests.**

Run: `uv run pytest tests/test_loop_runner.py tests/test_loop_checkpoint.py tests/test_cli.py tests/test_http_task_service.py -q`

Expected: PASS for pending/resolved behavior, no-MCP behavior, single/Duo/Triad role assembly, HTTP service task creation, and existing audit/allowlist contracts.

### Task 5: Explicit `forgeagent receipts` commands

**Files:**
- Modify: `src/forgeagent/cli.py:2649-2760,2880-3160`
- Create or modify: `tests/test_cli_receipts.py` (prefer a separate focused file; retain existing `tests/test_cli.py` for parser/main compatibility)

**Interfaces:**
- Add parser commands:
  - `forgeagent receipts list [--loop-id ID] [--task-id ID]`
  - `forgeagent receipts resolve ACTION_ID (--confirmed | --abandon | --retry) [--evidence TEXT]`
- `--confirmed`, `--abandon`, and `--retry` are mutually exclusive; `--confirmed` requires bounded evidence. Commands operate only on the current cwd’s canonical allowed root, never start MCP, never invoke a Task/model, and never dispatch an external action.
- Successful resolve emits one `external_action.receipt` audit projection; stale revision and malformed input return a nonzero exit without changing the file.

- [x] **Step 1: Add parser and command behavior tests before implementation.**

Test help/parse shapes, missing decision, mutually exclusive flags, evidence limit/control characters, list filters, deterministic output for pending receipts, successful confirmed/abandon/retry resolution, stale revision, malformed receipt, and an assertion that a fake MCP manager is never constructed.

- [x] **Step 2: Run the red CLI tests.**

Run: `uv run pytest tests/test_cli_receipts.py tests/test_cli.py -q`

Expected: new parser and command assertions fail before the subcommand exists.

- [x] **Step 3: Implement list and resolve handlers using only the store API.**

Use `argparse` subparsers already present in `build_parser`. Keep output public and bounded: action ID, phase, resolution, certainty, public labels, loop/task IDs, revision, timestamps, and evidence code only. Do not print raw request arguments, credentials, absolute paths, or exception text.

- [x] **Step 4: Run CLI focused tests and strict lint.**

Run: `uv run pytest tests/test_cli_receipts.py tests/test_cli.py -q && uv run ruff check src/forgeagent/cli.py tests/test_cli_receipts.py`

Expected: PASS and no new Ruff violations.

### Task 6: Contract documentation and release boundary

**Files:**
- Modify: `docs/threat-model.md`
- Modify: `docs/m7-tools-mcp-survey.md`
- Modify: `docs/http-task-service.md`
- Create: `docs/superpowers/reports/2026-07-30-external-action-receipts-verify.md` only during the final verification task, not during implementation.

**Interfaces:**
- Document the MCP-only scope, four phases, resolution independence, certainty semantics, fail-closed transitions, pending Loop gate, explicit CLI reconciliation, and the fact that `retry_approved` authorizes a separately identified new attempt but never replays automatically.
- State residual limitations: confirmed means protocol response, not business-level exactly-once/completion; unknown reconciliation requires trusted external evidence; local non-MCP side effects remain governed by the existing threat model.
- Do not document PyPI release as complete or alter release status.

- [x] **Step 1: Add documentation assertions/checklist.**

Review the existing MCP and HTTP wording for contradictions (especially auto-approve and headless allowlist behavior). Record the exact public CLI forms and the no-raw-data projection rules.

- [x] **Step 2: Update the three docs minimally.**

Add one focused subsection per document rather than restructuring historical M7/M21 material. Keep examples bounded and avoid promising remote reconciliation or exactly-once semantics.

- [x] **Step 3: Run documentation and repository consistency checks.**

Run: `rg -n "prepared|dispatched|confirmed|unknown|retry_approved|external_action_pending|forgeagent receipts|PyPI" docs src/forgeagent openspec/changes/external-action-receipts` and `git diff --check`

Expected: every public contract is represented once, no stale claim says PyPI was published, and no raw-secret example appears.

### Task 7: Full verification, two self-reviews, and handoff

**Files:**
- Modify: `docs/superpowers/reports/2026-07-30-external-action-receipts-verify.md`
- No source changes unless a verification finding is fixed in the owning task and its focused tests are rerun.

**Interfaces:**
- The verification report records commands, exact results, known skips, residual risks, and release pause status. It does not mark the Comet change archived or publish anything.

- [x] **Step 1: Run the focused security/contract matrix.**

Run: `uv run pytest tests/test_external_actions.py tests/test_mcp_manager.py tests/test_tools.py tests/test_step.py tests/test_task.py tests/test_loop_runner.py tests/test_loop_checkpoint.py tests/test_cli_receipts.py tests/test_cli.py tests/test_http_task_service.py -q`

Expected: PASS; if any test fails, classify the root cause before editing and rerun the smallest reproducer.

- [x] **Step 2: Run repository quality and build checks.**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv build`

Expected: all existing and new tests pass, Ruff is clean, formatting is clean, and the wheel/sdist build succeeds without publishing.

- [x] **Step 3: Run OpenSpec strict verification.**

Run: `openspec validate external-action-receipts --strict`

Expected: the change validates; do not mark tasks complete automatically unless the implementation actually exists and has passed the gates.

- [x] **Step 4: Perform self-review 1 (contract/state/security).**

Check every design requirement against an implementation/test path: phase transitions, resolution separation, no silent replay, no-dispatch proof, unknown after dispatch uncertainty, root binding, locking/CAS, masking, audit degraded behavior, operation-ID compatibility, and no-MCP compatibility. Search for accidental raw arguments, credentials, exception text, absolute paths, broad exception leaks, or `unknown` converted to success.

- [x] **Step 5: Perform self-review 2 (integration/scope/release).**

Check CLI, HTTP, Loop, Single/Duo/Triad Generator-only MCP ownership, Task lifecycle, store close ordering, resume-before-model behavior, stale revision handling, docs consistency, and whether any implementation broadened into FileWrite/Exec/WebFetch, new dependencies, HTTP reconciliation, remote exactly-once, or PyPI publication. Fix findings immediately in the smallest owning task and rerun its focused test plus the full verification command.

- [x] **Step 6: Write the verification report and hand off without release actions.**

Record exact command outputs, residual risks, and the unchanged release pause. The change may proceed to the project’s Comet verification/archival gates only after the parent agent separately reviews the report; this plan itself does not commit, tag, push, upload, or archive.

## Planned Execution Order

Execute Tasks 1–3 first because the model/store and certainty contract are prerequisites for all callers. Execute Task 4 next so Loop/HTTP/CLI receive one consistent store. Execute Task 5 and Task 6 in parallel only after Task 4’s public interfaces stabilize; otherwise keep changes serial to avoid shared-state drift. Task 7 is mandatory before declaring the milestone complete.

## Key Risks

- **Action-ID mismatch:** Existing model-generated ToolCall IDs are not guaranteed 32-hex; tightening them would be a compatibility regression. The plan deliberately tests and preserves them while giving receipts independent stable IDs.
- **False confirmation:** A returned MCP protocol response proves only transport/protocol certainty, not business success or exactly-once semantics. Do not infer more from `ok`.
- **Unknown replay:** `retry_approved` is a resolution record, not an execution trigger. Every new attempt gets a new receipt ID and optional parent link.
- **Storage trust boundary:** Audit is not the receipt authority. Any receipt transition failure blocks protected dispatch; malformed or replaced directories fail closed.
- **Loop ordering:** The pending gate must run before Task/model construction and before a subsequent iteration; a prompt instruction is insufficient.
- **Scope creep:** No local tool receipts, distributed idempotency, compensating transactions, browser/desktop platform work, or PyPI actions belong in this change.
