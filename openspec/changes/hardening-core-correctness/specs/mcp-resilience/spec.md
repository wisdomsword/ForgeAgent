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
ForgeAgent SHALL continue startup when an optional MCP server fails to connect, SHALL exclude that server's unavailable tools, and SHALL emit diagnostic information naming the failed server and a fixed failure category or exception type without exposing raw exception, command, argument, environment or server-content text.

#### Scenario: Optional server connection fails
- **WHEN** an optional MCP server cannot start or complete its connection handshake
- **THEN** the CLI remains usable with other tools and reports the degraded server

#### Scenario: Optional failure carries a known secret
- **WHEN** an optional server failure exception contains a configured secret value
- **THEN** `server_status()`, startup diagnostics and REPL status output identify the server and fixed cause without containing the secret or raw exception text

### Requirement: Required MCP failures abort startup
ForgeAgent MUST return a non-zero CLI startup result when a required MCP server fails to connect and MUST clean up MCP resources that were already started.

#### Scenario: Required server connection fails
- **WHEN** a required MCP server cannot start or complete its connection handshake
- **THEN** the CLI reports a startup error, closes already-started MCP resources and exits non-zero before running the task

#### Scenario: User changes a required server during an active REPL
- **WHEN** the REPL has already started and the user explicitly disables or enables a server configured with `required: true`
- **THEN** ForgeAgent updates and reports that server's runtime status without terminating the existing REPL session

### Requirement: MCP runtime holder ownership is loop-owned and generation-safe
ForgeAgent MUST serialize holder desired-state reconciliation on the MCP loop thread, MUST store each holder slot as a generation-bound task plus stop event and each session as a generation-bound slot, MUST bind replacement intent to an exact generation separately from teardown state, and MUST prevent an older generation from removing, cancelling or mutating a newer generation's holder, session, status or tools.

#### Scenario: Enable follows a timed-out disable
- **WHEN** disable has signalled generation N to stop but the synchronous disable wait times out, and the user immediately enables the same server
- **THEN** ForgeAgent keeps generation N visible in the holder map, removes its old tools from the available catalog, records desired enabled and a restarting status without overwriting the tearing-down slot, and starts generation N+1 only after generation N's async cleanup completes

#### Scenario: Old holder finalizer runs after replacement intent
- **WHEN** generation N finishes its holder and session finalizers after the server has been re-enabled
- **THEN** session/status/tools cleanup checks generation N, and the loop removes the holder slot only after its task is done and the slot still exactly matches generation N; generation N cannot alter generation N+1

#### Scenario: Disable occurs while a holder is initializing
- **WHEN** generation N is awaiting MCP initialization or tool discovery and loop-owned reconcile changes desired state to disabled or closing
- **THEN** generation N rechecks its exact slot, desired state, stop event and closing barrier before publishing, exits without advertising an available session/status/tools, and completes its ready signal and cleanup

#### Scenario: Old generation call fails after replacement
- **WHEN** a call using generation N fails after generation N+1 has become current
- **THEN** loop-owned failure invalidation checks the captured generation/session and cannot remove generation N+1's session or mark its status unavailable

#### Scenario: Tool call overlaps a generation change
- **WHEN** the synchronous caller requests a tool while holder generation ownership can change before the loop executes the request
- **THEN** a loop-owned wrapper invokes only a session whose generation matches both the current server state and current holder slot on the MCP loop, and the main thread does not cache or submit an obsolete ClientSession

#### Scenario: Active generation tool call fails
- **WHEN** the current generation's SDK tool call fails
- **THEN** loop-owned handling removes that generation's session and tools, marks and signals that exact generation for teardown, and leaves it unavailable without automatic replacement until an explicit enable records restart intent for that generation

#### Scenario: Enable races an unavailable holder finalizer
- **WHEN** explicit enable arrives after generation N is unavailable but before its holder task and done callback finish
- **THEN** ForgeAgent records restart intent for generation N and starts exactly one replacement after exact finalization instead of losing the enable or starting two holders

