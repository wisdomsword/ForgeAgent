# repository-lifecycle-integrity Specification

## Purpose
Define traceable, current-baseline-safe recovery of the authorized M29-M38 lifecycle evidence set and descriptive canonical specifications.
## Requirements
### Requirement: Completed milestones retain a traceable lifecycle chain

ForgeAgent SHALL keep a repository-local evidence chain for the authorized M29-M38 recovery set: M29-M32 and M35-M38. Every milestone in that set MUST have a milestone record, and each referenced archived change, technical design, implementation plan, and verification report MUST exist. Historical verification counts MUST be identified as evidence for their original snapshot rather than current HEAD. M39 and later milestones remain governed by their current milestone records and are not recursively rewritten by this historical recovery.

#### Scenario: Historical milestone evidence is inspected
- **WHEN** a reviewer follows a restored M29-M38 milestone link
- **THEN** every referenced repository artifact exists and the record distinguishes historical counts from the current baseline verifier

#### Scenario: A lifecycle artifact disappears
- **WHEN** a required milestone, archive, design, plan, or report is removed or renamed without updating its references
- **THEN** the offline lifecycle contract test fails with the missing path

### Requirement: Archived changes retain verified terminal state

Every recovered Comet change MUST remain under `openspec/changes/archive/` and its `.comet.yaml` MUST record `phase: archive`, `verify_result: pass`, and `archived: true`. Recovery MUST NOT recreate an active publication change or represent a canceled PyPI goal as pending work.

#### Scenario: Recovered archive is audited
- **WHEN** M45 validates a recovered M29-M38 archive
- **THEN** the archive has verified terminal state and no corresponding active change is created

#### Scenario: Removed distribution goal is reviewed
- **WHEN** historical M38 publication records are read
- **THEN** they preserve the canceled history without restoring PyPI, a formal tag, or publication automation as a current roadmap item

### Requirement: Current baseline wins over historical recovery sources

Artifact recovery MUST NOT overwrite a newer current milestone pointer, borrowing-review baseline, HTTP action approval contract, or MCP progressive-disclosure contract with an older historical version. An explicitly authorized development-branch push MUST remain distinguishable from package publication, a formal release tag, or publication automation.

#### Scenario: Historical and current files conflict
- **WHEN** a recovery source differs from an existing M44 or later baseline file
- **THEN** the current file is retained and the rejected historical source is recorded in the reconciliation report

### Requirement: Canonical specifications have descriptive purposes

Every `openspec/specs/*/spec.md` MUST contain a non-placeholder Purpose describing the capability boundary and MUST NOT contain delta-only section headings such as `ADDED Requirements`, `MODIFIED Requirements`, or `REMOVED Requirements`.

#### Scenario: Archive template leaves a placeholder
- **WHEN** a canonical spec contains `TBD - created by archiving` or a delta-only heading
- **THEN** the offline lifecycle contract test fails before the change can be accepted

### Requirement: Reconciled runtime claims retain executable verifiers

When a completed runtime capability is reconciled into the current baseline, ForgeAgent SHALL retain executable regression tests for its security, compatibility, and trust-boundary claims. Historical milestone text or an archived change alone MUST NOT be treated as current executable proof. Any verifier bundle digest MUST be computed from a representation that is stable across every supported Python interpreter while still changing when a selected verifier function or assignment source changes.

#### Scenario: Runtime Skill exit contract is reconciled
- **WHEN** M45 audits the completed M34 runtime Skill exit contract
- **THEN** the current test suite directly verifies valid version 2 contracts, fail-closed invalid inputs, legacy compatibility, secret masking, immutable exit metadata, and effective trust digest changes

#### Scenario: Supported Python versions inspect the same verifier
- **WHEN** the lifecycle verifier runs under Python 3.11, 3.12, and 3.14 against unchanged source
- **THEN** the bundle digest is identical on all supported interpreters

#### Scenario: A protected verifier source changes
- **WHEN** a selected verifier function or assignment source changes
- **THEN** the digest changes and the lifecycle contract fails until the change is explicitly reconfirmed

#### Scenario: A critical verifier disappears
- **WHEN** the M34 implementation and specifications remain but its executable contract tests are removed
- **THEN** the repository lifecycle verification fails before the baseline is declared complete

### Requirement: 直接依赖具有可审计的兼容范围
ForgeAgent 的全部直接运行时依赖与开发依赖 MUST 同时声明最低版本和不兼容版本之前的上界。刷新锁文件时，若本次变更没有明确升级目标，已锁定包版本 MUST 保持不变。

#### Scenario: 当前依赖声明被重新解析
- **WHEN** 维护者对当前 `pyproject.toml` 执行锁文件一致性检查
- **THEN** 每个直接依赖均有显式上界
- **AND THEN** `uv.lock` 中除直接依赖 specifier 外不得出现无关版本漂移

#### Scenario: 准备跨越依赖上界
- **WHEN** 后续变更需要采用当前上界之外的版本
- **THEN** 该升级 MUST 先通过独立兼容性验证并显式修改依赖范围

### Requirement: 运行时内部拆分保留公共门面兼容
ForgeAgent MAY 将纯解析、数据类型、配置加载与路由决策移动到内部模块，但原有公共模块 MUST 继续提供既有导入路径和支持的猴子补丁位置。状态机、持久化、IO、工具派发和生命周期所有权 MUST 留在原有权威模块，除非后续独立 change 明确修改该契约。

#### Scenario: 调用方继续使用旧导入路径
- **WHEN** 调用方从 `forgeagent.protocol`、`forgeagent.step`、`forgeagent.mcp_manager` 或 `forgeagent.collaboration` 导入既有公开对象
- **THEN** 导入和运行时行为 MUST 与拆分前兼容

#### Scenario: 测试替换 MCP 门面默认路径
- **WHEN** 测试猴子补丁 `forgeagent.mcp_manager.DEFAULT_USER_MCP_PATH` 后无参调用 `load_mcp_config`
- **THEN** 加载器 MUST 使用被替换的门面路径

#### Scenario: 审查内部所有权
- **WHEN** 维护者检查新内部模块
- **THEN** 它们 MUST NOT 引入通用 manager、factory、framework 或新的运行时依赖
- **AND THEN** C901 结果只作为报告基线，不得在本 change 中成为阻断门禁

