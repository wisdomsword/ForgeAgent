## ADDED Requirements

### Requirement: Attention state is separate from terminal outcome
ForgeAgent SHALL represent actionable attention independently from terminal execution outcome. The attention vocabulary MUST include `running`, `needs_input`, `blocked`, and `ready`; terminal outcomes MUST remain `succeeded`, `failed`, or `cancelled` (with existing public reason values preserved). A task MAY be `needs_input` or `blocked` without being a failed terminal outcome.

#### Scenario: Waiting for user input
- **WHEN** a Survey has no asker or a model declares `need_info`
- **THEN** the task exposes `attention.state=needs_input`, a bounded reason, the responsible party, and a recovery condition without classifying the task as an internal failure

#### Scenario: Waiting for an external dependency
- **WHEN** execution cannot continue because a permission, resource, or unresolved external action requires an explicit decision
- **THEN** the task exposes `attention.state=blocked` with a bounded reason and recovery condition, and does not silently retry

#### Scenario: Work is actionable after a non-terminal event
- **WHEN** a task has a result or checkpoint that can be consumed by the caller for its next action
- **THEN** the task exposes `attention.state=ready` even if the underlying Loop is not reported as succeeded

### Requirement: Attention metadata is bounded and safe
Every `needs_input` or `blocked` state MUST include a stable reason code, responsible party, required action or input, and recovery condition. Each field MUST be length-bounded, secret-masked, and free of full prompts, raw tool arguments, file contents, absolute host paths, and credentials. Missing optional metadata MUST use safe defaults rather than null ambiguity.

#### Scenario: Oversized or sensitive detail
- **WHEN** a model, tool, or worker supplies oversized detail or a value containing a configured secret
- **THEN** the public attention projection truncates and masks it before returning or auditing it

#### Scenario: Stable machine consumption
- **WHEN** an HTTP client receives an attention projection
- **THEN** the client can branch on stable `state` and `reason` fields without parsing prose

### Requirement: Legacy needs_info remains compatible
Existing `Termination.NEEDS_INFO`, `TaskStatus.reason=needs_info`, and `ToolOutcome.needs_info` inputs MUST remain readable. They MUST map to `attention.state=needs_input` with reason `user_input_required`, and existing CLI/HTTP reason fields MUST remain present for one compatibility period.

#### Scenario: Legacy Survey result
- **WHEN** a headless Survey returns the existing `needs_info=True` outcome
- **THEN** Step and Task preserve the `needs_info` reason while adding the equivalent `needs_input` attention projection

#### Scenario: Legacy serialized result
- **WHEN** a caller loads an existing result containing only `needs_info`
- **THEN** deserialization succeeds and derives the new attention state without rewriting historical data

### Requirement: Attention transitions are audited
Changes into or out of `needs_input`, `blocked`, and `ready` MUST emit a bounded audit event correlated to the task and Loop when available. Audit failure MUST set the existing degraded indicator and MUST NOT expose sensitive metadata.

#### Scenario: State transition
- **WHEN** a task enters or leaves an attention state
- **THEN** one correlated transition event records the stable state and reason code with masked bounded metadata

#### Scenario: Audit sink failure
- **WHEN** persisting an attention transition event fails
- **THEN** the task remains safe and the public projection marks audit degradation according to existing HTTP/CLI semantics
