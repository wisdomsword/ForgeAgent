# borrowing-review-baseline Specification

## Purpose
记录 Agent 开发指南借鉴清单与 ForgeAgent 已完成基线、条件触发候选及已移除分发目标之间的可验证对应关系。

## Requirements
### Requirement: Review planning documents track the latest completed baseline
The borrowing review documents SHALL identify M34 as the current ForgeAgent baseline, SHALL state that runtime Skill exit-contract enforcement is delivered, SHALL keep Memory migration and Rewrite/dependency work behind explicit real-demand gates, and SHALL record HTTP remote-action approval binding as conditional rather than delivered.

#### Scenario: Baseline references M34
- **WHEN** the review documents are checked after M34 archival
- **THEN** both frontmatter/body references identify M34 and link to its milestone evidence

#### Scenario: Completed runtime work is not listed as pending
- **WHEN** the documents describe remaining candidates
- **THEN** runtime Skill automatic rejection is marked completed, while Memory migration, Rewrite/dependency, and HTTP remote-action approval binding remain conditional unless their triggers are evidenced

#### Scenario: HTTP approval binding is recorded as conditional
- **WHEN** no externally reachable HTTP action surface exists
- **THEN** the documents state that current HTTP is loopback-only and do not claim action-bound remote approval delivery

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
