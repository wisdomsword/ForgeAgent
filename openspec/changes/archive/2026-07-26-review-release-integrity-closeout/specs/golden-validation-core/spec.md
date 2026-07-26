## MODIFIED Requirements

### Requirement: Release artifacts and current evidence are machine bounded
ForgeAgent MUST build its source distribution from an explicit allowlist of package source and required root metadata. Repository development directories, OpenSpec working material and user-local files MUST NOT enter the source distribution. Automated archive validation MUST derive the single distribution root independently of member ordering and verify required root files. The README MUST contain exactly one parseable current-verification section, while its automated documentation contract MUST remain separate from historical milestone evidence and MUST NOT fix the current pytest or OpenSpec counts as permanent product values.

#### Scenario: Source distribution is built from a development working tree
- **WHEN** the repository contains agent configuration, workflow material, OpenSpec changes and user-local files during an sdist build
- **THEN** the archive contains package source and required root metadata but excludes those development and user-local paths regardless of archive member order

#### Scenario: Current verification evidence changes
- **WHEN** a verified change alters the number of tests or main specifications
- **THEN** the single README current-verification section can be updated without changing its documentation contract test or rewriting historical M22 evidence

#### Scenario: A duplicate current-verification heading is introduced
- **WHEN** README contains an additional valid or malformed `当前验证` section heading
- **THEN** the documentation contract fails even if one section still matches the expected structured format
