# Comet Design Handoff

- Change: prompt-memory-rewrite-governance
- Phase: design
- Mode: compact
- Context hash: e6ed167fa93b26c519f80fe04c47ff9c324750ab2f5ce820e00b71f8e891f2c2

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/prompt-memory-rewrite-governance/proposal.md

- Source: openspec/changes/prompt-memory-rewrite-governance/proposal.md
- Lines: 1-30
- SHA256: 26be1c311341d0acecf4926b4c446eb9cf67c6018d58d62f4158d09653ce93fe

```md
# Prompt、Memory 与重写治理门禁

## Why

评审已确认 Prompt/Skill 退出条件、Memory 四问和 Rewrite/依赖门禁是可借鉴的流程纪律，但当前项目只有分散的原则描述，没有一份可执行、可回归检查的入口。继续迭代时容易出现提示词没有停止证明、长期记忆缺少来源与失效策略，或重写/引入依赖没有基线和回滚证据的问题。

## What Changes

- 新增一份项目级治理门禁，规定每条新增或修改的长期 Prompt/Skill 必须声明成功、失败、阻塞、需输入和超时/预算退出条件。
- 将 Memory 四问固化为写入长期记忆前必须填写的评审字段：为什么记、什么是真相、何时失效、谁可见以及如何删除/更正。
- 将 Rewrite/依赖门禁固化为变更评审模板，要求提供性能、可靠性、维护成本、兼容性、团队能力和迁移/回滚成本的基线、门槛与证据。
- 增加文档契约测试，检查门禁章节、字段和关键反例不会被后续规划文档删除或改成不可验收的绝对承诺。
- 不改变 Skill、Memory、Prompt 的运行时数据格式或行为，不迁移既有 `MEMORY.md`，不新增依赖。

## Capabilities

### New Capabilities

- `agent-governance-gates`: 为长期 Prompt/Skill、长期 Memory 和大规模重写/依赖变更提供可验证的项目级流程门禁。

### Modified Capabilities

无。现有运行时能力不改变；本 change 只新增开发期治理契约和其文档回归检查。

## Impact

- 文档：`spec.md`、`MILESTONE_GUIDE.md`、`docs/reviews/2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md`、`docs/threat-model.md`。
- 测试：新增治理文档契约测试，不调用网络、不需要模型凭据。
- OpenSpec/Comet：新增独立 change 和归档能力规格。
- 发布：PyPI 上传、正式 tag、远程 push 与 `publish-v0-1-0` 均不在范围内，继续暂停。

```

## openspec/changes/prompt-memory-rewrite-governance/design.md

- Source: openspec/changes/prompt-memory-rewrite-governance/design.md
- Lines: 1-61
- SHA256: f9f584dd119634b289bbaecd0de4f591ddb047a0b5f7d76780e152bf4149872e

