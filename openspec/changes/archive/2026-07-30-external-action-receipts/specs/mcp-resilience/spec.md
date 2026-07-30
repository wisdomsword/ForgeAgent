## ADDED Requirements

### Requirement: Non-read-only MCP calls use external action receipts
ForgeAgent SHALL classify MCP calls that are not covered by the configured read-only `autoApprove` allowlist as receipt-protected actions. The existing confirmation and HTTP headless allowlist gates MUST run before receipt creation, and denied calls MUST NOT create a dispatchable receipt.

#### Scenario: Read-only auto-approved MCP call
- **WHEN** a CLI or REPL MCP call matches the configured `autoApprove` entry
- **THEN** ForgeAgent preserves the existing direct call path and does not create an external action receipt

#### Scenario: Approved side-effecting MCP call
- **WHEN** a non-auto-approved MCP call passes the existing confirmer or HTTP headless allowlist
- **THEN** ForgeAgent creates and advances a receipt around the MCP dispatch

#### Scenario: Side-effecting MCP call is denied
- **WHEN** the existing confirmer or HTTP headless allowlist rejects a non-auto-approved MCP call
- **THEN** ForgeAgent returns the existing structured rejection and creates no prepared, dispatched, or unknown receipt

### Requirement: MCP call results expose dispatch certainty
The MCP manager SHALL return an internal dispatch-certainty classification that distinguishes `not_dispatched`, `confirmed`, and `unknown` without exposing raw SDK exceptions. The public ToolOutcome MUST remain bounded and MUST identify result-unknown cases so the caller can reconcile them rather than retrying automatically.

#### Scenario: MCP call has no live session
- **WHEN** the manager rejects the call before invoking the SDK session
- **THEN** the internal result is `not_dispatched` and the ToolOutcome remains a fixed unavailable failure

#### Scenario: MCP call receives a response
- **WHEN** the SDK session returns a normal MCP result object
- **THEN** the internal result is `confirmed`, regardless of the server's `isError` flag, and the receipt records protocol-response evidence

#### Scenario: MCP call loses certainty
- **WHEN** the SDK call raises, times out, or is cancelled after dispatch
- **THEN** the internal result is `unknown`, the ToolOutcome uses fixed result-unknown text, and the manager does not invalidate the receipt as a normal retryable failure
