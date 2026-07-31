# Comet Design Handoff

- Change: migrate-memory-metadata
- Phase: design
- Mode: compact
- Context hash: 51095a8476600629ca870d6dd62175f0cb0c35c30845c73d05a91d1293438f63

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/migrate-memory-metadata/proposal.md

- Source: openspec/changes/migrate-memory-metadata/proposal.md
- Lines: 1-30
- SHA256: c922f22fe64947b76d1ff02c0cf1f5fb595e24a3a50beeee9a1632c8a2ba2f08

```md
## Why

现有项目级 Memory 仅持久化 `key: content`，无法回答来源、写入者、可见性、何时过期或复核、如何恢复以及如何删除或纠错。M32 已定义治理门禁，但尚无运行时元数据、迁移或回滚能力；在长期 Memory 被用于跨进程恢复前，需要先建立可验证且不推断历史事实的迁移边界。

## What Changes

- 将项目级 `MEMORY.md` 升级为单文件 v2 格式，为每条持久化 Memory 保存由宿主生成和校验的治理元数据，同时保持正文可人工审阅和纠错。
- 提供只读 migration readiness 检查，区分无数据、已是 v2、可迁移 v1、需人工修复和不安全存储等状态，公开结果不包含正文、secret 或绝对路径。
- 提供显式迁移、验证和摘要绑定的回滚能力；迁移前创建私有恢复副本，迁移失败时自动恢复，不自动推断旧记录的来源或写入者。
- 过期或已到复核期的项目 Memory 不再作为有效上下文注入；纠错、删除和复核更新都必须经过宿主控制的原子写入路径。
- **BREAKING**：检测到旧 v1 文件时，新的项目级写入返回 `migration_required`，不得通过普通写入静默升级或继续产生无元数据记录；旧文件仍可加载和渲染。
- 当前仓库没有真实 `MEMORY.md` 历史数据，因此本里程碑只运行 readiness 并记录 `no_data` 证据，不制造或迁移虚构数据。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `runtime-memory`：增加持久化 Memory 的治理元数据、生命周期过滤、readiness、备份、显式迁移、验证和回滚契约，并定义旧 v1 的兼容边界。

## Impact

- 主要影响 `src/forgeagent/memory.py`、Memory 相关测试和迁移验证入口；不新增第三方依赖。
- `MemoryCandidate` 的模型可提交字段保持不变，治理元数据由宿主根据可信调用上下文生成，模型不能修改。
- 继续复用现有项目根目录边界、文件锁、原子替换、大小限制、secret 检查和审计脱敏机制。
- 不扫描或修改项目目录外的数据，不引入数据库、向量检索、网络服务或后台过期调度。
- 不执行 PyPI、tag、push 或任何发布自动化。

```

## openspec/changes/migrate-memory-metadata/design.md

- Source: openspec/changes/migrate-memory-metadata/design.md
- Lines: 1-104
- SHA256: 44d093845a9c6c08983a126971b27e027976956d7f8dec08e7108a42d8a81eb2

[TRUNCATED]