```md
# Prompt、Memory 与重写治理门禁设计

## Context

M31 已完成候选清单中的结构化 handoff。下一候选不是新的运行时能力，而是三条开发期质量纪律：长期 Prompt/Skill 的退出条件、长期 Memory 的四问、以及 Rewrite/依赖引入的量化门槛。当前实现已有 Skill 的失败分支/完成标准和 Memory 的安全写入边界，但缺少一个跨任务、可回归验证的治理入口。

## Goals / Non-Goals

**Goals:**

- 建立单一中文治理文档，作为 `spec.md`、`MILESTONE_GUIDE.md` 和后续 Comet 设计评审的引用入口。
- 把五类退出条件、Memory 四问（含可见性、恢复与删除/更正）和六项 Rewrite 门禁写成短字段、可检查的模板。
- 用纯本地文档契约测试锁定关键条款和 PyPI 发布暂停边界。

**Non-Goals:**

- 不改变 `SkillDefinition`、`MemoryCandidate`、Prompt 模板或持久化文件格式。
- 不迁移既有 `MEMORY.md`，不增加数据库、依赖、网络服务、自动记忆过期或 Rewrite 自动评分器。
- 不恢复 PyPI 发布，不创建 tag，不 push，不推进 `publish-v0-1-0`。

## Decisions

### 1. 采用 canonical 文档 + 引用，而不是运行时 schema

新增 `docs/agent-governance-gates.md` 作为流程事实源；`spec.md`、`MILESTONE_GUIDE.md` 和综合借鉴清单只引用其章节。这样可以让规范被人和评审工具读取，同时避免破坏现有 Skill/Memory 兼容格式。

备选方案是给 Skill frontmatter 和 Memory 行格式增加字段。该方案会引入旧文档迁移、持久化兼容和提示词上下文膨胀，与“流程纪律（零代码）”候选范围不符，否决。

### 2. 用静态文档契约测试作为最小 verifier

新增 `tests/test_governance_docs.py`，读取 canonical 文档和少量入口文档，逐项断言稳定标题、关键字段、反例和发布暂停词。测试不解析 Markdown AST、不访问网络、不读取凭据；失败消息包含缺失条款名称。

### 3. 退出条件采用统一五元模板

每个长期 Prompt/Skill 变更必须使用：`success`、`failure`、`blocked`、`needs_input`、`timeout_or_budget` 五行，并同时写 `condition` 和 `verifier`。现有 Skill 的 `Failure Branches`/`Completion Criteria` 继续作为运行时提示内容，不在本 change 中强制迁移。

### 4. Memory 四问扩展为可执行审查卡

治理模板要求回答：`why_remember`、`truth_source`、`expires_or_revalidate`、`visibility_and_recovery`、`delete_or_correct`。`visibility_and_recovery` 合并回答“谁可见”和“崩溃后哪份恢复”，避免将同一问题拆成两个无法独立验证的栏目。旧 Memory 内容不因本 change 自动补标。

### 5. Rewrite 门禁只规定证据，不自动给结论

六项固定指标为性能、可靠性、维护成本、兼容性、团队能力、迁移/回滚风险。每项必须有 baseline、threshold、evidence、migration、rollback trigger；缺任一项只能作为探索，不得进入实施。门禁不设全局数值阈值，因为不同模块的基线和风险不同。

## Risks / Trade-offs

- [流程文档与实现漂移] → 文档契约测试锁定入口条款；运行时 Skill/Memory 行为仍由各自专项测试负责。
- [模板过长导致形式主义] → 每个字段限制为一句话或一个可定位证据引用，不引入自动评分器。
- [旧文档不符合五元模板] → 只对新增或实质修改的长期 Prompt/Skill 生效，旧内容保持兼容并在后续变更中渐进补齐。
- [发布约束被误解] → canonical 文档和测试均检查 PyPI 暂停、不得 tag/push、不得推进 `publish-v0-1-0`。

## Migration Plan

1. 先添加失败的文档契约测试，确认测试能识别缺失条款。
2. 新增 canonical 治理文档，并在 `spec.md`、`MILESTONE_GUIDE.md`、综合借鉴清单和 threat model 中建立引用。
3. 运行定向测试、Markdown/diff 检查、全量 pytest、Ruff 和 OpenSpec strict。
4. 回滚只需移除本 change 新增文档、测试和引用；无运行时数据迁移。

## Open Questions

未来若要求运行时自动拒绝缺少退出条件的 Skill，必须另立 change，先定义旧 Skill 迁移、用户覆盖和 verifier 可信边界。

```

## openspec/changes/prompt-memory-rewrite-governance/tasks.md

- Source: openspec/changes/prompt-memory-rewrite-governance/tasks.md
- Lines: 1-17
- SHA256: 9dd4301a4c458cc8b92f8ac288f5cc8b7ad6894570a8baff4a5e7f8500e291a7

