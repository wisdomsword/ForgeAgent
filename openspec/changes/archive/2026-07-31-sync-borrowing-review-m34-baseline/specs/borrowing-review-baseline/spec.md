## ADDED Requirements

### Requirement: Review planning documents track the latest completed baseline
The borrowing review documents SHALL identify M34 as the current ForgeAgent baseline, SHALL state that runtime Skill exit-contract enforcement is delivered, and SHALL keep Memory migration and Rewrite/dependency work behind explicit real-demand gates.

#### Scenario: Baseline references M34
- **WHEN** the review documents are checked after M34 archival
- **THEN** both frontmatter/body references identify M34 and link to its milestone evidence

#### Scenario: Completed runtime work is not listed as pending
- **WHEN** the documents describe remaining candidates
- **THEN** runtime Skill automatic rejection is marked completed, while Memory migration and Rewrite/dependency remain conditional

### Requirement: Review baseline preserves release freeze
The review planning documents SHALL continue to state that PyPI publication, formal tags, remote pushes, and advancement or archival of `publish-v0-1-0` are not authorized.

#### Scenario: Release freeze wording remains present
- **WHEN** the offline document contract runs
- **THEN** it finds the release freeze wording and the active release change remains present