```md
## Context

ForgeAgent 当前把项目级 Memory 存在 `allowed_root/.forgeagent/MEMORY.md`，v1 文件只有 marker 和 `- key: content` 条目。它已具备准入、跨进程锁、原子替换、大小限制、secret 检查和脱敏审计，但无法表达 M32 治理门禁要求的来源、写入者、真相边界、可见性、失效/复核、恢复和纠错策略。

当前仓库的 `.forgeagent/` 下没有 `MEMORY.md`，所以没有可在本里程碑中实际迁移的历史记录。设计仍需覆盖带真实 v1 数据的项目，但必须先只读检查，再由调用方提供逐条完整元数据；系统不得根据正文猜测历史来源。

## Goals / Non-Goals

**Goals:**

- 用单文件 v2 格式保存正文和宿主拥有的治理元数据，并保持人工可读、跨进程安全和原子提交。
- 对 v1/v2/无数据/损坏/不安全路径给出稳定、最小披露的 readiness 结果。
- 提供可演练的备份、显式迁移、语义验证、自动恢复和有冲突保护的回滚。
- 让到期或需复核的条目停止进入模型上下文，同时保留受控纠错、删除和复核路径。
- 维持 `MemoryCandidate` 协议和 session Memory 行为，不新增依赖。

**Non-Goals:**

- 不实现向量检索、Memory 排名、远程同步、数据库、后台调度或 LLM 元数据推断。
- 不扫描用户主目录或项目根目录之外的 Memory。
- 不迁移当前仓库不存在的历史数据，也不把测试 fixture 当成生产迁移。
- 不改变项目身份、权限、预算、发布或外部动作审批边界。

## Decisions

### 1. 采用单文件 v2，拒绝 sidecar 和 JSON 主存储

`MEMORY.md` v2 继续使用 Markdown 正文，每条正文前放置一行紧邻的机器生成元数据 comment；文件头包含格式版本和随机 revision。解析器只接受完整且相邻的元数据/正文对，key、content、kind 和元数据都需通过既有准入及新治理校验。

选择单文件是为了继续复用现有 lock + temp file + `os.replace` 的原子边界。JSON sidecar 会产生正文与元数据不同步的双文件提交；改用 JSON 主存储会破坏既有路径和人工纠错契约。

元数据至少包含：

- `why_remember`
- `source`
- `writer`
- `who_can_write`
- `truth_source`
- `visibility`
- `written_at`
- `expires_at`（可为空）
- `review_after`（可为空）
- `revalidate_on`
- `recovery`
- `delete_or_correct`

正常写入的元数据由宿主根据可信调用上下文生成。`source` 表示候选来自哪个受控入口，`truth_source` 表示内容的权威边界，两者不得混写。Task 模型候选、用户 `/remember` 和内部 host API 使用不同的固定 source/writer/truth_source 投影；这些字段不加入 `MemoryCandidate`，模型无法提交或覆盖。无日期失效条件时必须仍有明确的 `revalidate_on`，避免以任意天数代替真实产品策略。

### 2. 分离存储上限与上下文上限

v2 元数据增加文件体积。存储文件使用独立且有界的上限，模型上下文仍受现有 render 上限约束；准入新条目时同时验证持久化文件和有效上下文大小。这样不会因元数据开销把既有安全上限误当作正文容量，也不会扩大 prompt 注入面。

### 3. 旧 v1 可读，但普通写入不得静默升级

v1 文件继续加载和渲染，以保持旧 checkpoint/project 可恢复。若普通项目写入检测到 v1，返回 `rejected/migration_required`，文件和 manager 快照保持不变。允许继续写 v1 会产生新的无元数据记录；自动补默认值则会把推断伪装成历史事实，因此两者均不采用。

readiness 是只读操作，返回固定状态、格式版本、条目计数和固定原因码；不返回正文、绝对路径、raw exception 或基于正文的公开摘要。状态至少区分 `no_data`、`legacy_ready`、`legacy_needs_metadata`、`current`、`repair_required`、`unsafe`。

### 4. 迁移使用完整 manifest、锁内重验和语义 verifier

显式迁移接收以旧 key 为索引的完整元数据 manifest。迁移在项目锁内重新读取 v1，要求 manifest key 集合与所有合法旧条目完全一致，并拒绝缺字段、额外字段、已变化文件、畸形文件或不安全路径。

写 v2 前先在 `.forgeagent/memory-backups/` 创建 `0600` 的不可覆盖恢复副本，目录和文件都经过项目边界、regular-file 和 symlink 检查。随后原子写入 v2，并重新解析验证：

- key/content 集合与 v1 语义相等；
- 每条元数据完整有效；
- v2 revision 与本次迁移标识一致；
- 有效上下文和存储大小仍在边界内。

验证失败时在同一锁内恢复原字节并返回固定失败码。成功结果只暴露计数、固定状态和 opaque migration id。

### 5. 回滚必须绑定未被后续写入改变的迁移 revision

迁移写入的文件头记录随机 `revision`、`migration_id` 和初始 `migration_revision`。任何后续纠错、删除、复核或普通写入都会生成新 revision。回滚仅在当前 revision 仍等于 `migration_revision`、migration id 匹配且恢复副本安全可读时执行；否则返回 `rollback_conflict`，禁止覆盖迁移后的新事实。

### 6. 失效条目保留在存储中但不进入有效上下文

解析器保留完整项目记录用于查看、纠错和删除；`render()` 只投影未过 `expires_at` 且未到 `review_after` 的条目。时间由可注入时钟提供，测试不依赖墙钟。到期/待复核只产生固定诊断与审计，不回显正文；显式复核通过宿主 API 更新元数据并生成新 revision。

### 7. 运维入口保持窄且离线

```

