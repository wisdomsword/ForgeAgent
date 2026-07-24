# http-task-service Specification

## Purpose
TBD - created by archiving change http-task-service. Update Purpose after archive.
## Requirements
### Requirement: Authenticated task submission
The service MUST expose an asynchronous task submission endpoint that accepts a strict JSON request schema containing a goal and only explicitly approved low-risk run options, and MUST require a configured static bearer token for every task-management request. The request MAY select ordinary Task, Duo, Triad, or M21 Loop mode and MAY request resume by a strict server-owned Loop identifier. Collaboration model/tier policy, Planner confirmation policy, security-sensitive execution policy, sandbox/path authority, checkpoint paths, identity, confirmer, credentials, and frozen resume budgets MUST remain server-owned.

#### Scenario: Valid submission
- **WHEN** a client sends a valid bearer token and a JSON body containing a non-empty goal without Loop or collaboration mode
- **THEN** the service creates one ordinary task unless deterministic programming-task routing requires Triad, returns a unique task identifier, and does not wait for completion

#### Scenario: Valid collaborative submission
- **WHEN** a client sends a valid bearer token, non-empty goal and allowed `duo` or `triad` mode
- **THEN** the service creates one collaborative task using server-owned role models, tiers, rejection limits and confirmation policy, returns a unique task identifier, and does not wait for completion

#### Scenario: Headless Triad confirmation is unavailable
- **WHEN** a Triad request requires Planner confirmation and the server has not configured preauthorization for the submitted plan
- **THEN** the service rejects or terminates the task with a stable needs-confirmation result without starting Generator

#### Scenario: Valid Loop submission
- **WHEN** a client sends a valid bearer token, a non-empty goal, Loop mode, frozen collaboration mode if any, and valid low-risk Loop budgets
- **THEN** the service creates one Loop task, assigns a server-owned Loop identifier and checkpoint location, returns a unique task identifier, and does not wait for Loop completion

#### Scenario: Valid Loop resume submission
- **WHEN** a client submits Loop resume with a syntactically valid server-owned Loop identifier and no conflicting goal, collaboration mode or budgets
- **THEN** the service resolves only the matching checkpoint under its configured Loop directory and asynchronously resumes that Loop with its frozen mode and plan

#### Scenario: Missing or invalid token
- **WHEN** a client sends a task-management request without the configured token or with a different token
- **THEN** the service returns an authentication error and does not disclose task, Loop, plan or configuration existence, values, or the expected token

#### Scenario: Invalid request body
- **WHEN** an authenticated client submits a body with a missing, empty, or invalidly typed goal for a new task, an unknown mode, or combines resume with a new goal, mode or budgets
- **THEN** the service returns a structured client error and creates no task

#### Scenario: Security-sensitive request option is rejected
- **WHEN** an authenticated client submits role model/tier, rejection limit, Planner approval, backend, allowed_root, checkpoint_path, container_image, identity/trust, confirmer, credential fields, or attempts to override frozen resume configuration
- **THEN** the service rejects the request without creating a task or changing server-owned policy

#### Scenario: Service starts without a usable token or with a non-loopback bind
- **WHEN** the configured token is missing/blank or the configured bind address is not loopback
- **THEN** the HTTP service refuses to start and exposes no task-management listener

### Requirement: Task status and result retrieval

The service MUST expose authenticated queries for a task's lifecycle state and terminal result using the existing `TaskOutcome` semantics for ordinary tasks and a bounded Loop report projection for Loop tasks. It MUST NOT expose internal exceptions, secrets, full prompts, raw tool arguments, checkpoint contents, file contents, absolute host paths, or unbounded round history.

#### Scenario: Running task query
- **WHEN** an authenticated client queries an ordinary task or Loop that has been accepted but is still running
- **THEN** the response identifies it as running, identifies the public execution mode, and does not fabricate a terminal result

#### Scenario: Terminal task query
- **WHEN** an authenticated client queries a completed, stopped, failed, refused, needs-information, or cancelled task
- **THEN** the response includes the stable terminal status, reason, safe detail, mode, and available bounded result data

