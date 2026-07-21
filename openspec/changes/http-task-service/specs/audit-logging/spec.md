# audit-logging Specification

## Purpose

Record security-relevant ForgeAgent activity in a machine-readable, bounded JSONL audit stream shared by CLI and HTTP execution paths.

## ADDED Requirements

### Requirement: Core-layer audit events cover the execution boundary

The core execution path MUST emit audit events for every logical tool operation, every model request attempt/outcome, and every confirmation-gate decision, regardless of whether the task was started by CLI or HTTP. Retries and streaming attempts MUST be distinguishable without producing ambiguous duplicate logical-operation records.

#### Scenario: Tool execution event
- **WHEN** a tool is allowed, denied, or fails during a task
- **THEN** exactly one tool audit event records the operation type, task correlation, risk level, outcome, and duration

#### Scenario: LLM call event
- **WHEN** a model request succeeds, returns a structured client error, or is interrupted
- **THEN** one LLM audit event records the model group/identifier, safe outcome, token metadata available from the client, and duration without prompt secrets

#### Scenario: Confirmation decision event
- **WHEN** a gated tool is pre-authorized, interactively approved, or denied by the headless confirmer
- **THEN** one confirmation event records the decision, risk level, tool kind, task correlation, and safe parameter summary

### Requirement: Audit records have a stable, masked JSONL schema

Each audit line MUST be one valid JSON object containing an event timestamp, event type, task identifier when available, risk level, masked parameter summary, result status, elapsed duration, and an operation/attempt correlation when applicable; serialization MUST be append-only and parseable line by line.

#### Scenario: Complete event fields
- **WHEN** a core event is written
- **THEN** its JSON object contains the required fields with stable scalar/object types and an UTC timestamp

#### Scenario: Secret masking before persistence
- **WHEN** event parameters, model metadata, tool arguments, or errors contain known secret names or values
- **THEN** masking occurs before JSON serialization and the raw secret is absent from the resulting line

#### Scenario: Malformed event data
- **WHEN** an event field contains an unserializable value or unsafe control characters
- **THEN** the logger writes a safe fallback representation or a bounded logging error without crashing the task worker or exposing raw data

### Requirement: Audit retention is bounded and concurrent writes are safe

The audit logger MUST support configurable size-based rotation with a finite retention count, serialize concurrent writers so lines are not interleaved, and preserve valid JSONL across rotations.

#### Scenario: Rotation at size limit
- **WHEN** appending an event would exceed the configured byte limit
- **THEN** the current file is rotated before the append, old files beyond the retention count are removed, and the new event is written as a complete JSON line

#### Scenario: Concurrent event writes
- **WHEN** multiple task workers emit events concurrently
- **THEN** every accepted event is either present once in a valid JSONL file or reported through a bounded logger error, with no partial/interleaved JSON records

#### Scenario: Disabled or unavailable audit path
- **WHEN** audit logging is explicitly disabled or its path cannot be opened
- **THEN** task execution follows the documented fail-open/fail-closed configuration, and the service reports the condition without silently claiming that events were persisted

### Requirement: Audit output is minimally disclosing and operationally attributable

Audit records MUST identify the risk level and operation outcome needed for replay/diagnosis while omitting bearer tokens, API keys, full prompts, file contents, and host-absolute paths.

#### Scenario: HTTP request correlation
- **WHEN** a task is submitted, queried, or cancelled through HTTP
- **THEN** core audit events for that task carry the same task identifier and do not log the bearer token

#### Scenario: HTTP lifecycle rejection is audited
- **WHEN** HTTP authentication fails, a task is rejected for capacity, or a headless confirmation denies an operation
- **THEN** one masked lifecycle or confirmation event records the route/operation and safe result status without the token, raw request body, or sensitive arguments

#### Scenario: Audit write failure is visible but non-disclosing
- **WHEN** a runtime audit append fails after service startup
- **THEN** the task/service is marked audit-degraded, a fixed diagnostic is emitted, and no response or event claims that the failed record was persisted

#### Scenario: Restricted file or web operation
- **WHEN** a FileRead, FileWrite, or WebFetch operation is audited
- **THEN** the record contains only the existing sanitized project-relative/path or artifact summary and never raw content or an unmasked URL/host path
