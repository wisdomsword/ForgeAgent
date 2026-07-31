## MODIFIED Requirements

### Requirement: Review baseline records the removed distribution goal
The borrowing review documents SHALL identify M34 as the current ForgeAgent baseline, SHALL state that runtime Skill exit-contract enforcement is delivered, SHALL keep Memory migration and Rewrite/dependency work behind explicit real-demand gates, SHALL record HTTP remote-action approval binding as conditional rather than delivered, and SHALL state that package-index publication, formal tags, remote pushes, and publication automation are outside the current roadmap.

#### Scenario: Baseline references M34
- **WHEN** the review documents are checked after M34 archival
- **THEN** both frontmatter/body references identify M34 and link to its milestone evidence

#### Scenario: Removed distribution goal is not listed as pending
- **WHEN** the documents describe remaining candidates
- **THEN** they do not require a future authorization or recovery step for the removed publication goal, and `publish-v0-1-0` is represented only by its canceled archive record

#### Scenario: HTTP approval binding is recorded as conditional
- **WHEN** no externally reachable HTTP action surface exists
- **THEN** the documents state that current HTTP is loopback-only and do not claim action-bound remote approval delivery