Full source: openspec/changes/migrate-memory-metadata/design.md

## openspec/changes/migrate-memory-metadata/tasks.md

- Source: openspec/changes/migrate-memory-metadata/tasks.md
- Lines: 1-31
- SHA256: 66b213987c3165de14cca55ba364e10552f47d9306558ae9d06b8d6016917c1f

```md
## 1. Readiness 与格式契约

- [ ] 1.1 先添加失败测试，覆盖无数据、合法 v1、合法 v2、畸形/不安全文件的最小披露 readiness 状态。
- [ ] 1.2 定义 v2 record/header、治理元数据、公开结果和固定原因码类型，保持 `MemoryCandidate` 不承载宿主元数据。
- [ ] 1.3 实现有界 v1/v2 解析与序列化，分离 storage/render 上限，并保持 v1 load/render 只读兼容。
- [ ] 1.4 实现 host API、Task 模型候选和 `/remember` 的固定 source/writer 投影；v1 普通 project 写入返回 `migration_required`。

## 2. 生命周期与受控修改

- [ ] 2.1 先添加失败测试，覆盖 expires_at、review_after、可注入时钟以及正文/路径不进入诊断和审计。
- [ ] 2.2 实现只投影有效记录的 render，并保留失效记录供治理操作读取。
- [ ] 2.3 实现原子纠错、删除和复核操作；每次成功操作生成新 revision 并保持并发 read-modify-write 语义。

## 3. 备份、迁移、验证与回滚

- [ ] 3.1 先添加失败测试，覆盖 manifest 缺失/额外 key、symlink 备份、故障注入自动恢复和公开结果脱敏。
- [ ] 3.2 实现锁内 v1 重验、完整 manifest 校验、项目内 `0600` 恢复副本和 v2 原子迁移。
- [ ] 3.3 实现写后语义 verifier，验证 key/content 等价、元数据完整、revision 与大小边界，并在失败时自动恢复。
- [ ] 3.4 先添加失败测试并实现 revision 绑定 rollback；迁移后任意写入必须返回 `rollback_conflict`，不得无条件重放。

## 4. 运维入口与文档

- [ ] 4.1 提供仅调用权威 Memory API 的离线 readiness/verify 运维入口，不访问网络、凭据或项目外路径。
- [ ] 4.2 更新 runtime Memory 文档、威胁模型和治理说明，明确 v1 只读兼容、manifest 责任、备份位置、回滚冲突和手工纠错边界。
- [ ] 4.3 在当前仓库运行 readiness，记录 `no_data`、零条目、未创建备份且迁移跳过的 M42 证据。

## 5. 验证与里程碑收尾

- [ ] 5.1 运行 Memory 专项测试、相关 Task/CLI 集成测试、全量 pytest、Ruff、format、OpenSpec strict、Comet verify 和 `git diff --check`。
- [ ] 5.2 完成两轮代码/契约自评，检查模糊、错误、过度保守、前后不一致、遗漏和公开信息泄漏；发现问题立即修复并重跑相关验证。
- [ ] 5.3 产出 verification report，归档 change，创建 M42 里程碑并更新 `milestones/latest`；不执行 PyPI、tag、push 或发布自动化。

```

