# independent-evaluator Specification

## Purpose
TBD - created by archiving change eval-evaluator. Update Purpose after archive.
## Requirements
### Requirement: Independent evaluation is explicitly opt-in
ForgeAgent SHALL invoke an Evaluator only through an explicit command with a selected
configured real model. Offline golden CI and ordinary Task execution SHALL NOT
invoke, configure, or depend on the Evaluator.

#### Scenario: Offline golden validation runs without an Evaluator
- **WHEN** the trusted-core golden command runs without a real-model option
- **THEN** it performs only deterministic script checks and no Evaluator model call
is made

#### Scenario: Explicit evaluator invocation lacks credentials
- **WHEN** a user explicitly requests an evaluation but the selected model is not
usable
- **THEN** the command fails before inspecting artifacts or writing a pass result

### Requirement: Evaluator uses an isolated observable-artifact contract
ForgeAgent SHALL construct the Evaluator in a separate task session and provide only
the declared acceptance criteria plus a bounded manifest of artifacts rooted in the
evaluation directory. The Evaluator SHALL NOT receive the Generator's conversation,
Memory, Skill registry, implementation source tree, or an expanded tool permission.

#### Scenario: Evaluator receives no Generator session context
- **WHEN** evaluation runs after a Generator task
- **THEN** the Evaluator request contains the external contract and declared
artifacts but no Generator prompt, round feedback, or memory entries

### Requirement: Evaluator reports machine-readable acceptance evidence
ForgeAgent SHALL require an Evaluator outcome to state pass or fail and to include
bounded observed evidence. A failed outcome SHALL identify the unmet expected
behavior without leaking secrets or absolute host paths.

#### Scenario: Known incorrect artifact is rejected
- **WHEN** a deliberately incorrect artifact is evaluated against its declared
acceptance criterion
- **THEN** the Evaluator reports failure with the observed behavior and unmet
criterion

#### Scenario: Known fail injections are detected
- **WHEN** the opt-in evaluator verification fixture supplies each known failing
artifact case
- **THEN** every injected case is reported as failed
