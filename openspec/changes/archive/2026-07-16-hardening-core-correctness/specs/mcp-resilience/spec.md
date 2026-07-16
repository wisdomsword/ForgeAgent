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

### Requirement: MCP discovery metadata does not expose known secrets
ForgeAgent MUST apply the existing sensitive-environment value policy before discovered MCP metadata or configured server identity reaches the model prompt, CLI, ToolOutcome feedback, structured call errors, public status, required-startup diagnostics or lifecycle logs. JSON-like input schemas MUST be recursively masked; exact built-in floats MUST be finite, and any nested NaN, positive infinity or negative infinity MUST make the public schema `{}`; a masked key collision or any other non-JSON-like value MUST have the same result. A tool or configured server routing identity that contains a known secret MUST NOT be advertised because a masked display alias cannot be routed safely back to the original SDK identity. Public configured-server labels MUST be stable and collision-free; an unknown or manually supplied raw server identity MUST map to one manager-owned fixed category label allocated without collision against configured public labels and never derived from that raw input. Internal lifecycle, approval and call routing MUST continue to use the original identity.

#### Scenario: Tool description contains a known secret
- **WHEN** MCP discovery returns a tool whose description contains a known sensitive environment value
- **THEN** the catalog, generated tools prompt and `/mcp` listing contain the redaction marker instead of the secret while preserving the safe tool name and its original call routing

#### Scenario: Input schema contains a known secret
- **WHEN** MCP discovery returns a JSON-like `inputSchema` whose keys or string values contain a known sensitive environment value
- **THEN** ForgeAgent recursively masks those keys and values before returning the catalog; if masking makes the schema structurally ambiguous or a non-JSON-like value is present, it returns an empty public schema instead of raw data

#### Scenario: Tool name contains a known secret
- **WHEN** MCP discovery returns a tool whose name would change under known-secret masking
- **THEN** ForgeAgent excludes that tool from the available catalog and prompt instead of advertising a non-routable masked alias

#### Scenario: Server identity contains a known secret
- **WHEN** a configured server identity would change under known-secret masking
- **THEN** ForgeAgent excludes that server's tools from the available catalog and prompt, uses the same public label in status, required-startup, `/mcp`, ToolOutcome, structured error and lifecycle log output, and retains the original identity only for internal lifecycle, approval and call routing

#### Scenario: Redacted server labels collide
- **WHEN** two raw server identities mask to the same text or collide with an already-safe configured identity
- **THEN** ForgeAgent preserves every safe raw label, assigns deterministic non-secret numeric suffixes to the redacted identities, reports every status/failure without overwrite, and lets enable/disable feedback select the exact raw server's public label

#### Scenario: Manual or replayed MCP call contains a known secret
- **WHEN** a ToolCall supplies a secret-bearing server or tool identity even though it was not advertised
- **THEN** approval and call routing receive the raw identity while the next-round feedback and CLI outcome contain only the manager-owned public server label and masked tool label

### Requirement: Required MCP failures abort startup
ForgeAgent MUST return a non-zero CLI startup result when a required MCP server fails to connect, MUST NOT start the task, and MUST perform bounded cleanup of MCP resources that were already started. Normal cleanup MUST release those resources. When an event-loop thread is hard-stuck, the required CLI failure MAY remain incomplete at the public deadline only while retaining cleanup evidence and emitting a sanitized warning. If the authoritative drain does not yet exist, the queued shutdown facade or fallback callback on the live loop/thread MUST keep the manager state strongly reachable; if the drain exists, that sole loop-owned drain MUST keep it reachable. When the loop recovers, queued work MUST create or reuse the sole authoritative drain and continue cleanup; an existing drain MUST continue directly. Because `build_mcp_manager()` closes and raises `MCPStartupError`, the CLI MUST NOT expose or promise a later `close()` handle, and this path MUST NOT add a global registry, `atexit` hook, or new API. A direct API caller that still holds the `MCPManager`, and ordinary manager lifecycle repeated `close()` calls, MAY use a new bounded close retry.

#### Scenario: Required server connection fails
- **WHEN** a required MCP server cannot start or complete its connection handshake
- **THEN** the CLI reports a startup error, makes one bounded cleanup attempt for already-started MCP resources, and exits non-zero before running the task without exposing a manager or later-close handle

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

### Requirement: MCP runtime holder ownership is loop-owned and generation-safe
ForgeAgent MUST serialize holder desired-state reconciliation on the MCP loop thread, MUST bind holder, session, teardown and replacement intent to monotonic generations, and MUST prevent an older generation from removing, cancelling or mutating a newer generation's resources or public state. The concrete container and task shapes belong to the technical Design Doc.

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

