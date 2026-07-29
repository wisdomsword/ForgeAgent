## MODIFIED Requirements

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
