# tool-approval Specification Delta

## MODIFIED Requirements

### Requirement: Terminal capability controls automatic confirmation

ForgeAgent SHALL attach the generic confirmer to restricted WebFetch, FileWrite and MCP operations independently of whether MCP servers are configured. It SHALL apply the same confirmation decision semantics to CLI, REPL, and HTTP headless execution. For HTTP tasks, the configured HTTP headless allowlist is the only non-interactive pre-approval path; the existing MCP `autoApprove` configuration remains a CLI/REPL compatibility mechanism and is not inherited by HTTP tasks.

#### Scenario: Interactive terminal run
- **WHEN** a restricted tool is requested and the command has interactive TTY input and output
- **THEN** ForgeAgent asks the user to approve or reject the operation before execution

#### Scenario: REPL operation
- **WHEN** a restricted tool is requested from a REPL whose stdin and stdout are both TTYs
- **THEN** ForgeAgent asks for confirmation before execution

#### Scenario: Non-interactive REPL operation
- **WHEN** a restricted tool is requested from a REPL whose stdin or stdout is not a TTY
- **THEN** ForgeAgent rejects the operation without invoking the confirmation input reader

#### Scenario: Non-interactive input
- **WHEN** WebFetch, FileWrite or an MCP call that still requires human confirmation is requested while stdin or stdout is not a TTY
- **THEN** ForgeAgent rejects the operation deterministically without waiting for input and identifies that no interactive confirmation channel is available

#### Scenario: Non-interactive CLI or REPL auto-approved MCP call
- **WHEN** an MCP tool is listed in that server's `autoApprove` configuration, the request originates from CLI or REPL execution, and stdin or stdout is not a TTY
- **THEN** ForgeAgent treats the explicit configuration as pre-approval and executes without an interactive prompt

#### Scenario: HTTP headless operation without allowlist entry
- **WHEN** an HTTP task requests a gated WebFetch, FileWrite, or MCP operation and the operation is not in the configured headless allowlist
- **THEN** ForgeAgent rejects it deterministically with structured feedback and does not wait for input

#### Scenario: HTTP headless operation with explicit allowlist entry
- **WHEN** an HTTP task requests a gated operation that exactly matches the configured headless allowlist
- **THEN** ForgeAgent records the pre-approval decision and executes without an interactive prompt

#### Scenario: HTTP does not inherit MCP auto-approval
- **WHEN** an HTTP task requests an MCP operation that matches the server's `autoApprove` configuration but does not match the HTTP headless allowlist
- **THEN** ForgeAgent rejects the operation as headless and does not execute it