#### Scenario: Close races holder task allocation
- **WHEN** the caller publishes close after loop reconciliation has entered holder startup but before task creation and slot publication finish
- **THEN** one lifecycle barrier orders the operations atomically: close-first leaves generation unchanged, while start-first publishes the complete generation/task/stop slot and finalizer before close can proceed, so shutdown cannot miss an untracked task

#### Scenario: Close races lifecycle-operation registration
- **WHEN** first close overlaps loop-owned lifecycle-operation startup or completion removal
- **THEN** the same lifecycle barrier orders close against coroutine/task allocation, operation-set registration and done-callback removal: close-first creates no operation task, start-first fully registers the task before releasing the lock, and the loop-owned first-close snapshot uses that lock and completes without leaving the operation untracked

#### Scenario: Enable or connect is requested after close
- **WHEN** the manager is closed or loop-owned shutdown has entered closing state
- **THEN** ForgeAgent reports the known server or returns idempotently without starting a new holder, session, loop or generation

#### Scenario: Lifecycle wait times out before holder cleanup
- **WHEN** an enable, disable or initial-connect facade wait times out while its generation-owned holder work continues
- **THEN** ForgeAgent cancels only the concurrent waiter, idempotently ensures the loop-owned lifecycle operation still starts even if the loop had not entered its coroutine, shields holder teardown from waiter cancellation, and a following close snapshots and drains lifecycle operations without leaving a pending task or untracked holder

#### Scenario: Lifecycle facade cleanup receives process control
- **WHEN** a synchronous lifecycle facade has an ordinary primary failure or timeout and closing/cancelling its waiter or scheduling its must-deliver operation then raises `KeyboardInterrupt` or `SystemExit`
- **THEN** ForgeAgent continues bounded ownership cleanup, transports any loop-owned process-control failure as data rather than throwing it through the asyncio Task, and propagates the first process-control object only on the synchronous caller thread; if the primary was already process control, that primary object remains authoritative

#### Scenario: Background holder lifecycle receives process control
- **WHEN** holder task allocation, an MCP SDK call inside a holder or tool call, or done-finalizer replacement startup raises `KeyboardInterrupt` or `SystemExit` without the main caller thread receiving an OS process-control signal
- **THEN** ForgeAgent isolates it as a fixed unavailable or structured call failure for that generation, removes partial/stale ownership, signals exact teardown, keeps the loop available for cleanup and other holders, avoids automatic restart loops, and does not expose the exception text; `CancelledError` retains cancellation semantics

#### Scenario: Active holder task is cancelled
- **WHEN** the actual `MCPManager._holder()` task is cancelled in the ClientSession body or while ClientSession `__aenter__` is still pending after stdio has entered
- **THEN** ForgeAgent saves the original `CancelledError` and sets that generation's ready event before beginning the owning session or stdio teardown; after each context and both contexts exit, it re-raises the saved cancellation so teardown throwing any `BaseException`, throwing a second `CancelledError`, or returning `True` cannot replace or suppress the original cancellation. The task remains cancelled with the original cancellation data, async-context and done-finalizer cleanup remove only its exact session/holder and clear its teardown generation, no replacement starts without explicit restart intent, the event loop remains usable, and no unretrieved-task warning is emitted; this does not weaken `KeyboardInterrupt`/`SystemExit` isolation when no holder cancellation was saved

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

#### Scenario: Startup rollback cannot close a stopped loop
- **WHEN** startup rollback stops the worker but closing the event-loop object raises an ordinary Exception
- **THEN** ForgeAgent records only the fixed exception type, retains the stopped loop/thread and completed pre-holder cleanup evidence, remains closed rather than retryable, and lets the caller that still holds the manager use a later `close()` to retry loop closure before references are cleared

#### Scenario: Startup rollback cannot stop the worker in time
- **WHEN** the loop thread remains alive after the startup rollback join bound
- **THEN** ForgeAgent does not close the active loop or clear its references, keeps the manager started but closed with startup cleanup marked complete because no holder was published, emits a sanitized incomplete-startup warning, and still rethrows the original startup exception so the caller that still holds the manager can use a later `close()` to retry stop/join

#### Scenario: Startup rollback cleanup receives process control
- **WHEN** startup has an ordinary primary failure and a later cancellation-marker, gate, loop-stop, join, state-check or loop-close cleanup raises `KeyboardInterrupt` or `SystemExit`
- **THEN** ForgeAgent continues the remaining bounded rollback, propagates the first cleanup process-control object, and never hides it behind the ordinary primary; an already-control primary remains authoritative

#### Scenario: Initial holder submission fails after loop publication
- **WHEN** the loop and thread are published but submitting or waiting for initial holders raises an ordinary infrastructure Exception
- **THEN** `connect()` performs bounded cleanup of every published loop/holder resource, the CLI does not consume a second full shutdown/join deadline for an already-closed manager, reports a fixed MCP startup error without raw exception/config text and exits non-zero, and no task execution begins

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

