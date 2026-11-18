## ADDED Requirements

### Requirement: Dependency security gate checks locked distributions
CI SHALL run a separate dependency security gate covering all external Python versions in the project lock, pinned Python build and CI tool versions, and the locked OpenSpec npm tree. The gate SHALL fail on audit errors or unaccepted vulnerabilities. An npm advisory exception SHALL be limited to the exact advisory and affected locked package version, remain visible in the report, and expire on a fixed date.

#### Scenario: Scan includes packages for other platforms
- **WHEN** the CI runner audits the project lock
- **THEN** it checks pinned external versions from all platform branches, including Windows-only packages

#### Scenario: An exception expires or a new advisory is found
- **WHEN** an audit finds a new advisory or the current exception expires
- **THEN** dependency security verification fails and the audit result remains available
