## ADDED Requirements

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