#### Scenario: Enable retries an unavailable server with no holder slot
- **WHEN** a failed generation has already been finalized, desired config remains enabled, and the user explicitly enables the unavailable server
- **THEN** ForgeAgent treats the command as retry intent and allocates one new generation instead of returning early because the desired boolean was already true

#### Scenario: Close overlaps runtime teardown
- **WHEN** close begins while a disable teardown is still awaiting holder cleanup
- **THEN** a loop-owned closing barrier blocks replacement, close snapshots and drains the exact `(server, generation, task, stop)` slot on the loop thread, and does not miss the in-progress holder or cancel a later generation

#### Scenario: Enable or connect is requested after close
- **WHEN** the manager is closed or loop-owned shutdown has entered closing state
- **THEN** ForgeAgent reports the known server or returns idempotently without starting a new holder, session, loop or generation

#### Scenario: Lifecycle wait times out before holder cleanup
- **WHEN** an enable, disable or initial-connect facade wait times out while its generation-owned holder work continues
- **THEN** ForgeAgent cancels only the concurrent waiter, idempotently ensures the loop-owned lifecycle operation still starts even if the loop had not entered its coroutine, shields holder teardown from waiter cancellation, and a following close snapshots and drains lifecycle operations without leaving a pending task or untracked holder

#### Scenario: Multiple initial holders do not multiply connection timeout
- **WHEN** multiple enabled MCP servers all fail to signal ready
- **THEN** ForgeAgent starts all holder slots before the first wait and applies ready timeouts concurrently from one monotonic start point, so initial waiting is bounded near one per-server connection timeout rather than their sum

#### Scenario: Ready result races its timeout boundary
- **WHEN** a generation publishes an available session at the same boundary where its ready waiter checks timeout
- **THEN** timeout handling rechecks the exact generation and ready/publication state and cannot overwrite a successful available status with unavailable

### Requirement: MCP loop startup is transactional
ForgeAgent MUST keep a new loop worker behind a publication gate until manager state is published, MUST roll back a failed startup without hiding a live thread, and MUST rethrow the original process-control exception.

#### Scenario: Publication gate release raises a process-control exception
- **WHEN** the OS thread has started and releasing the publication gate raises `KeyboardInterrupt` or `SystemExit`
- **THEN** ForgeAgent marks startup cancelled, lets a worker whose gate was not actually released observe cancellation, requests loop stop whether the worker has not yet entered or already entered `run_forever()`, performs a bounded join, and rethrows the same exception object without leaving a background loop thread in the normal injected case

#### Scenario: Startup rollback stops the worker
- **WHEN** startup rollback confirms the loop thread has stopped
- **THEN** ForgeAgent closes the loop, clears loop/thread references, restores `_started=False` and `_closed=False`, and allows a later connect attempt

#### Scenario: Startup rollback cannot stop the worker in time
- **WHEN** the loop thread remains alive after the startup rollback join bound
- **THEN** ForgeAgent does not close the active loop or clear its references, keeps the manager started but closed with startup cleanup marked complete because no holder was published, emits a sanitized incomplete-startup warning, and still rethrows the original startup exception so a later close can retry stop/join

#### Scenario: Initial holder submission fails after loop publication
- **WHEN** the loop and thread are published but submitting or waiting for initial holders raises an ordinary infrastructure Exception
- **THEN** `connect()` performs bounded cleanup of every published loop/holder resource, the CLI reports a fixed MCP startup error without raw exception/config text and exits non-zero, and no task execution begins

#### Scenario: Holder task creation fails before scheduling
- **WHEN** creating one initial or replacement holder task raises before the coroutine is scheduled
- **THEN** ForgeAgent closes the unawaited coroutine, leaves no partial slot, records an immediate fixed unavailable result for its waiter, and does not wait an additional connection timeout

