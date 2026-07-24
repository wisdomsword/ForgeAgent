## ADDED Requirements

### Requirement: Trusted-core standards are baseline protected
ForgeAgent SHALL validate the trusted-core manifest against a checked-in canonical
baseline before executing a suite or creating a report. The baseline SHALL cover the
ordered scenario IDs, titles, and real-model eligibility for exactly the approved
twenty scenarios. A mismatch SHALL fail preflight and SHALL NOT create a successful
report.

#### Scenario: A core scenario is removed or substituted
- **WHEN** the manifest differs from the approved baseline by an ID removal,
addition, substitution, or order change
- **THEN** golden preflight rejects the run before any scenario executes

#### Scenario: A scenario standard is lowered without changing its ID
- **WHEN** a trusted-core scenario title or real-model eligibility differs from the
approved baseline while its ID remains present
- **THEN** golden preflight rejects the run before any result is reported

#### Scenario: Approved manifest matches the baseline
- **WHEN** the checked-in trusted-core manifest matches its canonical baseline
- **THEN** existing offline and opt-in real-model preflight behavior remains
available without changing the approved 20-scenario set
