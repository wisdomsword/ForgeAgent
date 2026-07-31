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

核心能力由 `MemoryManager` 的 readiness、migrate、verify、rollback、correct/delete/revalidate 方法提供。项目内离线 verifier 只调用这些权威 API，并只输出公开结果；不访问网络、凭据或项目外路径。当前仓库运行 readiness 后应得到 `no_data`，因此不调用 migrate。

## Risks / Trade-offs

- **[风险] v1 存在时项目写入被拒绝，影响旧工作流** → 旧数据仍可读；返回明确 `migration_required`，并提供 readiness、manifest 校验和可回滚迁移，不静默损坏治理语义。
- **[风险] 人工编辑破坏元数据/正文配对** → 解析器逐条 fail closed，诊断固定；受控纠错 API 原子更新，文档说明人工编辑必须保留合法元数据 comment。
- **[风险] 备份本身扩大敏感数据驻留** → 备份只位于项目内私有目录、权限 `0600`、名称不含 key/content，公开报告不含路径；删除备份不在自动流程中发生。
- **[风险] 时间策略过于武断** → 不引入统一天数；日期字段可空，但 `revalidate_on` 必填。只有明确到达的日期触发停止注入。
- **[风险] rollback 覆盖迁移后新写入** → revision 冲突即拒绝回滚，不提供 force 选项。
- **[风险] v2 元数据令文件更大** → 分离 storage/render 上限并同时验证，仍保持 64 条上限和有界解析。

## Migration Plan

1. 运行 readiness，不写盘；记录状态和条目计数。
2. `no_data`：记录跳过结果并结束；`current`：运行 verifier；`repair_required/unsafe`：停止并人工修复；v1：继续下一步。
3. 操作者根据权威来源为每个旧 key 提供完整 manifest，不从正文自动推断。
4. 在锁内重读、验证 manifest、创建私有恢复副本、写入 v2 并执行语义 verifier。
5. verifier 失败时自动恢复；成功后保留恢复副本和 opaque migration id。
6. 只有当前 revision 未发生后续变化时允许显式 rollback；回滚后再次解析验证 v1 字节和条目计数。

## Open Questions

无阻塞问题。未来如需要统一时间 TTL、备份保留周期或跨设备 Memory，同样需要新的独立 change 和真实使用场景；M42 不预设这些策略。