#### Scenario: Shutdown facade submission is rejected
- **WHEN** submitting the public shutdown facade fails while the loop thread is alive and loop-owned containers currently appear empty
- **THEN** ForgeAgent closes the unsubmitted coroutine, schedules or retains a loop-owned drain retry, leaves authoritative completion unset on the caller thread, and preserves loop/thread/future evidence until the loop proves cleanup invariants

#### Scenario: Shutdown facade cleanup receives process control
- **WHEN** shutdown facade submission has an ordinary primary failure and closing the unsubmitted coroutine or scheduling the loop-owned fallback raises `KeyboardInterrupt` or `SystemExit`
- **THEN** ForgeAgent performs the remaining bounded finalization and propagates the first cleanup process-control object; if submission already raised process control, the original object remains authoritative

#### Scenario: Shutdown future cancellation cleanup receives process control
- **WHEN** waiting on an accepted shutdown facade has an ordinary primary failure and cancelling that future raises `KeyboardInterrupt` or `SystemExit`
- **THEN** ForgeAgent still requests the existing drain retry, performs bounded stop/join finalization, and only then propagates the first cleanup process-control object instead of hiding it behind the ordinary primary

#### Scenario: Shutdown control primary has a secondary cancellation control
- **WHEN** waiting on an accepted shutdown facade first raises `KeyboardInterrupt` or `SystemExit` and cancelling that future raises another process-control exception
- **THEN** ForgeAgent independently requests the existing drain retry, performs bounded stop/join finalization, and then propagates the original primary exception object

#### Scenario: Internal shutdown operation raises unexpectedly
- **WHEN** an internal holder, event-loop or thread cleanup operation raises an Exception
- **THEN** the authoritative drain isolates the ordinary failure, continues best-effort cleanup of the other exact slots, sets completion only if final invariants are true, and otherwise remains the single task waiting for a repeated-close retry signal; `close()` records but does not propagate the shutdown exception to replace the caller's result

#### Scenario: Lifecycle cancellation raises unexpectedly
- **WHEN** cancelling one snapshotted lifecycle operation raises an ordinary Exception
- **THEN** the authoritative drain records that fixed failure category, continues signalling and cancelling every remaining lifecycle and holder slot, and remains retryable instead of terminating the sole shutdown task

#### Scenario: Cleanup completes during the bounded thread join
- **WHEN** loop-owned cleanup publishes its completion signal after the public facade wait but before the same `close()` call finishes its bounded thread join
- **THEN** that `close()` call re-reads the authoritative completion signal, closes and clears stopped resources immediately, and does not retain stale shutdown references until another call

#### Scenario: Stopped event loop fails to close
- **WHEN** authoritative cleanup is complete and the loop thread has stopped but closing the event-loop object raises an ordinary Exception
- **THEN** public `close()` records the fixed failure category without raising, retains the stopped loop and related shutdown evidence, and a repeated `close()` retries loop closure before clearing references

#### Scenario: Close is called more than once
- **WHEN** `close()` is invoked after resources have already been closed or a previous close partially failed
- **THEN** the call completes without reopening resources or creating a second loop-owned shutdown task or waiting facade; it independently signals the existing drain, waits on the thread-safe completion event and performs bounded stop/join within the new absolute deadline, so one cleanup exception cannot skip later sites. Within a single synchronous `close()` invocation, the first captured process-control object remains authoritative over later cleanup controls and ordinary errors while cleanup still runs. A process-control object already delivered by an earlier `close()` call MUST NOT be persisted or rethrown by a later `close()` call. Retained references clear only after cleanup completion and thread stop are both proven

#### Scenario: Repeated close or stop/join cleanup receives process control
- **WHEN** drain retry, completion wait, loop stop, thread join/state read or loop close raises `KeyboardInterrupt` or `SystemExit`
- **THEN** ForgeAgent records that first control object, continues every still-valid bounded cleanup site, retains resources when liveness or loop closure is unproven, and propagates the original control only after cleanup

#### Scenario: Close preflight receives process control
- **WHEN** the initial or repeated `close()` preflight `thread.is_alive()` check raises `KeyboardInterrupt` or `SystemExit`
- **THEN** ForgeAgent conservatively treats the thread as alive, starts or reuses the shutdown drain, completes all still-valid bounded cleanup, and propagates the same control object only after cleanup

#### Scenario: Shutdown fails after task result exists
- **WHEN** task execution has produced a result and an MCP shutdown step fails
- **THEN** ForgeAgent preserves the task result and reports the shutdown problem separately

### Requirement: Tests do not consume user MCP configuration
ForgeAgent's automated tests MUST isolate the configuration home used by CLI and MCP discovery from the developer's real home directory.

#### Scenario: User home contains MCP configuration
- **WHEN** the machine running tests has `~/.forgeagent/mcp.yaml`
- **THEN** tests use an isolated configuration root and their result is independent of that file
