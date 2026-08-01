## MODIFIED Requirements

### Requirement: Reconciled runtime claims retain executable verifiers

When a completed runtime capability is reconciled into the current baseline, ForgeAgent SHALL retain executable regression tests for its security, compatibility, and trust-boundary claims. Historical milestone text or an archived change alone MUST NOT be treated as current executable proof. Any verifier bundle digest MUST be computed from a representation that is stable across every supported Python interpreter while still changing when a selected verifier function or assignment source changes.

#### Scenario: Runtime Skill exit contract is reconciled
- **WHEN** M45 audits the completed M34 runtime Skill exit contract
- **THEN** the current test suite directly verifies valid version 2 contracts, fail-closed invalid inputs, legacy compatibility, secret masking, immutable exit metadata, and effective trust digest changes

#### Scenario: Supported Python versions inspect the same verifier
- **WHEN** the lifecycle verifier runs under Python 3.11, 3.12, and 3.14 against unchanged source
- **THEN** the bundle digest is identical on all supported interpreters

#### Scenario: A protected verifier source changes
- **WHEN** a selected verifier function or assignment source changes
- **THEN** the digest changes and the lifecycle contract fails until the change is explicitly reconfirmed

#### Scenario: A critical verifier disappears
- **WHEN** the M34 implementation and specifications remain but its executable contract tests are removed
- **THEN** the repository lifecycle verification fails before the baseline is declared complete
