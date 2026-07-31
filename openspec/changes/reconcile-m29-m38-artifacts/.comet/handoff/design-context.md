# Comet Design Handoff

- Change: reconcile-m29-m38-artifacts
- Phase: design
- Mode: compact
- Context hash: 6376f18c699eef51fe79ba40c3233e7a3aa7306b257327db752c4efda6e10852

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/reconcile-m29-m38-artifacts/proposal.md

- Source: openspec/changes/reconcile-m29-m38-artifacts/proposal.md
- Lines: 1-34
- SHA256: ce5b595d883f7612ede7be2d4c4df91e356a53561cfd1861738f84478b91116a

```md
## Why

当前 M44/M45 Git 基线包含 M29-M38 的运行时实现与后续里程碑，却缺少 8 份里程碑记录、10 个已归档 change、关联设计/计划/验证报告和 4 个主规格；多个既有主规格还保留归档器生成的 `Purpose: TBD`。这会让 `milestones/latest`、ACTION_PLAN、OpenSpec 与真实代码形成不可审计的断链。

## What Changes

- 建立逐项来源清单，只从主工作区恢复可由 `archived: true`、`verify_result: pass`、归档 delta 和现有实现共同证明的 M29-M38 工件。
- 恢复 `milestone_029` 至 `milestone_032`、`milestone_035` 至 `milestone_038`，以及它们缺失的归档 change 和 Superpowers design/plan/report。
- 恢复 `agent-governance-gates`、`attention-state-protocol`、`runtime-skill-exit-contract`、`structured-collaboration-handoff` 主规格，并恢复 M34 对 `skills-runtime` 的 governed exit-contract 要求。
- 保留当前 M44 借鉴清单、HTTP action approval、M45 MCP 修复规格和 `milestones/latest`，禁止旧工件覆盖新基线。
- 为所有主规格填写准确 Purpose，增加离线契约测试，禁止归档器 `TBD`、缺失里程碑链、未归档状态和已撤销 PyPI 目标重新进入当前规划。
- 为恢复的历史里程碑加 M45 对账注记：历史测试计数不是当前 HEAD 证明；开发分支 push 与已移除的包发布/tag/发布自动化目标相互独立。

## Capabilities

### New Capabilities

- `repository-lifecycle-integrity`: 定义里程碑、归档 change、设计/计划/报告、主规格和当前基线之间的可验证完整性。
- `agent-governance-gates`: 恢复 M32 已交付的 Prompt/Skill、Memory 与 Rewrite/依赖开发期治理规格。
- `attention-state-protocol`: 恢复 M29 已交付的注意力状态与终态分离规格。
- `runtime-skill-exit-contract`: 恢复 M34 已交付的版本化 Skill 退出契约规格。
- `structured-collaboration-handoff`: 恢复 M31 已交付的 host-owned 结构化协作交接规格。

### Modified Capabilities

- `skills-runtime`: 恢复 M34 已实现的 version 2 exit contract、fail-closed discovery 与按需 `exit_conditions` 读取要求。

## Impact

- 文档与证据：`milestones/`、`docs/superpowers/`、`docs/agent-governance-gates.md` 和一份 M45 对账报告。
- OpenSpec：恢复历史 archive，补齐 4 个主规格、`skills-runtime` 已实现增量和所有主规格 Purpose。
- 测试：增加只读、离线的仓库生命周期契约测试；复用现有 governance/borrowing/skills/attention/collaboration 回归。
- 运行时：不新增行为、不修改公开 API、不迁移数据、不新增依赖。
- 分发：不恢复 PyPI、正式 tag 或发布自动化；本 change 内不 push。

```

## openspec/changes/reconcile-m29-m38-artifacts/design.md

- Source: openspec/changes/reconcile-m29-m38-artifacts/design.md
- Lines: 1-65
- SHA256: 01fb0d4943c8b1a524c464109bebc681c0e622b159b395413b9b806ee49edf8b

