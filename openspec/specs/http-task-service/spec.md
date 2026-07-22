# http-task-service Specification

## Purpose
TBD - created by archiving change http-task-service. Update Purpose after archive.
## Requirements
### Requirement: Authenticated task submission

The service MUST expose an asynchronous task submission endpoint that accepts a strict JSON request schema containing a goal and only explicitly approved low-risk run options, and MUST require a configured static bearer token for every task-management request. Security-sensitive execution policy, sandbox/path authority, identity, confirmer, and credentials MUST remain server-owned.

#### Scenario: Valid submission
- **WHEN** a client sends a valid bearer token and a JSON body containing a non-empty goal
- **THEN** the service creates one task, returns a unique task identifier, and does not wait for task completion

#### Scenario: Missing or invalid token
- **WHEN** a client sends a task-management request without the configured token or with a different token
- **THEN** the service returns an authentication error and does not disclose task existence, configuration values, or the expected token

#### Scenario: Invalid request body
- **WHEN** an authenticated client submits a body with a missing, empty, or invalidly typed goal
- **THEN** the service returns a structured client error and creates no task

#### Scenario: Security-sensitive request option is rejected
- **WHEN** an authenticated client submits `tier`, `backend`, `allowed_root`, `container_image`, identity/trust, confirmer, or credential fields
- **THEN** the service rejects the request without creating a task or changing the server-owned execution policy

#### Scenario: Service starts without a usable token or with a non-loopback bind
- **WHEN** the configured token is missing/blank or the configured bind address is not loopback
- **THEN** the HTTP service refuses to start and exposes no task-management listener

### Requirement: Task status and result retrieval

The service MUST expose authenticated queries for a task's lifecycle state and terminal result using the existing `TaskOutcome` semantics without exposing internal exceptions, secrets, full prompts, raw tool arguments, file contents, absolute host paths, or unbounded round history. Responses MUST use a bounded safe projection.

#### Scenario: Running task query
- **WHEN** an authenticated client queries a task that has been accepted but is still running
- **THEN** the response identifies the task as running and does not fabricate a terminal result

#### Scenario: Terminal task query
- **WHEN** an authenticated client queries a completed, failed, refused, or needs-information task
- **THEN** the response includes the stable terminal status, reason, safe detail, and available result data

#### Scenario: Unknown task query
- **WHEN** an authenticated client queries an identifier that is not retained by the service
- **THEN** the service returns a not-found error without revealing other task identifiers or stored task content

#### Scenario: Safe result projection
- **WHEN** an authenticated client queries a terminal task whose rounds contain prompts, tool arguments, file contents, or absolute paths
- **THEN** the response returns only the bounded status/reason/detail/round-count/usage projection with masking and truncation

### Requirement: Cancellation has bounded terminal semantics

The service MUST expose authenticated cancellation for accepted tasks; cancellation MUST prevent future task rounds when possible, produce a distinct `cancelled` terminal state, and MUST NOT affect other tasks. The cancellation race with completion or failure MUST have deterministic precedence.

#### Scenario: Cancel before execution
- **WHEN** a client cancels a queued task before its worker begins execution
- **THEN** the task transitions to cancelled without invoking the model or tools

#### Scenario: Cancel during execution
- **WHEN** a client cancels a running task
- **THEN** the service requests cooperative stop at the next safe round or tool boundary, returns a bounded acknowledgement, and eventually reports the deterministic terminal cancellation state

#### Scenario: Cancel an already terminal task
- **WHEN** a client cancels a task that is already terminal
- **THEN** the service leaves the terminal result unchanged and returns an idempotent acknowledgement

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
