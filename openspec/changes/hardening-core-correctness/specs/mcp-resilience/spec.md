## ADDED Requirements

### Requirement: MCP service criticality is configured per server
ForgeAgent SHALL support a boolean `required` setting on each MCP server configuration, SHALL treat an omitted setting as `false`, and SHALL apply the startup requirement only when that server is enabled.

#### Scenario: Optional server omits required
- **WHEN** an MCP server configuration does not specify `required`
- **THEN** ForgeAgent treats the server as optional

#### Scenario: Required server is declared
- **WHEN** an MCP server configuration sets `required: true`
- **THEN** ForgeAgent treats successful connection to that server as a CLI startup requirement

#### Scenario: Required server is explicitly disabled
- **WHEN** an MCP server configuration sets `required: true` and `enabled: false`
- **THEN** ForgeAgent does not connect the server and does not fail initial CLI startup because of that server

### Requirement: Optional MCP failures degrade predictably
ForgeAgent SHALL continue startup when an optional MCP server fails to connect, SHALL exclude that server's unavailable tools, and SHALL emit diagnostic information naming the failed server and cause.

#### Scenario: Optional server connection fails
- **WHEN** an optional MCP server cannot start or complete its connection handshake
- **THEN** the CLI remains usable with other tools and reports the degraded server

### Requirement: Required MCP failures abort startup
ForgeAgent MUST return a non-zero CLI startup result when a required MCP server fails to connect and MUST clean up MCP resources that were already started.

#### Scenario: Required server connection fails
- **WHEN** a required MCP server cannot start or complete its connection handshake
- **THEN** the CLI reports a startup error, closes already-started MCP resources and exits non-zero before running the task

#### Scenario: User changes a required server during an active REPL
- **WHEN** the REPL has already started and the user explicitly disables or enables a server configured with `required: true`
- **THEN** ForgeAgent updates and reports that server's runtime status without terminating the existing REPL session

### Requirement: MCP shutdown is bounded and idempotent
`MCPManager.close()` MUST finish within configured internal bounds, SHALL tolerate repeated calls, and MUST NOT replace an existing task or startup result with a shutdown failure.

#### Scenario: Child process does not exit promptly
- **WHEN** an MCP child process does not respond during normal shutdown
- **THEN** ForgeAgent cancels pending holders, bounds event-loop and thread cleanup by an absolute deadline, and returns from close without waiting indefinitely

#### Scenario: Event-loop thread remains alive after join timeout
- **WHEN** the named MCP loop daemon thread is still alive after the absolute shutdown deadline
- **THEN** ForgeAgent cancels but retains the shutdown future, returns without closing the active loop, retains pending holder, session, loop and thread references, records an incomplete-shutdown warning using pending names returned by the loop coroutine or a read-only pre-submit fallback, and excludes MCP arguments, environment values and server-returned content from that warning

#### Scenario: Internal shutdown operation raises unexpectedly
- **WHEN** an internal holder, event-loop or thread cleanup operation raises an Exception
- **THEN** `close()` records the failure, keeps the manager closed and does not propagate the shutdown exception to replace the caller's result

#### Scenario: Close is called more than once
- **WHEN** `close()` is invoked after resources have already been closed or a previous close partially failed
- **THEN** the call completes without reopening resources or rerunning holder shutdown; if a previously lingering thread exists it performs only a bounded stop/join retry, and once that thread has stopped it closes the retained loop and clears the references

#### Scenario: Shutdown fails after task result exists
- **WHEN** task execution has produced a result and an MCP shutdown step fails
- **THEN** ForgeAgent preserves the task result and reports the shutdown problem separately

### Requirement: Tests do not consume user MCP configuration
ForgeAgent's automated tests MUST isolate the configuration home used by CLI and MCP discovery from the developer's real home directory.

#### Scenario: User home contains MCP configuration
- **WHEN** the machine running tests has `~/.forgeagent/mcp.yaml`
- **THEN** tests use an isolated configuration root and their result is independent of that file
