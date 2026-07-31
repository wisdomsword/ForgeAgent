# borrowing-review-baseline Specification

## Purpose
记录 Agent 开发指南借鉴清单与 ForgeAgent 已完成基线、条件触发候选及已移除分发目标之间的可验证对应关系。

## Requirements
### Requirement: Review planning documents track the latest completed baseline
The borrowing review documents SHALL identify M44 as the current ForgeAgent baseline, SHALL state that runtime Skill exit-contract enforcement, Memory metadata governance, Rewrite/dependency measurement, and loopback HTTP action approval binding are delivered, and SHALL keep future Rewrite experiments and externally reachable HTTP control planes behind explicit real-demand gates.

#### Scenario: Baseline references M44
- **WHEN** the review documents are checked after M44 archival
- **THEN** both frontmatter/body references identify M44 and link to its milestone evidence

#### Scenario: Completed runtime work is not listed as pending
- **WHEN** the documents describe remaining candidates
- **THEN** completed runtime and governance work is marked delivered, while only a new Rewrite experiment or externally reachable HTTP control plane remains conditional

#### Scenario: HTTP approval binding and listener exposure are distinguished
- **WHEN** M44 is archived while the listener remains loopback-only
- **THEN** the documents mark action-bound approval as delivered and do not claim a public listener or Gateway

### Requirement: Review baseline records the removed distribution goal
The borrowing review documents SHALL identify M44 as the current ForgeAgent baseline and SHALL state that package-index publication, formal tags, distribution-oriented remote pushes, and publication automation are outside the current roadmap.

#### Scenario: Baseline references M44
- **WHEN** the review documents are checked after M44 archival
- **THEN** both frontmatter/body references identify M44 and link to its milestone evidence

#### Scenario: Removed distribution goal is not listed as pending
- **WHEN** the documents describe remaining candidates
- **THEN** they do not require a future authorization or recovery step for the removed publication goal, and `publish-v0-1-0` is represented only by its canceled archive record

#### Scenario: Development branch push remains distinct from distribution
- **WHEN** an explicitly authorized development branch is pushed for version-control handoff
- **THEN** the documents do not treat that operation as package publication, a formal tag, or restored release automation