## openspec/changes/migrate-memory-metadata/specs/runtime-memory/spec.md

- Source: openspec/changes/migrate-memory-metadata/specs/runtime-memory/spec.md
- Lines: 1-111
- SHA256: d3270cea2e2c09ddc28efd4f86130a1e080dee87b5a4c2201748c4cdfadcff46

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: 项目 Memory 宿主拥有的治理元数据
系统 SHALL 以单一 `MEMORY.md` v2 文件持久化项目 Memory 正文及其治理元数据。每条记录的元数据 MUST 包含为什么保留、候选来源、实际写入者、谁可写、真相来源、可见性、写入时间、到期/复核条件、恢复来源以及删除/纠错策略；候选来源表示记录来自哪个受控入口，真相来源表示内容的权威边界，两者 MUST NOT 混写。元数据 MUST 由宿主从可信调用上下文生成和校验，模型提交的 `MemoryCandidate` MUST NOT 能设置或覆盖这些字段。文件写入 MUST 继续使用同一项目锁、私有临时文件和原子替换，且存储大小与注入上下文大小 MUST 分别受有界限制。

#### Scenario: 模型候选不能伪造元数据
- **WHEN** Task 接受一个合法的 project `MemoryCandidate`
- **THEN** 宿主使用固定的模型候选 source/writer 策略生成元数据，候选正文不能声明自己是用户或权威工具写入

#### Scenario: 用户显式写入具有独立来源
- **WHEN** 用户通过 `/remember` 提交合法 project 候选
- **THEN** 宿主将来源记录为用户命令路径，并保持治理字段不进入模型可控制协议

#### Scenario: v2 原子持久化
- **WHEN** 新项目在没有 MEMORY.md 时接受首条 project 候选
- **THEN** 系统原子创建可重新加载的 v2 文件，正文和完整元数据属于同一次提交

### Requirement: Memory 迁移 readiness 与旧格式兼容
系统 SHALL 提供不写盘的 readiness 检查，至少区分无数据、可读 v1、缺迁移元数据、有效 v2、需修复和不安全存储。readiness 结果 MUST 只包含固定状态、格式版本、条目计数和固定原因码，不得包含正文、secret、绝对路径、raw exception 或由正文直接导出的公开摘要。旧 v1 文件 SHALL 继续加载和渲染；普通 project 写入遇到 v1 时 MUST 返回 `migration_required`，不得静默迁移或继续产生无元数据记录。

#### Scenario: 当前仓库无历史数据
- **WHEN** 项目 `.forgeagent/` 中不存在 MEMORY.md
- **THEN** readiness 返回 `no_data`、零条目且不创建文件或备份

#### Scenario: 旧 v1 继续可读
- **WHEN** 项目包含合法 v1 MEMORY.md
- **THEN** load 和 render 仍可使用其合法条目，readiness 将其识别为 legacy 且不修改原文件

#### Scenario: 旧 v1 阻止普通写入
- **WHEN** v1 文件存在且普通 Task 或 `/remember` 尝试写入 project Memory
- **THEN** 系统返回 `rejected/migration_required`，磁盘字节和 manager 的项目快照均不改变

#### Scenario: 不安全或损坏存储最小披露
- **WHEN** MEMORY.md、lock 或备份路径为 symlink、越界、不可读或格式不完整
- **THEN** readiness 返回固定的 `unsafe` 或 `repair_required` 原因，不泄漏宿主路径和底层异常文本