#### Scenario: Unknown task query
- **WHEN** an authenticated client queries an identifier that is not retained by the service
- **THEN** the service returns a not-found error without revealing other task or Loop identifiers or stored content

#### Scenario: Safe result projection
- **WHEN** an authenticated client queries a terminal task whose rounds or checkpoint contain prompts, tool arguments, file contents, absolute paths, or handoff text
- **THEN** the response returns only bounded status/reason/detail/mode/round-count/usage/Loop-counter fields with masking and truncation

### Requirement: Cancellation has bounded terminal semantics

The service MUST expose authenticated cancellation for accepted ordinary tasks and Loops; cancellation MUST prevent future task rounds or Loop iterations when possible, produce a distinct `cancelled` terminal state, persist a Loop cancellation checkpoint when applicable, and MUST NOT affect other tasks. The cancellation race with completion or failure MUST have deterministic precedence.

#### Scenario: Cancel before execution
- **WHEN** a client cancels a queued ordinary task or Loop before its worker begins execution
- **THEN** the task transitions to cancelled without invoking the model or tools and a Loop records cancellation before returning if its checkpoint was created

#### Scenario: Cancel during execution
- **WHEN** a client cancels a running ordinary task or Loop
- **THEN** the service requests cooperative stop at the next safe round, tool, or iteration boundary, returns a bounded acknowledgement, and eventually reports deterministic terminal cancellation

#### Scenario: Cancel an already terminal task
- **WHEN** a client cancels a task or Loop that is already terminal
- **THEN** the service leaves the terminal result and checkpoint unchanged and returns an idempotent acknowledgement

### Requirement: Concurrent task isolation

The service MUST execute multiple submitted tasks concurrently within configured limits while isolating task state, results, cancellation, runtime state, and audit correlation.

#### Scenario: Independent concurrent submissions
- **WHEN** multiple authenticated clients submit tasks at the same time
- **THEN** each task receives a distinct identifier and its status, result, cancellation, and audit records remain associated only with that task

#### Scenario: Worker failure isolation
- **WHEN** one task worker raises an unexpected internal error
- **THEN** that task reaches a safe failed state while other accepted tasks continue according to their own lifecycle

#### Scenario: Queue or registry capacity is exhausted
- **WHEN** a client submits a task after the configured queue or retained-record capacity is exhausted
- **THEN** the service returns a documented capacity error without creating a partial task record or evicting a running task

#### Scenario: Expired terminal result
- **WHEN** a client queries a terminal task after its configured retention period or eviction boundary
- **THEN** the service returns the documented not-found/expired result without disclosing the former result contents

### Requirement: HTTP error responses are structured and minimally disclosing

The service MUST return deterministic JSON error envelopes with an error kind and safe detail, and MUST NOT return raw tracebacks, bearer tokens, API keys, absolute host paths, or unmasked tool arguments.

#### Scenario: Internal failure response
- **WHEN** a request or task encounters an internal exception
- **THEN** the client receives the documented error kind and redacted detail while the server retains diagnostic context only through masked audit logging

#### Scenario: Startup and owner-controlled shutdown boundaries
- **WHEN** the service starts without a bearer token, binds to an invalid address, or its owning process requests shutdown
- **THEN** startup fails closed or owner-controlled shutdown completes with bounded cleanup and no unauthenticated task-management path is exposed

### Requirement: Collaborative task results use a safe bounded projection
The service MUST identify `duo` and `triad` as public execution modes and project collaborative terminal reports without exposing full plans, rejection feedback, prompts, artifact contents or role conversations.

#### Scenario: Running collaborative task query
- **WHEN** an authenticated client queries an accepted collaboration that is still planning, generating or evaluating
- **THEN** the response reports running state, public mode and current stable phase without fabricating acceptance results

#### Scenario: Terminal collaborative task query
- **WHEN** a collaboration completes, exhausts rejection attempts, needs confirmation, fails or is cancelled
- **THEN** the response contains stable status/reason/mode, role and acceptance counters, normalized usage and bounded masked evidence summaries

