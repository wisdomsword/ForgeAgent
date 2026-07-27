# collaboration-mode-evaluation Specification

## Purpose
Define a fixed, reproducible, and privacy-safe protocol for comparing Single, Duo, and Triad execution
with neutral quality and cost evidence, without changing the collaboration runtime or automatically ranking
the modes.

## Requirements
### Requirement: Versioned and fixed evaluation protocol
The evaluation system SHALL load a versioned machine-readable protocol that fixes the task suite, mode schedule, model identifier, generation parameters, execution settings, repeat count, and artifact checks before any model call.

#### Scenario: Protocol is valid
- **WHEN** an operator starts the M23 evaluation with the checked-in protocol
- **THEN** the system validates all fixed fields, records the protocol hash, and schedules every task-mode-repeat combination exactly once

#### Scenario: Protocol is incomplete or changed unexpectedly
- **WHEN** a required fixed field is missing, invalid, or conflicts with the expected environment
- **THEN** the system fails before invoking a model and reports the mismatched field

### Requirement: Repeated and order-balanced mode execution
The evaluation system SHALL run Single, Duo, and Triad on identical task fixtures and artifact checks for at least three repetitions per mode, using a fixed rotating mode order.

#### Scenario: Complete schedule
- **WHEN** the M23 protocol contains three tasks and three repetitions
- **THEN** the system creates twenty-seven independently isolated runs and follows the protocol's rotating mode order

### Requirement: Independent task completion checks
The evaluation system SHALL define task completion as a completed runtime outcome plus successful mode-independent artifact checks, and SHALL preserve both components in the raw record.

#### Scenario: Internal completion with a bad artifact
- **WHEN** a mode reports completion but an external artifact check fails
- **THEN** the raw record marks the task as not solved and preserves the failed check result

#### Scenario: Correct artifact after completed execution
- **WHEN** a mode reports completion and every external artifact check passes
- **THEN** the raw record marks the task as solved

#### Scenario: Immutable fixture is modified
- **WHEN** a candidate changes, removes, or replaces a protocol-declared immutable fixture
- **THEN** an independent fixture-integrity check fails and the raw record marks the task as not solved

### Requirement: Applicable acceptance-loop metrics
The evaluation system SHALL record first acceptance, rejection count, and correction count for Duo and Triad, and SHALL encode those fields as not applicable for Single.

#### Scenario: Single run
- **WHEN** the system records a Single run
- **THEN** first acceptance, rejection count, and correction count are null rather than zero or a fabricated percentage

#### Scenario: Collaboration run accepted immediately
- **WHEN** the first Generator candidate is accepted by the Evaluator
- **THEN** first acceptance is true and both rejection and correction counts are zero

#### Scenario: Collaboration run requires correction
- **WHEN** the Evaluator rejects a candidate and the Generator tries again
- **THEN** the raw record preserves the rejection and correction counts and first acceptance is false

### Requirement: Complete quality and cost telemetry
The evaluation system SHALL record input, output, cached, and reasoning tokens; logical model call count; provider attempt diagnostic count; end-to-end latency; and call-level usage missingness without converting unknown usage into known zero.

#### Scenario: Usage is present
- **WHEN** a logical model call emits four valid non-negative token fields
- **THEN** the system adds those tokens to the run totals and counts the call as usage-present

#### Scenario: Usage is absent or invalid
- **WHEN** a logical model call lacks a valid usage payload
- **THEN** the system increments the missing-usage numerator, excludes unknown tokens from totals, and retains the logical call in the denominator

#### Scenario: No logical model call occurs
- **WHEN** a run fails before the first model call
- **THEN** the system records zero calls and a null usage missing rate

### Requirement: Safe raw records and reproducible aggregation
The evaluation system SHALL atomically save one safe machine-readable record per run and SHALL derive machine and human aggregate reports only from those records.

#### Scenario: Run record is saved
- **WHEN** a scheduled run reaches a terminal state
- **THEN** its raw record contains protocol/environment identifiers, metrics, checks, statuses, and artifact hashes but no prompt, model reply body, or credential

#### Scenario: Aggregation is repeated
- **WHEN** the aggregator reads the same complete raw record set more than once
- **THEN** it produces equivalent metric values and denominators

#### Scenario: Evidence output escapes its fixed root
- **WHEN** run or aggregate receives an output path containing `..` or a symbolic-link ancestor that resolves outside the allowed root
- **THEN** the system rejects the path before reading or writing evidence

### Requirement: Neutral descriptive report
The evaluation system SHALL report per-mode sample sizes, denominators, rates, counts, token totals, call counts, latency distributions, and usage missingness without automatically ranking modes or asserting that Triad is superior to Single.

#### Scenario: Human report is generated
- **WHEN** aggregation completes
- **THEN** the report states the small-sample limitation, renders non-applicable metrics explicitly, and contains no automatic winner or superiority conclusion
