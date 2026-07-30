# external-action-receipts Specification

## Purpose
TBD - created by archiving change external-action-receipts. Update Purpose after archive.
## Requirements
### Requirement: External action receipts are durable and strictly bounded
ForgeAgent SHALL persist one versioned receipt for every approved, non-read-only external action before dispatch. The receipt MUST use the phases `prepared`, `dispatched`, `confirmed`, and `unknown`, MUST preserve a stable action identifier and request digest, and MUST store only bounded, secret-masked target metadata and evidence references. Receipt writes and phase transitions MUST be atomic and fail closed when the authoritative receipt cannot be persisted.

#### Scenario: Approved action is prepared before dispatch
- **WHEN** a user or server-owned policy approves a non-read-only MCP action
- **THEN** ForgeAgent durably writes a `prepared` receipt before invoking the external MCP session

#### Scenario: Receipt persistence is unavailable
- **WHEN** ForgeAgent cannot safely create or atomically update the receipt store
- **THEN** ForgeAgent does not dispatch the external action and returns a fixed receipt-unavailable failure

#### Scenario: Receipt metadata contains secrets or oversized text
- **WHEN** target labels, argument summaries, evidence references, or error text contain known secrets, control characters, or exceed configured bounds
- **THEN** the persisted receipt contains only masked, escaped, bounded values and never the raw material

### Requirement: Receipt transitions distinguish dispatch certainty
ForgeAgent SHALL transition a receipt to `dispatched` before the external call, to `confirmed` only after receiving an authoritative MCP protocol response or authoritative no-dispatch result, and to `unknown` when dispatch may have occurred but no authoritative result is available. ForgeAgent MUST NOT treat `unknown` as an ordinary retryable failure.

#### Scenario: External call returns an MCP response
- **WHEN** a dispatched MCP action receives a protocol response, including a server-declared error response
- **THEN** ForgeAgent records `confirmed` with a bounded evidence reference and returns the existing structured tool outcome semantics

#### Scenario: External call times out after dispatch
- **WHEN** the MCP session call times out, is cancelled, or raises after the receipt is `dispatched`
- **THEN** ForgeAgent records `unknown`, returns a fixed result-unknown outcome, and does not claim the external action failed before dispatch

#### Scenario: MCP server is unavailable before dispatch
- **WHEN** ForgeAgent can prove that no MCP session call was started
- **THEN** ForgeAgent records an authoritative no-dispatch result and does not expose the action as an unresolved external side effect

### Requirement: Reconciliation is explicit and never silently replays
ForgeAgent SHALL provide a bounded read-only receipt listing and an explicit reconciliation operation for unresolved receipts. Reconciliation MUST require a user or server-owned caller to choose confirmation with evidence, abandonment, or permission for a new attempt; ForgeAgent MUST never issue the original external action automatically as part of listing, resume, retry, or process startup.

#### Scenario: List unresolved receipts
- **WHEN** a user lists receipts for a project or Loop
- **THEN** ForgeAgent returns only bounded, masked metadata and identifies receipts whose phase is `prepared`, `dispatched`, or `unknown` without reading or exposing raw arguments

#### Scenario: Confirm an unknown action
- **WHEN** a user resolves an `unknown` receipt as confirmed and supplies bounded evidence
- **THEN** ForgeAgent records the evidence, marks the receipt resolved, emits an audit event, and does not dispatch any action

#### Scenario: Abandon or approve a new attempt
- **WHEN** a user resolves an unresolved receipt as abandoned or explicitly permits a new attempt
- **THEN** ForgeAgent records the decision, keeps the original receipt immutable as history, and requires any new attempt to receive a new action identifier

### Requirement: Receipt storage is scoped and recoverable
Receipt records SHALL be scoped to the canonical allowed project root and MAY carry a task and Loop correlation. Loading MUST reject unsafe paths, malformed records, unknown schema versions, extra fields, and oversized content. A partial or corrupt latest record MUST fail closed for that action rather than silently deleting history.

#### Scenario: Load receipts after process restart
- **WHEN** ForgeAgent starts or resumes after a process interruption
- **THEN** it can enumerate valid receipts from the same allowed root and preserve their phases and reconciliation decisions

#### Scenario: Receipt file is replaced or malformed
- **WHEN** a receipt path is a symlink, outside the allowed root, malformed, or contains an unknown schema
- **THEN** ForgeAgent rejects the record, reports a fixed receipt-store error, and does not dispatch related actions

