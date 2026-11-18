# continuous-verification Specification

## Purpose
Define mandatory offline and Linux Docker verification gates, release-artifact boundaries,
and evidence-based platform status rules for ForgeAgent changes.

## Requirements

### Requirement: Mandatory offline verification pipeline
The repository SHALL define a GitLab CI job that runs Ruff lint and format checks, the complete offline pytest suite, the twenty-case Golden runner, OpenSpec strict validation, wheel and sdist builds, and the release-content boundary contract without model credentials.

#### Scenario: All offline gates pass
- **WHEN** a branch or merge-request pipeline runs in the pinned Python and tool environment
- **THEN** every offline gate completes successfully and the job publishes the Golden and distribution artifacts

#### Scenario: Any offline gate fails
- **WHEN** lint, formatting, pytest, Golden, OpenSpec, build, or release-content validation returns a non-zero result
- **THEN** the pipeline job fails and cannot be reported as a successful verification

### Requirement: Release artifacts preserve the explicit boundary
The continuous verification pipeline SHALL build a wheel and sdist and SHALL execute the packaging contract that rejects development directories and user-local files from the release artifacts.

#### Scenario: Forbidden release content appears
- **WHEN** a built sdist includes an agent/workflow/OpenSpec development path or a forbidden user-local file
- **THEN** the release-content contract fails the offline verification job

#### Scenario: Installed wheel lacks runtime resources
- **WHEN** the isolated wheel probe cannot import ForgeAgent or render its required prompt resources
- **THEN** the release-content contract fails the offline verification job

### Requirement: Required Linux Docker container gate
The repository SHALL define a required Linux Docker CI job that proves daemon availability, makes the fixed worker image available, runs exactly the ten marked real container integration and escape tests without accepting skips as success, builds the release artifacts, installs the wheel into a clean Python 3.11 environment, and runs the complete offline RC smoke suite against that installed wheel. The job SHALL publish machine-readable JUnit and RC smoke evidence.

#### Scenario: Docker environment is ready
- **WHEN** the pinned Docker CLI can reach its daemon and inspect the fixed worker image
- **THEN** the job runs the ten `container_integration` tests and succeeds only when all ten pass

#### Scenario: Docker daemon or image is unavailable
- **WHEN** daemon preflight or worker-image preparation fails
- **THEN** the job fails before pytest rather than producing a successful result with ten skipped tests

#### Scenario: Container test is skipped or fails
- **WHEN** any selected container integration test does not pass
- **THEN** the required Docker job fails and the platform cannot be recorded as verified

#### Scenario: Installed-wheel RC smoke passes on Linux
- **WHEN** the Linux Docker job builds the candidate artifacts and runs the RC smoke harness in a newly created Python 3.11 environment
- **THEN** clean-wheel, CLI, HTTP, Single, Duo, and Triad checks all pass and the job publishes the versioned JSON report

#### Scenario: Installed-wheel RC smoke is incomplete or fails
- **WHEN** wheel installation fails, any required smoke is skipped or fails, or the JSON report is absent or incomplete
- **THEN** the Linux Docker job fails and the candidate cannot be represented as release-ready

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

### Requirement: Public verification baseline reflects the latest completed run
README and the platform support document MUST state the latest completed full pytest, OpenSpec strict, and Golden results as the current repository baseline, MUST distinguish environment-dependent skips from passes, and MUST NOT present a historical milestone count as current.

#### Scenario: M27 verification completes
- **WHEN** the final M27 full verification commands finish
- **THEN** public baseline statements are updated from those command results and agree with each other

#### Scenario: Historical evidence remains referenced
- **WHEN** a milestone-specific older count is retained for audit history
- **THEN** it is labeled as historical and is not represented as the current repository baseline

### Requirement: GitHub verification preserves release gates
The repository MUST provide GitHub Actions for offline verification and required Linux Docker verification using a documented fixed OpenSpec version shared with GitLab. Docker verification MUST reject skips and retain machine-readable evidence. Default tests MUST run from a current checkout without unavailable historical Git objects. Runtime state and local credential files MUST be ignored by Git. Public onboarding MUST identify installation, credential configuration, first use, safety boundaries and private security reporting.

#### Scenario: Fresh GitHub checkout runs verification
- **WHEN** a branch or pull request is verified from its current source
- **THEN** lint, format, pytest, Golden, strict specs, builds and clean-wheel smoke run without model credentials

#### Scenario: Linux Docker integration is skipped
- **WHEN** a selected container integration test is skipped or the Docker daemon is unavailable
- **THEN** the Docker job fails rather than recording success

#### Scenario: Local runtime and credential files exist
- **WHEN** a user creates local env files, checkpoints, memory, collaborations or receipts
- **THEN** Git ignores those files while retaining intentionally shared project instructions and Skills

### Requirement: Public model acceptance is reproducible and explicitly authorized
The repository MUST provide credential-free configuration examples and an acceptance entry point for the documented text, collaboration and image checks. Its default execution MUST validate and show the plan without network requests or credentials. Paid execution MUST require explicit opt-in, use a finite request budget and a fresh ignored evidence directory, and redact known sensitive values from saved responses. Examples MUST NOT include real keys or a fixed private gateway endpoint.

#### Scenario: Contributor validates the example without credentials
- **WHEN** a fresh checkout invokes the acceptance entry point without paid opt-in
- **THEN** it displays the selected checks without network access or creating runtime evidence

#### Scenario: Collaboration claims completion with an incorrect candidate
- **WHEN** the model reports completed but the candidate fails independent function or unittest checks
- **THEN** acceptance fails and preserves the failure result

#### Scenario: Image service ignores the requested dimensions
- **WHEN** a generated PNG has dimensions different from those requested
- **THEN** the image evidence is retained but parameter acceptance fails

#### Scenario: Request budget is exhausted
- **WHEN** execution reaches its configured request limit
- **THEN** no further provider request is sent and acceptance records a failure
