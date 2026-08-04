## MODIFIED Requirements

### Requirement: Task status and result retrieval

The service MUST expose authenticated queries for a task's lifecycle state and terminal result using the existing `TaskOutcome` semantics for ordinary tasks and bounded Loop and collaboration report projections for aggregate tasks. A terminal response MUST include bounded attempted-tool statuses and safe task-relative program artifact references when execution evidence exists. It MUST NOT expose internal exceptions, secrets, full prompts, raw tool arguments, checkpoint contents, file contents, generated code content, absolute host paths, or unbounded round or execution-evidence history.

#### Scenario: Running task query
- **WHEN** an authenticated client queries an ordinary task, Loop, or collaboration that has been accepted but is still running
- **THEN** the response identifies it as running, identifies the public execution mode, and does not fabricate a terminal result or execution evidence for unattempted work

#### Scenario: Terminal task query
- **WHEN** an authenticated client queries a completed, stopped, failed, refused, needs-information, or cancelled task
- **THEN** the response includes the stable terminal status, reason, safe detail, mode, available bounded result data, and bounded execution evidence already produced by that task

#### Scenario: Unknown task query
- **WHEN** an authenticated client queries an identifier that is not retained by the service
- **THEN** the service returns a not-found error without revealing other task, Loop, collaboration, or artifact identifiers or stored content

#### Scenario: Safe result projection
- **WHEN** an authenticated client queries a terminal task whose rounds, checkpoint, collaboration state, or execution evidence contain prompts, tool arguments, code, file contents, absolute paths, or handoff text
- **THEN** the response returns only bounded stable result fields, tool statuses, and safe task-relative artifact references with masking, truncation, and no host absolute path

#### Scenario: Artifact reference is metadata rather than a download capability
- **WHEN** a terminal task exposes an `execution-artifacts/...` program reference
- **THEN** the service can map that reference internally to the persisted regular file under the task project root, but this change adds no HTTP artifact read or download endpoint and discloses no absolute path

#### Scenario: Terminal record expiry does not delete program evidence
- **WHEN** a terminal HTTP record expires under the existing retention policy
- **THEN** the record becomes unqueryable under existing semantics while its already persisted project-local program artifact is not deleted by TaskService
