# documentation-index-integrity Specification

## Purpose
为当前读者提供一个可验证的 ForgeAgent 文档导航入口，并用离线契约测试防止当前状态、里程碑指针和分发边界发生静默漂移。
## Requirements
### Requirement: Current documentation has one classified entry point
The repository SHALL provide `docs/README.md` as a concise navigation entry point that distinguishes current authoritative contracts, development process, milestones and evidence, governance and reviews, runtime references, and historical material.

#### Scenario: Reader can locate current authorities
- **WHEN** a reader opens `docs/README.md`
- **THEN** the index links to `spec.md`, `ACTION_PLAN.md`, `MILESTONE_GUIDE.md`, `milestones/latest`, and the canonical governance entry

#### Scenario: Historical material is not presented as active work
- **WHEN** the index lists archived milestones, reviews, evaluations, or OpenSpec archives
- **THEN** it labels them as evidence or historical references and points current status back to the authoritative plan and latest milestone

### Requirement: The documentation index is locally integrity-checked
The repository SHALL provide an offline test that resolves every local Markdown link in `docs/README.md`, verifies that `milestones/latest` names an existing milestone, and verifies that the pointed milestone is complete and archived.

#### Scenario: Missing local link fails the contract
- **WHEN** a local index target is removed or misspelled
- **THEN** the documentation contract test fails with the missing target

#### Scenario: Latest pointer is valid
- **WHEN** the contract test reads `milestones/latest`
- **THEN** it finds the named milestone, confirms its status is `已完成并归档`, and rejects a missing or malformed pointer

### Requirement: Current documentation states external-boundary exclusions
The current documentation entry point SHALL state that PyPI/public distribution, formal tags, release automation, and non-loopback HTTP exposure are not enabled by this baseline, and the contract test SHALL remain offline and release-neutral.

#### Scenario: Conditional or removed goals are not claimed as delivered
- **WHEN** a reader uses the current documentation index
- **THEN** it can distinguish conditional Memory/Rewrite/HTTP follow-up triggers from delivered capabilities and sees the no-publish boundary

#### Scenario: Documentation validation has no external side effects
- **WHEN** the documentation contract test runs
- **THEN** it reads only repository files, performs no network access, reads no credentials, and invokes no publishing command
