## MODIFIED Requirements

### Requirement: Optional MCP failures degrade predictably

ForgeAgent SHALL continue startup when an optional MCP server fails to connect, SHALL exclude that server's unavailable tools, and SHALL emit only a masked fixed failure category and bounded user-facing diagnostic. Each server/generation's child stderr SHALL be isolated in its own bounded in-memory sink; raw stderr, command, arguments, environment, server content, Python exception type and `ExceptionGroup` text MUST NOT reach startup output, `/mcp`, structured feedback or lifecycle logs.

#### Scenario: Optional server connection fails
- **WHEN** an optional MCP server cannot start or complete its connection handshake
- **THEN** the CLI remains usable with other tools and reports the degraded server using its public label and fixed failure category

#### Scenario: Optional server emits startup chatter
- **WHEN** an MCP child writes normal startup chatter to stderr before becoming available
- **THEN** the chatter is consumed by that server's sink and does not appear in ForgeAgent stdout or stderr

#### Scenario: Optional server failure carries a known secret
- **WHEN** an optional server failure stderr or exception contains a configured secret value
- **THEN** server status, startup diagnostics and `/mcp` output contain neither the secret nor raw failure text

#### Scenario: Docker runtime is unavailable
- **WHEN** an enabled optional server uses Docker and its stderr matches the known Docker daemon-unavailable condition
- **THEN** `/mcp` reports a fixed user-facing reason that Docker is not running, explains that only that configured integration is disabled, and offers starting Docker or disabling that server

### Requirement: Required MCP failures abort startup

ForgeAgent MUST return a non-zero CLI startup result when a required MCP server fails to connect, MUST NOT start the task, and MUST perform bounded cleanup of MCP resources that were already started. The required-startup error MUST be written through the sanitized stderr path and MUST NOT expose raw child stderr, command, arguments, environment, server content, Python exception type or `ExceptionGroup` text. Normal cleanup MUST release those resources. When an event-loop thread is hard-stuck, the required CLI failure MAY remain incomplete at the public deadline only while retaining cleanup evidence and emitting a sanitized warning. If the authoritative drain does not yet exist, the queued shutdown facade or fallback callback on the live loop/thread MUST keep the manager state strongly reachable; if the drain exists, that sole loop-owned drain MUST keep it reachable. When the loop recovers, queued work MUST create or reuse the sole authoritative drain and continue cleanup; an existing drain MUST continue directly. Because `build_mcp_manager()` closes and raises `MCPStartupError`, the CLI MUST NOT expose or promise a later `close()` handle, and this path MUST NOT add a global registry, `atexit` hook, or new API. A direct API caller that still holds the `MCPManager`, and ordinary manager lifecycle repeated `close()` calls, MAY use a new bounded close retry.

#### Scenario: Required server connection fails
- **WHEN** a required MCP server cannot start or complete its connection handshake
- **THEN** the CLI reports a fixed sanitized startup error, makes one bounded cleanup attempt for already-started MCP resources, and exits non-zero before running the task without exposing a manager or later-close handle

#### Scenario: Required startup failure cleans up normally
- **WHEN** a required server fails after one or more MCP resources have started and their loop thread remains responsive
- **THEN** bounded cleanup releases the started holder/session/loop/thread resources before the CLI returns its non-zero startup result, and no task starts

#### Scenario: Required startup failure encounters a hard-stuck loop
- **WHEN** a required server fails and cleanup cannot complete because the MCP event-loop thread is blocked in synchronous code
- **THEN** the CLI exits non-zero before task execution at its bounded deadline, retains holder/session/lifecycle/loop/thread evidence through either queued shutdown facade/fallback work on the live loop/thread or an already-created sole authoritative drain, emits only a sanitized incomplete-cleanup warning, and lets recovered queued work create or reuse that drain and continue cleanup; the CLI exposes no later `close()` handle and does not fabricate completion

#### Scenario: User changes a required server during an active REPL
- **WHEN** the REPL has already started with an MCP manager because at least one server was enabled at startup, and the user explicitly disables or enables a server configured with `required: true`
- **THEN** ForgeAgent updates and reports that server's runtime status without terminating the existing REPL session

#### Scenario: Runtime MCP update exceeds its facade wait
- **WHEN** `/mcp enable` or `/mcp disable` times out while its loop-owned operation continues
- **THEN** the CLI reports a fixed pending status for the named server and keeps the REPL running instead of propagating `TimeoutError`

#### Scenario: Every configured server is disabled at startup
- **WHEN** all MCP server entries are disabled when the CLI is assembled
- **THEN** ForgeAgent starts without an MCP manager or loop, does not fail because a disabled server is required, and does not promise runtime enable from that manager-less session

#### Scenario: Required server emits raw stderr before failing
- **WHEN** a required MCP child writes Docker, filesystem, or arbitrary stderr before its handshake fails
- **THEN** the required startup error contains only the fixed failure category and no raw child line

## ADDED Requirements

### Requirement: MCP child stderr is isolated per server and generation

ForgeAgent SHALL pass a distinct bounded text sink to each MCP SDK `stdio_client(..., errlog=...)` invocation. The sink SHALL retain only a fixed maximum number of bytes in memory, record whether truncation occurred, and release its content after the holder generation is finalized. Masking and fixed-category classification SHALL happen before any diagnostic projection; an older generation MUST NOT overwrite a newer generation's diagnostic.

#### Scenario: One server writes more than the bound
- **WHEN** an MCP child writes stderr beyond the configured sink limit
- **THEN** the sink remains bounded, records truncation, and the public diagnostic uses a fixed truncation marker without exposing the complete text

#### Scenario: A replacement generation starts
- **WHEN** generation N is unavailable and generation N+1 is explicitly enabled
- **THEN** generation N's sink and diagnostic cannot replace or mutate generation N+1's status or diagnostic
