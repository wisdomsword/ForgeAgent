## ADDED Requirements

### Requirement: Release artifacts and current evidence are machine bounded
ForgeAgent MUST build its source distribution from an explicit allowlist of package source and required root metadata. Repository development directories, OpenSpec working material and user-local files MUST NOT enter the source distribution. The README MUST contain one parseable current-verification section, while its automated documentation contract MUST NOT fix the current pytest or OpenSpec counts as permanent product values.

#### Scenario: Source distribution is built from a development working tree
- **WHEN** the repository contains agent configuration, workflow material, OpenSpec changes and user-local files during an sdist build
- **THEN** the archive contains package source and required root metadata but excludes those development and user-local paths

#### Scenario: Current verification evidence changes
- **WHEN** a verified change alters the number of tests or main specifications
- **THEN** README current-verification values can be updated without changing the documentation contract test or rewriting historical M22 evidence
