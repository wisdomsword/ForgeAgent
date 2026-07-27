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
The repository SHALL define a required Linux Docker CI job that proves daemon availability, makes the fixed worker image available, and runs exactly the ten marked real container integration and escape tests without accepting skips as success.

#### Scenario: Docker environment is ready
- **WHEN** the pinned Docker CLI can reach its daemon and inspect the fixed worker image
- **THEN** the job runs the ten `container_integration` tests and succeeds only when all ten pass

#### Scenario: Docker daemon or image is unavailable
- **WHEN** daemon preflight or worker-image preparation fails
- **THEN** the job fails before pytest rather than producing a successful result with ten skipped tests

#### Scenario: Container test is skipped or fails
- **WHEN** any selected container integration test does not pass
- **THEN** the required Docker job fails and the platform cannot be recorded as verified

### Requirement: Evidence-driven platform matrix
The repository SHALL maintain a platform matrix that records release priority, current support state, evidence, prerequisites, limitations, and the next validation trigger for Linux Docker, Linux Podman, Windows, and local macOS Docker evidence.

#### Scenario: Platform has complete evidence
- **WHEN** the required commands pass on the named operating system, architecture, and runtime
- **THEN** the matrix may record that exact platform tuple as verified with a dated evidence reference

#### Scenario: Platform has no complete evidence
- **WHEN** a platform is only planned, partially exercised, or blocked by known runtime assumptions
- **THEN** the matrix records it as scheduled, deferred, or unsupported and does not imply release support

#### Scenario: Release target changes
- **WHEN** maintainers promote Podman or Windows to a release target
- **THEN** a separate Comet change MUST define and verify the required compatibility work before the matrix status becomes verified
