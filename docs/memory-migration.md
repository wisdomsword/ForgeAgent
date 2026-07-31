# Project Memory v2 与迁移

## 边界

M42 只治理项目级持久化 Memory。session Memory 仍只存在于当前进程。Memory 不是权限、
执行、审批或恢复语义的来源，模型只能提交 `MemoryCandidate`；来源、写入者、可见性、
生命周期和恢复策略由宿主生成并校验。

旧 `forgeagent-memory-v1` 文件可加载、可渲染，但普通 project 写入返回
`migration_required`。系统不会静默升级 v1，也不会为历史记录猜测元数据。

开发期治理问题见 `docs/reviews/2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md`。
M32 模板帮助立项，但不替代 M42 的
运行时 metadata 校验、备份、verifier 和 revision 冲突检查。

## v2 记录与宿主元数据

每条 v2 记录由一行 metadata comment 和一行有界正文组成。header 保存当前 `revision`；
迁移产生的文件还保存 opaque `migration_id` 与 `migration_revision`。以下字段必须完整：

| 字段 | 责任 |
| --- | --- |
| `kind` | `fact`、`preference` 或 `decision` |
| `why_remember` | 跨任务保留原因，与 kind 对应 |
| `source` | 固定宿主入口，不从正文推断 |
| `writer` | 宿主控制的写入者投影 |
| `who_can_write` | 固定为 `host_only` |
| `truth_source` | 事实权威边界，不等于写入入口 |
| `visibility` | 固定为 `project` |
| `written_at` | UTC 写入时间 |
| `expires_at` | 可选到期时间 |
| `review_after` | 可选复核时间 |
| `revalidate_on` | 复核触发策略 |
| `recovery` | 固定恢复介质 |
| `delete_or_correct` | 宿主纠错、删除和复核策略 |

模型候选、`/remember` 和直接 host API 分别投影为固定入口与写入者，正文不能覆盖这些字段。
后续复核保留原始 `source`/`writer`，只更新 `truth_source` 和生命周期条件，避免把新的权威判断
伪装成另一条写入路径。key 与正文使用同一 secret 边界；非法、含 secret 的 key 不进入结果或审计。

## Readiness 决策表

| 状态 | 含义 | 后续动作 |
| --- | --- | --- |
| `no_data` | 没有 Memory 文件 | 不迁移；首次合法写入创建 v2 |
| `legacy_needs_metadata` | v1 可读，但 manifest 缺失或不完整 | 补齐 manifest，不写盘 |
| `legacy_ready` | v1 与完整 manifest 匹配 | 可执行显式 migrate |
| `current` | 完整 v2 | 执行 verify 后继续使用 |
| `repair_required` | 格式、大小或 metadata 无效 | 停止，不自动修复 |
| `unsafe` | 路径或文件类型不安全 | 停止并人工处理存储边界 |

readiness 只返回状态、格式、条目数和固定原因码，不创建目录、锁、备份或 Memory 文件。

## Legacy manifest 责任

manifest 必须位于目标项目内，使用相对路径，并与 v1 key 集精确相等。操作者必须为每条
记录明确提供上表全部字段；不推断 kind、来源或权威性。`source` 必须为
`legacy_manifest`。当 `truth_source` 为 `unknown` 时，迁移把 `review_after` 收敛为不晚于
迁移时刻；该记录立即待复核且不进入 prompt。

## 显式迁移与 0600 恢复副本

迁移在项目锁内重新读取 canonical v1，验证完整 manifest，再在
`.forgeagent/memory-backups/` 创建不覆盖的恢复副本。目录权限收敛为 `0700`，副本权限为
`0600`。v2 写入后必须重读并证明 key、正文、metadata 和迁移 header 等价；验证失败时
自动恢复原始 v1。恢复无法确认时返回 `recovery_failed`，不得宣称成功。备份不会自动删除。

## Verify 与 revision 绑定 rollback

verify 是只读操作。rollback 只接受 32 位小写 hex migration id，并要求当前
`revision == migration_revision`。迁移后发生任何写入、纠错、删除或复核时，rollback 返回
`rollback_conflict/revision_changed`。接口没有 `force`，也不会无条件重放旧状态。

## 到期、复核、纠错和删除

`expires_at <= now` 或 `review_after <= now` 的记录仍保留在 v2 文件中，但不进入 prompt。
`truth_source=unknown` 的记录不依赖当前时钟，始终保持待复核，直到宿主显式复核或纠正。
宿主可调用受控纠错、删除或复核操作；每次成功操作都生成新 revision。复核保留记录的原始
`source`/`writer`，并更新 `truth_source` 与新的复核/到期条件。

## 人工编辑边界

不要直接编辑 v2 metadata 或 header。严格 parser 会把缺字段、额外字段、无效时间、重复 key
或未配对记录视为整个快照 `repair_required`。需要纠错时使用宿主 API；需要恢复时使用
revision 绑定 rollback。v1 也不能通过普通 `/remember` 继续追加。

## 离线命令

```bash
uv run python scripts/m42_memory_migration.py readiness --root /absolute/project
uv run python scripts/m42_memory_migration.py readiness --root /absolute/project --manifest .forgeagent/memory-manifest.json
uv run python scripts/m42_memory_migration.py migrate --root /absolute/project --manifest .forgeagent/memory-manifest.json
uv run python scripts/m42_memory_migration.py verify --root /absolute/project
uv run python scripts/m42_memory_migration.py rollback --root /absolute/project --migration-id 0123456789abcdef0123456789abcdef
```

命令只调用权威 Memory API，不访问网络或凭据；stdout 是单行固定 JSON。manifest 只能是项目
相对 regular JSON，symlink、绝对路径、越界路径、超限文件和异常文本均 fail closed。

## 当前仓库 M42 证据

2026-07-31 在 ForgeAgent 仓库根目录运行 readiness，结果为 `no_data`、`entry_count=0`、
`format_version=none`。因此历史数据迁移被跳过，没有创建 `.forgeagent/MEMORY.md` 或
`.forgeagent/memory-backups/`；这属于 readiness 成功，不是缺失实施。
