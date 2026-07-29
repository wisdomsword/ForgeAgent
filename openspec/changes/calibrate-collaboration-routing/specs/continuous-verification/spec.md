## MODIFIED Requirements

### Requirement: Evidence-driven platform matrix
The repository SHALL maintain a platform matrix that records release priority, current support state, evidence, prerequisites, limitations, and the next validation trigger for Linux Docker, Linux Podman, Windows, and local macOS Docker evidence. A `verified` claim MUST be limited to the operating system, architecture when recorded, runtime, and runner topology established by the cited execution, and the document MUST NOT contain a conflicting status for that same evidence.

#### Scenario: Platform has complete evidence
- **WHEN** the required commands pass on the named operating system, recorded architecture, runtime, and runner topology
- **THEN** the matrix may record only that proven platform tuple as verified with a dated evidence reference

#### Scenario: Evidence does not record every advertised architecture
- **WHEN** a successful platform run does not establish every architecture named by a broader matrix row
- **THEN** the verified row is narrowed to the recorded runner tuple rather than implying unverified architectures

#### Scenario: Platform has no complete evidence
- **WHEN** a platform is only planned, partially exercised, or blocked by known runtime assumptions
- **THEN** the matrix records it as scheduled, deferred, or unsupported and does not imply release support

#### Scenario: Release target changes
- **WHEN** maintainers promote Podman or Windows to a release target
- **THEN** a separate Comet change MUST define and verify the required compatibility work before the matrix status becomes verified

## ADDED Requirements

### Requirement: Public verification baseline reflects the latest completed run
README and the platform support document MUST state the latest completed full pytest, OpenSpec strict, and Golden results as the current repository baseline, MUST distinguish environment-dependent skips from passes, and MUST NOT present a historical milestone count as current.

#### Scenario: M27 verification completes
- **WHEN** the final M27 full verification commands finish
- **THEN** public baseline statements are updated from those command results and agree with each other

#### Scenario: Historical evidence remains referenced
- **WHEN** a milestone-specific older count is retained for audit history
- **THEN** it is labeled as historical and is not represented as the current repository baseline
