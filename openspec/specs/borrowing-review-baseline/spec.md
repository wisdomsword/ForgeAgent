# borrowing-review-baseline Specification

## Purpose
记录 Agent 开发指南借鉴清单与 ForgeAgent 已完成基线、条件触发候选及已移除分发目标之间的可验证对应关系。
## Requirements
### Requirement: Review planning documents track the latest completed baseline
The borrowing review documents SHALL identify the completed milestone named by `milestones/latest` as the current ForgeAgent baseline, SHALL link to that milestone evidence, SHALL state that runtime Skill exit-contract enforcement, Memory metadata governance, Rewrite/dependency measurement, loopback HTTP action approval binding, and M45 lifecycle reconciliation are delivered, and SHALL keep future Rewrite experiments and externally reachable HTTP control planes behind explicit real-demand gates.

#### Scenario: Baseline follows the latest milestone pointer
- **WHEN** a completed milestone becomes the repository baseline
- **THEN** both review frontmatter/body references identify the milestone named by `milestones/latest` and link to its milestone evidence

#### Scenario: Completed runtime work is not listed as pending
- **WHEN** the documents describe remaining candidates
- **THEN** completed runtime, governance, and lifecycle reconciliation work is marked delivered, while only a new Rewrite experiment or externally reachable HTTP control plane remains conditional

#### Scenario: HTTP approval binding and listener exposure are distinguished
- **WHEN** M44 is archived while the listener remains loopback-only
- **THEN** the documents mark action-bound approval as delivered and do not claim a public listener or Gateway

### Requirement: Review baseline records the removed distribution goal
The borrowing review documents SHALL identify the completed milestone named by `milestones/latest` as the current ForgeAgent baseline and SHALL state that package-index publication, formal tags, distribution-oriented remote pushes, and publication automation are outside the current roadmap.

#### Scenario: Distribution boundary follows the latest baseline
- **WHEN** the review documents are checked after a completed milestone closes
- **THEN** both frontmatter/body references identify the milestone named by `milestones/latest` while retaining the removed distribution boundary

#### Scenario: Removed distribution goal is not listed as pending
- **WHEN** the documents describe remaining candidates
- **THEN** they do not require a future authorization or recovery step for the removed publication goal, and `publish-v0-1-0` is represented only by its canceled archive record

#### Scenario: Development branch push remains distinct from distribution
- **WHEN** an explicitly authorized development branch is pushed for version-control handoff
- **THEN** the documents do not treat that operation as package publication, a formal tag, or restored release automation