### Requirement: 显式 Memory 迁移、验证与恢复副本
系统 SHALL 只在调用方为每个 v1 条目提供完整且有效的治理 manifest 后执行显式迁移，并 MUST 在项目锁内重读源文件和验证 key 集合。系统 MUST NOT 从旧正文推断来源、写入者或真相；manifest 可以显式标记未知历史值，但未知 truth source 的记录 MUST 在迁移后立即处于待复核状态且不得进入有效上下文。写入 v2 前 MUST 创建项目内私有、不可覆盖且 symlink-safe 的恢复副本；写入后 MUST 重新解析并验证 key/content 语义等价、元数据完整、revision 一致以及大小边界。替换前的失败 MUST 保持原 v1 字节；替换后的验证失败 MUST 尝试从恢复副本自动恢复并验证。若恢复无法确认，系统 MUST 返回 `recovery_failed`、保留恢复副本且不得报告迁移成功。迁移结果和审计 MUST NOT 包含 Memory 正文、secret 或绝对路径。

#### Scenario: 缺失 manifest 不迁移
- **WHEN** v1 有两个条目而 manifest 缺少、增加或错误映射任一 key
- **THEN** 迁移在写盘前失败，v1 字节不变且不创建虚假的成功结果

#### Scenario: 未知历史来源不被推断
- **WHEN** 操作者无法证明某条 v1 Memory 的原始写入者或 truth source，并在完整 manifest 中显式标记 unknown
- **THEN** 系统保留该正文但将记录标记为待复核，迁移后不把它注入模型上下文

#### Scenario: 成功迁移并验证语义等价
- **WHEN** 合法 v1 的每个 key 都有完整治理 manifest 且存储路径安全
- **THEN** 系统先创建 `0600` 恢复副本，再原子写入 v2，并由 verifier 证明 key/content 等价和元数据完整

#### Scenario: 写后验证失败自动恢复
- **WHEN** v2 写入后重新解析或语义验证失败
- **THEN** 系统在锁内恢复迁移前字节，返回固定失败码且不报告迁移成功

#### Scenario: 自动恢复无法确认
- **WHEN** 写后验证失败且恢复写入或恢复后验证也失败
- **THEN** 系统返回 `recovery_failed`、保留私有恢复副本并将当前状态视为未知，不得报告迁移或回滚成功

#### Scenario: 迁移报告最小披露
- **WHEN** readiness、migrate 或 verify 返回公开结果并写审计
- **THEN** 结果只包含固定状态、计数和 opaque migration/revision 标识，不包含正文、secret、完整 key 集、原始 manifest 或绝对路径

### Requirement: Memory 回滚的 revision 冲突保护
系统 SHALL 只允许恢复与当前迁移标识匹配的私有副本，且当前 v2 revision MUST 仍等于迁移完成时的 revision。迁移后发生任何写入、纠错、删除或复核时，回滚 MUST 返回 `rollback_conflict`，不得提供无条件覆盖或 force 路径。成功回滚后 MUST 验证恢复字节可按 v1 重新解析。

#### Scenario: 未变化的迁移可回滚
- **WHEN** v2 自迁移完成后未发生变化，且 migration id、revision 和恢复副本均匹配
- **THEN** 系统原子恢复 v1，重新解析成功并返回固定的 rolled_back 结果

#### Scenario: 后续写入阻止回滚
- **WHEN** 迁移后任一记录被新增、替换、删除或复核
- **THEN** 旧迁移的 rollback 返回 `rollback_conflict`，当前 v2 文件保持不变

#### Scenario: 不安全备份拒绝回滚
- **WHEN** recovery 副本缺失、为 symlink、不是 regular file 或不属于项目备份目录
- **THEN** rollback 返回固定失败码且不读取项目外内容

### Requirement: Memory 到期复核、纠错与删除
系统 SHALL 保留完整项目记录用于治理，但 `render()` MUST 排除已到 `expires_at` 或 `review_after` 的记录。日期为空时元数据 MUST 提供明确的 `revalidate_on` 条件。宿主 SHALL 提供受控的纠错、删除和复核操作；每次成功操作 MUST 原子写入新 revision，并使旧迁移 rollback 失效。时间判断 MUST 支持可注入时钟，诊断和审计不得回显正文。

```

Full source: openspec/changes/migrate-memory-metadata/specs/runtime-memory/spec.md