```md
## 1. 建立治理契约测试

- [ ] 1.1 新增 `tests/test_governance_docs.py`，用本地文件读取断言 Prompt/Skill 五类退出条件、Memory 四问、六项 Rewrite 门禁和 PyPI 暂停条款；先运行该文件确认 canonical 文档尚不存在时按预期失败。
- [ ] 1.2 为缺失条款提供可定位的断言消息，并断言测试不依赖网络、凭据或发布命令。

## 2. 编写并接入治理规范

- [ ] 2.1 新增 `docs/agent-governance-gates.md`，提供长期 Prompt/Skill 退出条件模板、Memory 四问模板、Rewrite/依赖六指标模板和最小验收/反例。
- [ ] 2.2 在 `spec.md` 增加治理门禁入口；在 `MILESTONE_GUIDE.md` 增加阶段 1/3/4/5 的引用和检查项，保持原有里程碑结构不变。
- [ ] 2.3 在 `docs/reviews/2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md` 补充 canonical 文档链接、候选 5 的验收指针和“仅新增/实质修改内容生效”的兼容边界。
- [ ] 2.4 在 `docs/threat-model.md` 增加治理漂移/无退出条件/Memory 来源不明/无回滚证据的开发期风险与缓解措施。

## 3. 验证与收尾

- [ ] 3.1 运行治理专项测试，确认红-绿转换和关键反例覆盖。
- [ ] 3.2 运行完整 `pytest`、`uv run ruff check .`、`uv run ruff format --check .`、`git diff --check` 和 `openspec validate --all --strict --no-interactive`。
- [ ] 3.3 更新 M32 里程碑与 `milestones/latest`；完成两轮最终自评，明确未修改运行时、未迁移 Memory、未恢复 PyPI，并保持 `publish-v0-1-0` 不推进。

```

## openspec/changes/prompt-memory-rewrite-governance/specs/agent-governance-gates/spec.md

- Source: openspec/changes/prompt-memory-rewrite-governance/specs/agent-governance-gates/spec.md
- Lines: 1-51
- SHA256: 2b7d334585b2748293661f3d025967aadc3f72102ba3e3f9d61328a5e504a399

```md
# agent-governance-gates Specification

## ADDED Requirements

### Requirement: Long-lived Prompt and Skill instructions declare bounded exits

The project SHALL require every newly added or materially changed long-lived Prompt or Skill instruction to declare five exit classes: success, failure, blocked, needs-input, and timeout-or-budget. Each exit declaration MUST name an observable condition and the responsible verifier, and MUST NOT use an unbounded absolute claim as its only acceptance condition.

#### Scenario: A new Skill is proposed
- **WHEN** a change adds or materially changes a long-lived Skill or Prompt instruction
- **THEN** its proposal or design records all five exit classes, a bounded condition for each, and the verifier that observes the condition

#### Scenario: A prompt instruction lacks a verifier
- **WHEN** a proposed instruction has prose guidance but no observable verifier or exit condition
- **THEN** the change is rejected by the governance review until the condition and verifier are added or the instruction is removed

### Requirement: Durable Memory proposals answer the four governance questions

The project SHALL require every proposal to write or change durable project Memory to answer why the item is remembered, what source is authoritative truth, when the item expires or is revalidated, who can see it, and how a user deletes or corrects it. Session-only Memory MAY use the session boundary as its visibility and recovery answer, but SHALL still identify its source and correction behavior.

#### Scenario: A project Memory write is proposed
- **WHEN** a change adds or changes a durable project Memory path
- **THEN** the design records purpose, authoritative source, expiry or revalidation rule, visibility, recovery copy, and deletion/correction action

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

### Requirement: Governance gates are regression-tested and release-neutral

The project SHALL keep a local, deterministic document contract test for the governance gate. The test MUST check the five Prompt/Skill exits, the Memory questions including visibility and correction, the six rewrite metrics, and the release pause wording. The gate MUST NOT publish artifacts, create tags, push remotes, or advance the active PyPI release change.

#### Scenario: Governance wording is accidentally removed
- **WHEN** a required heading, field, or release-pause guard is deleted from the canonical governance document
- **THEN** the document contract test fails with the missing contract name

#### Scenario: Governance verification runs in CI
- **WHEN** the contract test runs in an offline test environment
- **THEN** it completes without network access, model credentials, package upload, tag creation, or remote push

```