```md
## Context

M44 分支从较早的干净 Git 基线连续开发，代码已经包含 M29-M38 的能力，但这些里程碑的大量流程工件只存在于主工作区未提交内容中。直接复制整个主工作区会把旧借鉴清单、过期测试计数、无关 agent 配置和用户文件带入 M45；完全忽略又会让 ACTION_PLAN 已完成行无法追溯到里程碑、归档 change 和主规格。

本 change 是仓库证据恢复，不是运行时功能开发。主工作区只读，M45 worktree 是唯一写入目标。

## Goals / Non-Goals

**Goals:**

- 恢复 M29-M38 缺失的里程碑和 Comet/OpenSpec/Superpowers 生命周期链。
- 恢复当前代码已经实现但主规格缺失的 M29、M31、M32、M34 契约。
- 保留 M44/M45 较新的 borrowing、HTTP、MCP 和里程碑指针事实。
- 清除全部主规格的归档器 `Purpose: TBD`，并用离线测试防止回归。
- 产出来源、SHA、采纳/拒绝理由和验证结果可追溯的 M45 对账报告。

**Non-Goals:**

- 不复制主工作区 `.agent/`、`.agents/`、`.claude/`、`.codex/`、`skills-lock.json`、`work/` 或其他无关文件。
- 不用旧 M30 主规格覆盖 M45 修复后的 `mcp-progressive-disclosure`。
- 不用旧 M34/M43 借鉴清单覆盖 M44 当前基线。
- 不修改运行时代码、依赖、持久数据、HTTP listener 或发布自动化。

## Decisions

### 1. 使用明确白名单，不做目录级全量同步

恢复范围固定为：8 个缺失 milestone、10 个缺失 archive、20 个缺失 Superpowers 工件、`docs/agent-governance-gates.md`、`tests/test_governance_docs.py`，以及经当前 change delta 合并的 4 个缺失主规格和 `skills-runtime` 增量。每个来源文件在复制前后记录 SHA256。

替代方案“复制主工作区所有未跟踪文件”被拒绝，因为无法区分用户文件、旧基线和当前 M45 事实。

### 2. 当前分支事实优先于历史来源

若目标路径已存在，不自动覆盖。已知冲突中：M45 的 borrowing spec 已到 M44，优于主工作区 M34 版本；M45 的 MCP spec 包含真实 manager 修复，优于旧 M30 版本；M44 的 HTTP action approval spec 在主工作区尚不存在。历史 archive 可以恢复用于 provenance，但不能反向更新这些主规格。

### 3. 缺失规格通过本 change 的 delta 合并

不直接把 `openspec/specs/` 当普通文件复制。4 个缺失能力作为 ADDED delta、M34 的 `skills-runtime` 作为 MODIFIED delta，由当前 Comet archive 统一合并；这样 OpenSpec 能验证要求格式和归档来源。历史 archive 原样恢复，仅作为当时的生命周期证据。

### 4. 历史里程碑附加对账注记

M29-M38 的原始范围、裁决和测试计数保留，但追加统一 M45 注记：计数只证明当时快照；当前实现由 M45 全量门禁重新证明；开发分支 push 与已移除的 PyPI/tag/发布自动化目标不同。M30 额外指向 M45 的修复归档，说明 M44 集成时 manager 契约曾缺失且已修复。

### 5. Purpose 必须描述能力，不允许模板占位

离线测试扫描 `openspec/specs/*/spec.md`，拒绝 `TBD - created by archiving` 和 delta-only 顶层标题。Purpose 只写一至两句能力边界，不改变 requirements。

## Risks / Trade-offs

- **历史工件曾来自脏工作区。** → 只接受 `.comet.yaml` 同时满足 `phase: archive`、`verify_result: pass`、`archived: true` 的 archive，并用当前 tests/specs 重新验证。
- **旧文档与新事实冲突。** → 不覆盖已存在目标；对恢复 milestone 追加 M45 注记；对账报告列出拒绝项。
- **一次恢复文件较多。** → 先用失败的清单测试锁定精确路径，再分“证据复制、规格合并、Purpose 清理”三批提交。
- **Purpose 清理跨越早期里程碑。** → 只改 Purpose，不改 requirements；OpenSpec strict 和全量 pytest 防止语义漂移。

## Migration Plan

1. 新增生命周期清单测试并确认缺失路径、TBD 和断链导致失败。
2. 从只读主工作区按白名单恢复历史工件，记录 SHA 和冲突决策。
3. 通过 delta 恢复缺失主规格与 M34 `skills-runtime` 增量。
4. 填写所有主规格 Purpose，运行 governance、borrowing、skills、attention、collaboration 和全量门禁。
5. 归档本 change。失败时回滚本 change 提交即可；无运行时数据迁移。

## Open Questions

无。所有来源和冲突裁决都必须在实现前进入白名单；发现白名单外文件时拒绝复制并记录，而不是扩大范围。

```

## openspec/changes/reconcile-m29-m38-artifacts/tasks.md

- Source: openspec/changes/reconcile-m29-m38-artifacts/tasks.md
- Lines: 1-23
- SHA256: 84884c94ac6e264aceac5df226bdc777dde7058ba036767fb9bd3b6badfb04be

```md
## 1. 失败契约与来源清单

- [ ] 1.1 增加离线生命周期契约测试，覆盖 M29-M38 里程碑、archive、Superpowers 工件、主规格和 `TBD` Purpose
- [ ] 1.2 运行专项测试并确认当前基线因缺失文件和主规格占位失败
- [ ] 1.3 记录白名单来源路径、SHA256、采纳/拒绝理由和新基线优先裁决

## 2. 历史证据恢复

- [ ] 2.1 恢复 8 个缺失里程碑并追加 M45 历史证据/分发边界对账注记
- [ ] 2.2 恢复 10 个已验证终态的历史 archive，不创建 active 发布 change
- [ ] 2.3 恢复 20 个缺失 Superpowers design/plan/report、治理文档和离线治理测试

## 3. 主规格修复

- [ ] 3.1 通过 delta 恢复 4 个缺失能力规格和 M34 `skills-runtime` 增量
- [ ] 3.2 为全部 canonical spec 填写非占位 Purpose，不修改既有 requirements
- [ ] 3.3 确认 M44 borrowing/HTTP、M45 MCP 和 `milestones/latest` 未被旧来源覆盖

## 4. 验证与归档准备

- [ ] 4.1 运行 lifecycle、governance、borrowing、skills、attention 和 collaboration 聚焦回归
- [ ] 4.2 运行全量 pytest、Ruff、format、build、diff check 和 OpenSpec strict
- [ ] 4.3 完成两轮最终自审并记录归档证据，不执行 PyPI、tag、push 或发布自动化

```

## openspec/changes/reconcile-m29-m38-artifacts/specs/agent-governance-gates/spec.md

- Source: openspec/changes/reconcile-m29-m38-artifacts/specs/agent-governance-gates/spec.md
- Lines: 1-65
- SHA256: 6f9d6742927f6a64ffe86d2f4e8a1543a3310ed176b54e33253f3e3364c60c77

```md
## ADDED Requirements
### Requirement: Long-lived Prompt and Skill instructions declare bounded exits

The project SHALL require every newly added or materially changed long-lived Prompt or Skill instruction to declare five exit classes: success, failure, blocked, needs-input, and timeout-or-budget. Each exit declaration MUST name an observable condition and the responsible verifier, and MUST NOT use an unbounded absolute claim as its only acceptance condition. A model upgrade MUST record the model version, a runnable minimum regression set, and whether stale scaffolding was retired.

#### Scenario: A new Skill is proposed
- **WHEN** a change adds or materially changes a long-lived Skill or Prompt instruction
- **THEN** its proposal or design records all five exit classes, a bounded condition for each, the verifier that observes the condition, the model version, the minimum regression set, and stale-scaffolding disposition

#### Scenario: A prompt instruction lacks a verifier
- **WHEN** a proposed instruction has prose guidance but no observable verifier or exit condition
- **THEN** the change is rejected by the governance review until the condition and verifier are added or the instruction is removed

### Requirement: Durable Memory proposals answer the four governance questions

The project SHALL require every proposal to write or change durable project Memory to answer who can write it, what source is authoritative truth, when the item expires or is revalidated, and which copy recovers after a crash. The proposal SHALL additionally record why the item is remembered, who can see it, and how a user deletes or corrects it. Session-only Memory MAY use the session boundary as its visibility and recovery answer, but SHALL still identify its writer, source, and correction behavior.

#### Scenario: A project Memory write is proposed
- **WHEN** a change adds or changes a durable project Memory path
- **THEN** the design records writer authority, purpose, authoritative source, expiry or revalidation rule, visibility, recovery copy, and deletion/correction action

#### Scenario: A Memory item becomes stale
- **WHEN** its expiry or revalidation condition is reached
- **THEN** the process stops treating it as authoritative and records the required revalidation or correction path instead of silently refreshing it

### Requirement: Rewrite and dependency changes pass a six-metric gate

The project SHALL require a large rewrite or new runtime dependency to provide a baseline, threshold, evidence source, migration plan, and rollback plan for performance, reliability, maintenance cost, compatibility, team capability, and migration/rollback risk. A rewrite MUST NOT be justified solely by model quality, novelty, or an unmeasured architectural preference.

#### Scenario: A rewrite is proposed
- **WHEN** a change replaces a module, execution backend, language layer, or introduces a runtime dependency with cross-module impact
- **THEN** the design includes six metric rows with baseline, threshold, evidence source, migration steps, and rollback trigger

#### Scenario: A rewrite gate is not met
- **WHEN** one or more metrics lacks a baseline, threshold, or evidence source
- **THEN** the change remains exploratory and cannot enter implementation as an approved rewrite

### Requirement: Governance gates are regression-tested and distribution-neutral
The project SHALL keep a local, deterministic document contract test for the governance gate. The test MUST check the five Prompt/Skill exits, the Memory questions including visibility and correction, the six rewrite metrics, and the explicit statement that package-index publication, formal tags, remote pushes, and publication automation are outside the current roadmap. No active release change may remain for that removed goal. The gate MUST NOT publish artifacts, create tags, or push remotes.

#### Scenario: Governance wording is accidentally removed
- **WHEN** a required heading, field, or distribution-boundary guard is deleted from the canonical governance document
- **THEN** the document contract test fails with the missing contract name

#### Scenario: Governance verification runs in CI
- **WHEN** the contract test runs in an offline test environment
- **THEN** it completes without network access, model credentials, package upload, tag creation, or remote push, and it confirms no active release change remains

### Requirement: Borrowing candidates are evidence-mapped before completion

The project SHALL map every borrowing candidate marked complete to an archived OpenSpec change,
milestone, or verification report that states its delivered scope and boundaries. A candidate list
MUST NOT be treated as an execution queue, and deferred or conditional candidates MUST state the
trigger or independent change required before implementation.

#### Scenario: Completed candidate has evidence

- **WHEN** a borrowing candidate is marked complete in the planning baseline
- **THEN** the baseline names an archived change or milestone and a verifier-visible scope boundary

#### Scenario: Candidate remains deferred or conditional

- **WHEN** a candidate is not authorized for implementation
- **THEN** the baseline records its deferred/conditional status and the trigger or independent change
  required before work begins

```

## openspec/changes/reconcile-m29-m38-artifacts/specs/attention-state-protocol/spec.md

- Source: openspec/changes/reconcile-m29-m38-artifacts/specs/attention-state-protocol/spec.md
- Lines: 1-48
- SHA256: a96c99845732a4df0a25b8726ffec757b38d94151bf7569d79b9b053487457cc

```md
## ADDED Requirements
### Requirement: Attention state is separate from terminal outcome
ForgeAgent SHALL represent actionable attention independently from terminal execution outcome. The attention vocabulary MUST include `running`, `needs_input`, `blocked`, and `ready`; terminal outcomes MUST remain `succeeded`, `failed`, or `cancelled` (with existing public reason values preserved). A task MAY be `needs_input` or `blocked` without being a failed terminal outcome.

#### Scenario: Waiting for user input
- **WHEN** a Survey has no asker or a model declares `need_info`
- **THEN** the task exposes `attention.state=needs_input`, a bounded reason, the responsible party, and a recovery condition without classifying the task as an internal failure

#### Scenario: Waiting for an external dependency
- **WHEN** execution cannot continue because a permission, resource, or unresolved external action requires an explicit decision
- **THEN** the task exposes `attention.state=blocked` with a bounded reason and recovery condition, and does not silently retry

#### Scenario: Work is actionable after a non-terminal event
- **WHEN** a task has a result or checkpoint that can be consumed by the caller for its next action
- **THEN** the task exposes `attention.state=ready` even if the underlying Loop is not reported as succeeded

### Requirement: Attention metadata is bounded and safe
Every `needs_input` or `blocked` state MUST include a stable reason code, responsible party, required action or input, and recovery condition. Each field MUST be length-bounded, secret-masked, and free of full prompts, raw tool arguments, file contents, absolute host paths, and credentials. Missing optional metadata MUST use safe defaults rather than null ambiguity.

#### Scenario: Oversized or sensitive detail
- **WHEN** a model, tool, or worker supplies oversized detail or a value containing a configured secret
- **THEN** the public attention projection truncates and masks it before returning or auditing it

#### Scenario: Stable machine consumption
- **WHEN** an HTTP client receives an attention projection
- **THEN** the client can branch on stable `state` and `reason` fields without parsing prose

### Requirement: Legacy needs_info remains compatible
Existing `Termination.NEEDS_INFO`, `TaskStatus.reason=needs_info`, and `ToolOutcome.needs_info` inputs MUST remain readable. They MUST map to `attention.state=needs_input` with reason `user_input_required`, and existing CLI/HTTP reason fields MUST remain present for one compatibility period.

#### Scenario: Legacy Survey result
- **WHEN** a headless Survey returns the existing `needs_info=True` outcome
- **THEN** Step and Task preserve the `needs_info` reason while adding the equivalent `needs_input` attention projection

#### Scenario: Legacy serialized result
- **WHEN** a caller loads an existing result containing only `needs_info`
- **THEN** deserialization succeeds and derives the new attention state without rewriting historical data

### Requirement: Attention transitions are audited
Changes into or out of `needs_input`, `blocked`, and `ready` MUST emit a bounded audit event correlated to the task and Loop when available. Audit failure MUST set the existing degraded indicator and MUST NOT expose sensitive metadata.

#### Scenario: State transition
- **WHEN** a task enters or leaves an attention state
- **THEN** one correlated transition event records the stable state and reason code with masked bounded metadata

#### Scenario: Audit sink failure
- **WHEN** persisting an attention transition event fails
- **THEN** the task remains safe and the public projection marks audit degradation according to existing HTTP/CLI semantics

```

## openspec/changes/reconcile-m29-m38-artifacts/specs/repository-lifecycle-integrity/spec.md

- Source: openspec/changes/reconcile-m29-m38-artifacts/specs/repository-lifecycle-integrity/spec.md
- Lines: 1-41
- SHA256: 3db96771e493bb4b85c99a1547e1039dab74ac5d082cd9d0b750c99ae2e5e7bf

```md
## ADDED Requirements

### Requirement: Completed milestones retain a traceable lifecycle chain

ForgeAgent SHALL keep a repository-local evidence chain for M29 through the latest completed milestone. Every completed milestone in that range MUST have a milestone record, and each referenced archived change, technical design, implementation plan, and verification report MUST exist. Historical verification counts MUST be identified as evidence for their original snapshot rather than current HEAD.

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

```

## openspec/changes/reconcile-m29-m38-artifacts/specs/runtime-skill-exit-contract/spec.md

- Source: openspec/changes/reconcile-m29-m38-artifacts/specs/runtime-skill-exit-contract/spec.md
- Lines: 1-37
- SHA256: f5becba15125fa9142d0f22446152e525c5f0b3b790cc029beeb9d0507732287

```md
## ADDED Requirements
### Requirement: Versioned Skills declare bounded exit contracts
Runtime Skill documents declaring `format_version: 2` SHALL include exactly five exit classes: `success`, `failure`, `blocked`, `needs_input`, and `timeout_or_budget`. Each class MUST contain non-empty string fields `condition` and `verifier`, each bounded to 512 UTF-8 bytes. The runtime MUST reject an absolute, unbounded claim when it is the only condition text, including claims that rely solely on words such as "always", "never", "all", "100%", or "完美".

#### Scenario: Version 2 Skill with complete exits is accepted
- **WHEN** a Skill front matter declares `format_version: 2` and all five exit classes contain bounded condition and verifier strings
- **THEN** the Skill enters the immutable registry and its structured exits are available to the read-only Skill tool

#### Scenario: Version 2 Skill missing one exit is isolated
- **WHEN** a version 2 Skill omits `blocked` or gives it an empty field
- **THEN** the runtime skips that Skill, emits one bounded `invalid exit contract` diagnostic, and continues discovering other Skills

#### Scenario: Version 2 Skill uses an unbounded absolute condition
- **WHEN** a version 2 Skill uses only an absolute claim such as `100% complete` as an exit condition
- **THEN** the runtime skips that Skill with an `invalid exit contract` diagnostic

### Requirement: Legacy Skill compatibility is explicit and bounded
Runtime Skills without `format_version` SHALL continue to use the existing five-section parser and SHALL be represented as legacy definitions. Legacy definitions MUST NOT be treated as satisfying the version 2 exit contract, and the runtime SHALL expose their version so callers can distinguish compatibility from governed declarations.

#### Scenario: Existing legacy Skill remains readable
- **WHEN** a pre-existing Skill has only `name`, `trigger`, `Steps`, `Failure Branches`, and `Completion Criteria`
- **THEN** the Skill remains discoverable with `format_version` equal to 1 and its existing full/section reads are unchanged

#### Scenario: Unsupported format version is isolated
- **WHEN** a Skill declares a format version other than 1 or 2
- **THEN** the runtime skips it with a bounded `invalid format version` diagnostic

### Requirement: Trust and reads include the governed contract
The runtime SHALL include a version 2 Skill's five exit classes in deterministic full rendering and project trust effective-input digests. The read-only Skill tool SHALL allow the `exit_conditions` section and SHALL return a deterministic structured rendering without exposing unmasked secret values.

#### Scenario: Project approval covers exit conditions
- **WHEN** a trusted project Skill changes only one exit condition or verifier
- **THEN** its effective-input digest changes and the project Skill requires re-confirmation before overriding a user Skill

#### Scenario: Exit conditions are read by section
- **WHEN** the model requests `exit_conditions` for a governed Skill
- **THEN** the tool returns the five named classes and their condition/verifier pairs, with secrets masked

```

## openspec/changes/reconcile-m29-m38-artifacts/specs/skills-runtime/spec.md

- Source: openspec/changes/reconcile-m29-m38-artifacts/specs/skills-runtime/spec.md
- Lines: 1-23
- SHA256: d86acf9b26c40eb991290081f8a1c21904646810834b7f028962d15d999b2e02

```md
## MODIFIED Requirements

### Requirement: Skill 文档具有可验证的固定结构
系统必须（SHALL）只接受位于独立目录 `SKILL.md` 中、包含非空 `name`、`trigger`、`steps`、`failure_branches` 与 `completion_criteria` 五段内容的 Skill。`name` 必须（MUST）是与目录名一致的 kebab-case 标识符；无效、超限或不可读文档不得进入模型可见目录。文档若声明 `format_version: 2`，还必须包含 `success`、`failure`、`blocked`、`needs_input`、`timeout_or_budget` 五类退出条件；每类都必须有有界 `condition` 与 `verifier`，否则按 fail-closed 规则隔离。未声明版本的既有文档按 legacy version 1 兼容读取，不得被误标为满足 version 2 治理契约。

#### Scenario: 有效 Skill 被发现
- **WHEN** 用户级目录包含结构完整且名称匹配的 `review-code/SKILL.md`
- **THEN** 系统将 `review-code` 加入可用 Skill 目录

#### Scenario: 无效 Skill 被隔离
- **WHEN** `SKILL.md` 缺少失败分支或名称与目录不一致
- **THEN** 系统跳过该 Skill、输出有界诊断且继续加载其他有效 Skill

#### Scenario: governed Skill 缺少退出契约被隔离
- **WHEN** `SKILL.md` 声明 `format_version: 2` 但缺少五类退出条件之一
- **THEN** 系统跳过该 Skill、输出 `invalid exit contract` 有界诊断且继续加载其他有效 Skill

### Requirement: 模型通过只读工具按需加载 Skill
系统必须（SHALL）提供只读 `Skill` 工具，接收一个目录中存在的 Skill 名称并把经过掩码的完整五段文档作为工具反馈返回；工具还必须（MUST）允许按 `steps`、`failure_branches` 或 `completion_criteria` 单段重读，以便在 M17 有界反馈截断整篇内容后继续。对于声明 `format_version: 2` 的 Skill，工具还必须允许按 `exit_conditions` 单段重读，并返回五类退出条件的结构化文本；模型自主依据触发描述决定是否调用，不得（MUST NOT）增加独立意图识别器或额外 LLM 请求。

#### Scenario: governed Skill 的退出契约可按需读取
- **WHEN** 模型针对当前任务调用 `Skill` 并请求 `exit_conditions`
- **THEN** 下一轮反馈包含五类退出条件及其 condition/verifier，且敏感值已掩码

```

## openspec/changes/reconcile-m29-m38-artifacts/specs/structured-collaboration-handoff/spec.md

- Source: openspec/changes/reconcile-m29-m38-artifacts/specs/structured-collaboration-handoff/spec.md
- Lines: 1-58
- SHA256: 8aaf99b21da8be5a4b978a4589089269918bc2a4ef790be9867b811037393cae

```md
## ADDED Requirements
### Requirement: Collaboration roles exchange a bounded structured handoff

ForgeAgent SHALL create a validated `HandoffPacket` for each Planner, Generator and Evaluator boundary. The packet MUST contain bounded goal/scope projection, verified facts, explicit assumptions, open side-effect receipt projection, capability/approval projection, checkpoint, stop conditions, and a fixed return owner. Model-generated free-form summaries MUST NOT become durable handoff facts.

#### Scenario: Generator receives Planner handoff
- **WHEN** a Triad plan is submitted and confirmed
- **THEN** the Generator task data contains a validated handoff with the frozen plan digest, current phase, verified facts, explicit empty-or-bounded assumptions, capability/approval projection and return owner `evaluator`

#### Scenario: Evaluator receives Generator handoff
- **WHEN** the Generator successfully submits the current Candidate
- **THEN** the Evaluator task data contains a handoff tied to the current generator attempt and revision, lists only its read-only capabilities/frozen checks, and returns responsibility to `caller`

#### Scenario: Rejected Candidate returns to Generator
- **WHEN** Evaluator submits a failing verdict and the runner starts a new Generator attempt
- **THEN** the handoff preserves the frozen plan digest, includes bounded failed evaluation facts, identifies the current attempt and revision, and returns responsibility to `evaluator`

### Requirement: Handoff packets are deterministic and resumable

ForgeAgent SHALL derive handoff packets only from validated collaboration state and host-owned public projections. The same state, role, attempt and capability inputs MUST produce the same packet and digest. Resume MUST rebuild the packet from durable state rather than trusting an old model summary. Handoff persistence MUST NOT change existing collaboration state transition or completion invariants.

The raw collaboration goal used to execute Planner, Generator and Evaluator tasks MUST remain an internal execution input and MAY retain a legitimate absolute path required by the task. `HandoffPacket.goal`, CollaborationReport and handoff audit MUST use a separate bounded public projection that masks secrets, absolute paths and unsafe characters. Public audit MUST NOT contain either the raw goal or the public goal prose.

#### Scenario: Resume reconstructs the same handoff
- **WHEN** a collaboration resumes from an evaluator phase with an empty verdict
- **THEN** the new Evaluator receives the same handoff digest for the same state and host capability projection, and no in-memory pre-crash summary is required

#### Scenario: Handoff input contains unsafe text
- **WHEN** goal, evidence, receipt labels or loop context contain secrets, absolute paths or control characters
- **THEN** the packet's public fields use existing masking and bounded text rules, while internal role task data preserves only the validated execution goal and routing or receipt ownership retains raw internal identities only where already required

#### Scenario: Legitimate execution path remains available
- **WHEN** a validated goal instructs a role to process an absolute path such as `/data/input.csv`
- **THEN** the internal role task goal retains that path for execution, while `HandoffPacket.goal`, CollaborationReport and audit contain no absolute path or raw goal body

### Requirement: Handoff exposes risk and authority without granting authority

ForgeAgent SHALL project open receipts using only public server/tool labels, phase and dispatch certainty, and SHALL mark unresolved actions as requiring explicit reconciliation. Capability and approval fields MUST be host-derived summaries; the packet MUST NOT grant new tools, bypass confirmation, resolve receipts, replay actions, or alter role ownership.

#### Scenario: Open external receipt is present
- **WHEN** a role boundary has an open external-action receipt
- **THEN** the handoff reports a bounded unresolved receipt projection and requires explicit reconciliation before retry; it does not call `resolve()` or replay the action

#### Scenario: No receipt store is available
- **WHEN** a role runs without a receipt store
- **THEN** the handoff explicitly reports that receipt visibility is unavailable rather than claiming there are no external actions

### Requirement: Handoff audit is bounded and compatible

ForgeAgent SHALL emit a handoff audit event containing only role, phase, attempt, revision, digest prefix, bounded counts, and return owner. Existing `CollaborationReport` fields, Single mode behavior, role Submit gates, loop context compatibility, and CLI/HTTP public report shape MUST remain unchanged.

#### Scenario: Handoff audit is emitted
- **WHEN** a role task starts with a handoff packet
- **THEN** audit contains a stable digest prefix and counts but no goal prose, plan text, file content, command, secret, absolute path or full receipt identifier

#### Scenario: Single mode remains unchanged
- **WHEN** a task uses Single mode
- **THEN** no collaboration handoff is created and the existing `TaskOutcome` path is used

```