#### Scenario: Initial holder submission receives a process-control exception
- **WHEN** initial holder submission or result waiting raises `KeyboardInterrupt` or `SystemExit` after publication
- **THEN** `connect()` first performs best-effort bounded cleanup, prevents any secondary cleanup exception from replacing the primary, and then rethrows the same exception object without converting it to `MCPStartupError`

### Requirement: MCP shutdown is bounded and idempotent
`MCPManager.close()` MUST finish within configured internal bounds, SHALL tolerate repeated calls, and MUST NOT replace an existing task or startup result with a shutdown failure. The main thread's concurrent shutdown future MUST be only a bounded waiting facade over one loop-owned shielded shutdown task; cancellation of the facade MUST NOT cancel or duplicate the authoritative drain task.

#### Scenario: Child process does not exit promptly
- **WHEN** an MCP child process does not respond during normal shutdown
- **THEN** ForgeAgent cancels pending holders and returns from public close within one absolute deadline; if async context finalization is still running, the shielded authoritative drain continues on the live loop and stops it only after cleanup completes

#### Scenario: Event-loop thread remains alive after join timeout
- **WHEN** the named MCP loop daemon thread is still alive after the absolute shutdown deadline
- **THEN** ForgeAgent cancels but retains the shutdown future, returns without closing the active loop, retains pending holder, session, loop and thread references, records an incomplete-shutdown warning using pending names returned by the loop coroutine or a read-only pre-submit fallback, and excludes MCP arguments, environment values and server-returned content from that warning

#### Scenario: Loop thread stops before cleanup completion is proven
- **WHEN** the OS thread is no longer alive but the loop-owned cleanup completion signal is not set
- **THEN** ForgeAgent treats shutdown as incomplete, retains holder/session/lifecycle-operation/loop/thread evidence, and does not clear resources or fabricate completion based on thread state or empty holder/session maps alone

#### Scenario: Internal shutdown operation raises unexpectedly
- **WHEN** an internal holder, event-loop or thread cleanup operation raises an Exception
- **THEN** the authoritative drain isolates the ordinary failure, continues best-effort cleanup of the other exact slots, sets completion only if final invariants are true, and otherwise remains the single task waiting for a repeated-close retry signal; `close()` records but does not propagate the shutdown exception to replace the caller's result

#### Scenario: Lifecycle cancellation raises unexpectedly
- **WHEN** cancelling one snapshotted lifecycle operation raises an ordinary Exception
- **THEN** the authoritative drain records that fixed failure category, continues signalling and cancelling every remaining lifecycle and holder slot, and remains retryable instead of terminating the sole shutdown task

#### Scenario: Cleanup completes during the bounded thread join
- **WHEN** loop-owned cleanup publishes its completion signal after the public facade wait but before the same `close()` call finishes its bounded thread join
- **THEN** that `close()` call re-reads the authoritative completion signal, closes and clears stopped resources immediately, and does not retain stale shutdown references until another call

#### Scenario: Close is called more than once
- **WHEN** `close()` is invoked after resources have already been closed or a previous close partially failed
- **THEN** the call completes without reopening resources or creating a second loop-owned shutdown task or waiting facade; it signals the existing drain, waits on the thread-safe completion event within the new absolute deadline, performs a bounded stop/join retry, and clears retained references only after cleanup completion and thread stop are both proven

#### Scenario: Shutdown fails after task result exists
- **WHEN** task execution has produced a result and an MCP shutdown step fails
- **THEN** ForgeAgent preserves the task result and reports the shutdown problem separately

### Requirement: Tests do not consume user MCP configuration
ForgeAgent's automated tests MUST isolate the configuration home used by CLI and MCP discovery from the developer's real home directory.

#### Scenario: User home contains MCP configuration
- **WHEN** the machine running tests has `~/.forgeagent/mcp.yaml`
- **THEN** tests use an isolated configuration root and their result is independent of that file
