## MODIFIED Requirements

### Requirement: Task status and result retrieval

The service MUST expose authenticated queries for a task's lifecycle state and terminal result using the existing `TaskOutcome` semantics for ordinary tasks and a bounded Loop report projection for Loop tasks. It MUST NOT expose internal exceptions, secrets, full prompts, raw tool arguments, checkpoint contents, file contents, absolute host paths, or unbounded round history. Every response MUST include an additive bounded `attention` projection with stable `state` and `reason` fields; legacy `status`, `reason`, and `detail` fields MUST remain present.

#### Scenario: Running task query
- **WHEN** an authenticated client queries an ordinary task or Loop that has been accepted but is still running
- **THEN** the response identifies it as running, identifies the public execution mode, sets `attention.state=running`, and does not fabricate a terminal result

#### Scenario: Needs-input task query
- **WHEN** an authenticated client queries a task that stopped because a user answer or explicit confirmation is required
- **THEN** the response sets `attention.state=needs_input`, exposes bounded reason and recovery metadata, and retains the legacy `needs_info` reason when that is the underlying result

#### Scenario: Blocked task query
- **WHEN** an authenticated client queries a task that cannot continue until a permission, resource, or external action is resolved
- **THEN** the response sets `attention.state=blocked`, exposes the bounded recovery condition, and does not classify the task as `internal_error`

#### Scenario: Terminal task query
- **WHEN** an authenticated client queries a completed, stopped, failed, refused, needs-information, or cancelled task
- **THEN** the response includes the stable terminal status, reason, safe detail, mode, attention projection, and available bounded result data

#### Scenario: Unknown task query
- **WHEN** an authenticated client queries an identifier that is not retained by the service
- **THEN** the service returns a not-found error without revealing other task or Loop identifiers or stored content

#### Scenario: Safe result projection
- **WHEN** an authenticated client queries a terminal task whose rounds or checkpoint contain prompts, tool arguments, file contents, absolute paths, or handoff text
- **THEN** the response returns only bounded status/reason/detail/attention/mode/round-count/usage/Loop-counter fields with masking and truncation
