## ADDED Requirements

### Requirement: Execution rewrite evidence is versioned and reproducible
ForgeAgent SHALL provide an offline, standard-library-only measurement entry point that records a versioned execution-backend report. The report MUST contain exactly the six governance metrics `performance`, `reliability`, `maintenance_cost`, `compatibility`, `team_capability`, and `migration_rollback_risk`, and every metric MUST contain baseline, threshold, evidence, migration, and rollback trigger information.

#### Scenario: A baseline report is generated
- **WHEN** the M43 measurement entry point runs against the current repository
- **THEN** it emits a versioned machine-readable report with all six metrics and the commands or observations needed to reproduce the evidence

#### Scenario: Sensitive runtime context exists
- **WHEN** environment values, repository paths, executed code, or subprocess failures are observed during measurement
- **THEN** the public report contains no environment value, absolute path, code body, raw exception, or raw subprocess output

### Requirement: Backend evidence distinguishes measurement from absence
The measurement SHALL exercise trusted and restricted Python execution paths with the same trivial workload shape. Restricted evidence MUST include recovery after a worker crash and timeout. Container evidence MUST run only when the local daemon and fixed image are already available; unavailable container evidence MUST be recorded as `not_available` and MUST NOT count as passed or measured.

#### Scenario: Restricted worker terminates unexpectedly
- **WHEN** a restricted execution worker exits or is killed by its timeout
- **THEN** the report records a structured failure and verifies that a subsequent block can execute successfully without replaying the failed block

#### Scenario: Container runtime is unavailable
- **WHEN** the configured local container runtime or fixed image cannot be verified without network access
- **THEN** the report records fixed `not_available` evidence and excludes container timing from rewrite eligibility

### Requirement: Rewrite eligibility requires evidence and a real bottleneck
The readiness evaluator MUST return only `keep_python`, `eligible_for_single_module_experiment`, or `insufficient_evidence`. It MUST return `eligible_for_single_module_experiment` only when all six metric records are complete, at least one measured real-use bottleneck crosses its declared threshold after required clean remeasurement, compatibility and team-capability constraints are satisfied, rollback remains deterministic, and the relevant real boundary has a verifier.

#### Scenario: Metrics remain within thresholds
- **WHEN** all required evidence is complete and no real-use bottleneck crosses its threshold
- **THEN** the verdict is `keep_python` and no rewrite or new dependency is authorized

#### Scenario: A timing sample alone crosses a threshold
- **WHEN** one noisy or unconfirmed microbenchmark sample crosses a performance threshold without clean remeasurement and a real-use requirement
- **THEN** the verdict is not `eligible_for_single_module_experiment`

#### Scenario: Critical evidence is incomplete
- **WHEN** a required metric fails measurement or a proposed target boundary lacks its real verifier
- **THEN** the verdict is `insufficient_evidence` rather than success

### Requirement: Any later experiment is isolated and reversible
M43 MUST NOT implement a Rust backend, add a dependency, alter an execution protocol, or switch a runtime path. A later experiment SHALL require a separate full Comet change, SHALL target one module, SHALL preserve the current Python path, and SHALL define migration and rollback triggers before implementation.

#### Scenario: M43 completes measurement
- **WHEN** the baseline and verdict are finalized
- **THEN** runtime source, dependencies, configuration, persisted data, sandbox behavior, and public interfaces remain unchanged

#### Scenario: A later experiment cannot retain the Python path
- **WHEN** a candidate requires irreversible state conversion, unconditional replay, or removal of the current Python path before verification
- **THEN** the candidate is rejected or rolled back without entering migration

