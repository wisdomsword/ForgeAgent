## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Collaborative task results use a safe bounded projection
The service MUST identify `duo` and `triad` as public execution modes and project collaborative terminal reports without exposing full plans, rejection feedback, prompts, artifact contents or role conversations.

#### Scenario: Running collaborative task query
- **WHEN** an authenticated client queries an accepted collaboration that is still planning, generating or evaluating
- **THEN** the response reports running state, public mode and current stable phase without fabricating acceptance results

#### Scenario: Terminal collaborative task query
- **WHEN** a collaboration completes, exhausts rejection attempts, needs confirmation, fails or is cancelled
- **THEN** the response contains stable status/reason/mode, role and acceptance counters, normalized usage and bounded masked evidence summaries

