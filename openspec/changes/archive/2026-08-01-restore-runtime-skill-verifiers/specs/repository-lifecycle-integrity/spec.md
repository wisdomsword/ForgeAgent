## ADDED Requirements

### Requirement: Reconciled runtime claims retain executable verifiers

When a completed runtime capability is reconciled into the current baseline, ForgeAgent SHALL retain executable regression tests for its security, compatibility, and trust-boundary claims. Historical milestone text or an archived change alone MUST NOT be treated as current executable proof.

#### Scenario: Runtime Skill exit contract is reconciled
- **WHEN** M45 audits the completed M34 runtime Skill exit contract
- **THEN** the current test suite directly verifies valid version 2 contracts, fail-closed invalid inputs, legacy compatibility, secret masking, immutable exit metadata, and effective trust digest changes

#### Scenario: A critical verifier disappears
- **WHEN** the M34 implementation and specifications remain but its executable contract tests are removed
- **THEN** the repository lifecycle verification fails before the baseline is declared complete
