# collaboration-mode-evaluation Specification

## Purpose
Define a fixed, reproducible, and privacy-safe protocol for comparing Single, Duo, and Triad execution
with neutral quality and cost evidence, without changing the collaboration runtime or automatically ranking
the modes.
## Requirements
### Requirement: Versioned and fixed evaluation protocol
The evaluation system SHALL load a versioned machine-readable protocol that fixes the task suite, task families, mode schedule, model identifiers, generation parameters, execution settings, repeat count, artifact checks, and evidence namespace before any model call, and SHALL keep each protocol's historical evidence immutable and isolated.

#### Scenario: M25 protocol is valid
- **WHEN** an operator starts the M25 evaluation with the checked-in protocol
- **THEN** the system validates every fixed field, records the protocol hash, and schedules every task-model-mode-repeat combination exactly once

#### Scenario: Protocol is incomplete or changed unexpectedly
- **WHEN** a required fixed field is missing, invalid, conflicts with the expected environment, or references another protocol's evidence namespace
- **THEN** the system fails before invoking a model and reports the mismatched field

#### Scenario: Historical M23 evidence exists
- **WHEN** the M25 protocol or aggregator is used in a repository containing M23 evidence
- **THEN** the system neither reads M23 raw records into M25 aggregation nor modifies any M23 protocol or evidence file

### Requirement: Repeated and order-balanced mode execution
The evaluation system SHALL run Single, Duo, and Triad on identical task fixtures and artifact checks for five repetitions per model, using a fixed deterministic schedule that balances mode position across the complete task-model matrix.

#### Scenario: Complete M25 schedule
- **WHEN** the M25 protocol contains nine tasks, two models, three modes, and five repetitions
- **THEN** the system creates 270 independently isolated runs with unique identities and equal aggregate position counts for Single, Duo, and Triad

#### Scenario: Evaluation resumes
- **WHEN** a scheduled run already has a valid terminal raw record bound to the same protocol, environment, route, and RunSpec hashes
- **THEN** the system skips that run without invoking a model and continues with the next fixed schedule entry

### Requirement: Independent task completion checks
The evaluation system SHALL define task completion as a completed runtime outcome plus successful mode-independent artifact checks, SHALL preserve both components in the raw record, and SHALL apply the same checks to every model and mode for a task.

#### Scenario: Internal completion with a bad artifact
- **WHEN** a mode reports completion but an external artifact check fails
- **THEN** the raw record marks the task as not solved and preserves the failed check result

#### Scenario: Correct artifact after completed execution
- **WHEN** a mode reports completion and every external artifact check passes
- **THEN** the raw record marks the task as solved

#### Scenario: Immutable fixture is modified
- **WHEN** a candidate changes, removes, or replaces a protocol-declared immutable fixture
- **THEN** an independent fixture-integrity check fails and the raw record marks the task as not solved

#### Scenario: Real programming task is scheduled
- **WHEN** the task belongs to the bugfix, feature, or refactor family
- **THEN** the isolated workspace contains the fixed multi-file fixture and its protocol-declared checks without access to another run's workspace

### Requirement: Applicable acceptance-loop metrics
The evaluation system SHALL record first acceptance, rejection count, and correction count for Duo and Triad for every model and task family, and SHALL encode those fields as not applicable for Single.

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
The evaluation system SHALL record input, output, cached, and reasoning tokens; logical model call count; provider attempt diagnostic count; end-to-end latency; and call-level usage missingness for each model, task family, task, and mode without converting unknown usage into known zero.

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
The evaluation system SHALL atomically save one safe machine-readable record per run and SHALL derive machine and human aggregate reports only from the complete raw record set for one protocol and environment.

#### Scenario: Run record is saved
- **WHEN** a scheduled run reaches a terminal state
- **THEN** its raw record contains protocol/environment identifiers, model and route identifiers, task family, metrics, checks, statuses, and artifact hashes but no prompt, model reply body, base URL, or credential

#### Scenario: Aggregation is repeated
- **WHEN** the aggregator reads the same complete raw record set more than once
- **THEN** it produces equivalent metric values and denominators at model, task-family, task, and mode levels

#### Scenario: Raw set is incomplete or mixed
- **WHEN** any of the 270 expected records is absent, duplicated, or bound to another protocol, environment, model route, or RunSpec
- **THEN** aggregation fails without writing a partial summary or report

#### Scenario: Evidence output escapes its fixed root
- **WHEN** run or aggregate receives an output path containing `..` or a symbolic-link ancestor that resolves outside the allowed root
- **THEN** the system rejects the path before reading or writing evidence

### Requirement: Neutral descriptive report
The evaluation system SHALL report per-model and per-mode sample sizes, denominators, rates, counts, token totals, call counts, latency distributions, usage missingness, and task-family breakdowns without automatically ranking modes or asserting that one mode is superior.

#### Scenario: Human report is generated
- **WHEN** aggregation completes
- **THEN** the report states the task, repetition, provider, model-weight, time, and local-platform limitations; renders non-applicable metrics explicitly; and contains no automatic winner, rank, best-mode, or superiority conclusion

#### Scenario: Models differ
- **WHEN** the two models produce different mode-level outcomes
- **THEN** the report preserves separate model denominators and does not hide the difference in an unlabeled cross-model score

