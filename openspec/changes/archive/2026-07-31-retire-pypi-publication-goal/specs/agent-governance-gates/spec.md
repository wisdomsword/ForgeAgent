## MODIFIED Requirements

### Requirement: Governance gates are regression-tested and distribution-neutral
The project SHALL keep a local, deterministic document contract test for the governance gate. The test MUST check the five Prompt/Skill exits, the Memory questions including visibility and correction, the six rewrite metrics, and the explicit statement that package-index publication, formal tags, remote pushes, and publication automation are outside the current roadmap. No active release change may remain for that removed goal. The gate MUST NOT publish artifacts, create tags, or push remotes.

#### Scenario: Governance wording is accidentally removed
- **WHEN** a required heading, field, or distribution-boundary guard is deleted from the canonical governance document
- **THEN** the document contract test fails with the missing contract name

#### Scenario: Governance verification runs in CI
- **WHEN** the contract test runs in an offline test environment
- **THEN** it completes without network access, model credentials, package upload, tag creation, or remote push, and it confirms no active release change remains
