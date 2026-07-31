---
comet_change: migrate-memory-metadata
role: technical-design
canonical_spec: openspec
---

# Memory 元数据迁移技术设计

## 1. 现状与边界

`MemoryManager` 当前同时负责 session Memory、project Memory 的 v1 Markdown 解析、准入、原子写入、跨进程锁、prompt 投影和审计。M42 只扩展 project 持久化路径；session Memory 继续只存在进程内，不参与迁移。

```text
MemoryCandidate                    trusted call site
      |                                   |
      +----------------+------------------+
                       v
               MemoryManager.apply
                       |
          admission + host metadata
                       |
              project lock / reload
                       |
          MEMORY.md v2 atomic replace
                       |
        parse records -> active projection
```

模型仍只能提交 `scope/kind/key/content`。治理元数据不加入文本协议、native tool schema 或 `MemoryCandidate`，从根源上避免模型自称“用户写入”或“工具已证实”。

## 2. 类型设计

### 2.1 受控写入来源

`MemoryManager.apply` 增加 keyword-only 的 `source`，默认保持内部 host API 兼容：

```python
MemoryWriteSource = Literal["host_api", "model_candidate", "user_command"]

def apply(
    self,
    candidate: MemoryCandidate,
    task_id: str | None = None,
    *,
    source: MemoryWriteSource = "host_api",
) -> MemoryResult: ...
```

可信调用点负责选择 source：

| 调用点 | source | writer | truth_source |
| --- | --- | --- | --- |
| Task 解析出的模型候选 | `model_candidate` | `task_host` | `model_output_unverified` |
| REPL `/remember` | `user_command` | `interactive_host` | `user_statement` |
| 直接 host API | `host_api` | `host_api` | `host_assertion` |
| v1 manifest | `legacy_manifest` | manifest 值或 `unknown` | manifest 值或 `unknown` |

source 表示进入 Memory 系统的受控入口；truth_source 表示正文的权威边界。二者必须分别序列化。

### 2.2 持久化记录

使用 frozen dataclass，避免把可变字典当作内部权威状态：

```python
@dataclass(frozen=True)
class MemoryGovernance:
    why_remember: str
    source: str
    writer: str
    who_can_write: str
    truth_source: str
    visibility: str
    written_at: str
    expires_at: str | None
    review_after: str | None
    revalidate_on: str
    recovery: str
    delete_or_correct: str

@dataclass(frozen=True)
class ProjectMemoryRecord:
    candidate: MemoryCandidate
    governance: MemoryGovernance

@dataclass(frozen=True)
class MemoryFileHeader:
    revision: str
    migration_id: str | None = None
    migration_revision: str | None = None
```

所有枚举式字符串使用显式白名单，不接受控制字符、路径或任意长文本。时间戳只接受 UTC RFC 3339 `YYYY-MM-DDTHH:MM:SSZ`；内部比较转换为 timezone-aware `datetime`。revision 和 migration id 使用 `secrets.token_hex(16)`，只作为 opaque 并发标识，不由正文摘要生成。

正常写入的固定值：

- `why_remember`：按 kind 映射为 `cross_task_fact`、`cross_task_preference` 或 `cross_task_decision`。
- `who_can_write`：`host_only`。
- `visibility`：`project`。
- `expires_at/review_after`：默认 `None`，不引入武断统一 TTL。
- `revalidate_on`：`conflict_or_explicit_review`。
- `recovery`：`project_memory_file`。
- `delete_or_correct`：`host_replace_delete_or_revalidate`。

legacy manifest 必须提供所有字段。无法证明的历史 writer/truth_source 允许显式 `unknown`；若 truth_source 为 `unknown`，迁移器把 `review_after` 规范化为不晚于迁移时刻，使记录立即待复核。它仍保存在 v2 中，但不会进入 prompt。

### 2.3 公开结果

readiness 和运维操作返回 frozen dataclass，只暴露固定字段：

```python
MemoryReadiness(status, format_version, entry_count, reason)
MemoryOperationResult(status, entry_count, reason, migration_id=None)
```

允许状态：

- readiness：`no_data`、`legacy_needs_metadata`、`legacy_ready`、`current`、`repair_required`、`unsafe`。
- migration：`migrated`、`not_required`、`rejected`、`persistence_error`、`recovery_failed`。
- verify：`verified`、`not_current`、`repair_required`、`unsafe`。
- rollback：`rolled_back`、`rollback_conflict`、`backup_unavailable`、`persistence_error`、`recovery_failed`。

reason 只能来自固定 reason-code 集。公开对象不保存正文、绝对路径、raw exception、manifest、key 集或正文摘要。

## 3. v2 文件格式

格式保持逐行、有界、可人工检查：

```markdown
<!-- forgeagent-memory-v2: {"migration_id":null,"migration_revision":null,"revision":"0123456789abcdef0123456789abcdef"} -->
<!-- forgeagent-memory-meta: {"delete_or_correct":"host_replace_delete_or_revalidate","expires_at":null,"kind":"preference","recovery":"project_memory_file","revalidate_on":"conflict_or_explicit_review","review_after":null,"source":"user_command","truth_source":"user_statement","visibility":"project","who_can_write":"host_only","why_remember":"cross_task_preference","writer":"interactive_host","written_at":"2026-07-31T10:00:00Z"} -->
- preferred-editor: nvim
```

序列化使用 `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True)`，确保 deterministic ASCII metadata。正文继续使用既有 `- key: content` 语法。parser 状态机只有三步：

1. 第一行必须是唯一 v1 或 v2 header。
2. v2 中每个 metadata comment 必须紧邻一个正文条目，且 metadata `kind` 与 candidate 一致。
3. 未配对、重复 key、未知字段、无效 JSON、额外非空行或超过上限均使整个 v2 readiness 为 `repair_required`；load 对整个 v2 fail closed，避免只加载部分记录形成错误权威集。

v1 保持现有逐条隔离行为，以兼容旧文件；但迁移只接受没有畸形非空行、没有重复 key 的 canonical v1，防止迁移时悄悄丢弃数据。

文件限制：

- `_MAX_ENTRIES = 64` 保持不变。
- `_MAX_RENDER_BYTES = 32 KiB` 继续约束进入 prompt 的 session + active project 内容。
- 新增 `_MAX_STORAGE_BYTES = 64 KiB` 约束含 metadata 的 MEMORY.md 和恢复副本。
- 单条正文、key、控制字符、secret 和 injection 检查保持既有规则。

## 4. 内存状态与生命周期

manager 分开保存：

- `_session: dict[str, MemoryCandidate]`
- `_project: dict[str, ProjectMemoryRecord]`
- `_project_format: Literal["none", "v1", "v2", "invalid"]`
- `_header: MemoryFileHeader | None`

`load()` 对 v1 构造仅供兼容渲染的 legacy record，不伪造持久化 metadata；`_project_format="v1"` 阻止普通写入。对 v2 保存全部 records。

`render()` 每次使用注入的 `clock: Callable[[], datetime]` 计算有效记录：

- `now >= expires_at`：expired。
- `now >= review_after`：review due。
- legacy v1：兼容期继续渲染。
- v2 unknown truth：manifest 已确保 review due，因此不渲染。

同一次 revision 的每个失效 key 最多发一次固定诊断/审计，避免每次 render 制造日志噪音。审计参数只包含 scope、kind、key、固定 reason 和 revision/migration id；不含时间之外的原始 metadata。

## 5. Readiness

```text
safe path?
  no  -> unsafe
  yes -> file exists?
           no  -> no_data
           yes -> bounded UTF-8 + header?
                    invalid -> repair_required
                    v2      -> parse all -> current / repair_required
                    v1      -> canonical parse
                                 no manifest -> legacy_needs_metadata
                                 exact valid manifest -> legacy_ready
                                 incomplete/invalid -> legacy_needs_metadata
```

`readiness(manifest=None)` 不获取写锁、不创建目录或 lock file、不写审计文件。它只读取现有安全 regular file；传入 manifest 时只验证结构和 key 集，不修改记录。路径异常被映射为 `unsafe/storage_path`，Unicode、大小或格式异常映射为 `repair_required/<fixed-code>`。

## 6. 写入、纠错、删除与复核

普通 project `apply` 在锁内重读当前文件：

- none：创建 v2。
- v1：返回 `rejected/migration_required`，磁盘和 manager 快照不变。
- v2：合并或替换 record，宿主重新生成治理 metadata 和 revision。
- invalid/unsafe：返回固定 persistence error。

受控方法共享同一个锁内 read-modify-write helper：

```python
correct_project(candidate, governance, *, task_id=None)
delete_project(key, *, task_id=None)
revalidate_project(key, *, review_after, expires_at, truth_source, task_id=None)
```

这些方法只接受 v2。成功后重新解析刚写入文件，再更新 manager 快照。任何修改都会生成新 revision，但保留 header 中的 migration id 和 migration revision，以便 rollback 检测“迁移后已发生变化”。

## 7. 迁移事务

`migrate_legacy(manifest)` 的锁内顺序固定：

1. 安全重读 MEMORY.md 原始 bytes，验证大小、UTF-8、canonical v1 和 manifest exact key set。
2. 生成 migration id/revision，构造全部 v2 records；未知 truth source 强制 review due。
3. 验证待写 v2 的 storage/render 上限和完整 round-trip。
4. 安全创建 `.forgeagent/memory-backups/`：拒绝已有 symlink/非目录，权限收紧为 `0700`。
5. 用 `O_CREAT|O_EXCL|O_NOFOLLOW` 创建 `<migration-id>.memory-v1.bak`，权限 `0600`，写入原 bytes、flush、fsync。
6. 使用现有 temp + fsync + replace 原子写入 v2。
7. 从磁盘重读，运行语义 verifier；通过后更新 manager 并审计 `memory.migrated`。

若第 6 步前失败，原文件未改变。第 6 步后验证失败时，用备份 bytes 再走原子写入恢复 v1，并重新读取确认字节相等和 canonical parse 成功。恢复成功返回固定 migration failure；恢复无法确认返回 `recovery_failed`，保留备份且不更新内存快照为成功状态。

备份创建成功后不自动删除。M42 不定义保留周期，因为仓库当前没有真实历史数据，缺少可验证的清理策略。

## 8. Verify 与 rollback

`verify_project()` 对当前文件运行与写后 verifier 相同的安全解析和治理校验；它不需要 backup，也不改变文件。

`rollback_migration(migration_id)`：

1. 验证 id 只含 32 位小写 hex，并安全解析固定备份路径。
2. 获取项目锁并重读当前 v2。
3. 要求 header migration id 匹配，且 `revision == migration_revision`。
4. 安全读取 regular、非 symlink、`0600`、bounded backup，先验证为 canonical v1。
5. 原子恢复 backup bytes，重新读取并验证。

若 revision 已变化，返回 `rollback_conflict`；不存在 force 参数。若恢复后的验证无法确认，返回 `recovery_failed`，不得宣称 rolled back。

## 9. 文件安全与审计

- 所有 MEMORY、lock、backup 路径从 resolved allowed root 派生，不接受调用方拼接的文件路径。
- 所有现有 path 必须是位于 root 内的 regular file/directory；symlink 一律拒绝。
- 临时文件和备份文件显式 `fchmod(0o600)`；备份目录显式 `chmod(0o700)`。
- 公开 exception 只映射固定 reason。底层异常只用于控制流，不拼接到 diagnostic、CLI JSON 或 AuditEvent。
- migration id/revision 是随机 opaque 值；不用内容 hash，避免对短正文做离线猜测。
- `readiness` 保持只读，不写 audit event。状态变更与失败使用实现中的固定事件名：`memory.migrated`、`memory.verified`、`memory.rolled_back`、`memory.rollback_conflict`、`memory.rejected`、`memory.persistence_error`、`memory.recovery_failed`、`memory.expired`、`memory.review_due`、`memory.deleted`、`memory.revalidated`。所有事件在 `_audit` 边界重新投影 key；若 key 在写入后才进入敏感集合，公开审计中的 key 仍为空。

## 10. 离线运维入口

新增项目脚本 `scripts/m42_memory_migration.py`，只接受：

- `readiness --root <project-root> [--manifest <project-relative-json>]`
- `migrate --root <project-root> --manifest <project-relative-json>`
- `verify --root <project-root>`
- `rollback --root <project-root> --migration-id <opaque-id>`

manifest 必须是 root 内的 safe regular JSON file；输出为单行 JSON，只序列化公开结果 dataclass。脚本不读取环境凭据、不访问网络、不搜索其他目录。当前仓库的验收只运行 readiness，预期 `no_data`；不执行 migrate。

## 11. TDD 与验证矩阵

### 单元测试

- v2 deterministic round-trip、未知字段、重复 key、孤立 metadata、invalid timestamp。
- readiness 对 no-data/v1/v2/malformed/oversize/symlink 的状态和零写入。
- 三种 write source 的 metadata，证明模型正文不能覆盖。
- injected clock 下 active/expired/review-due/unknown truth 的投影。
- correct/delete/revalidate revision 变化和其他 key 保持。

### 迁移故障测试

- manifest exact key set、unknown legacy truth 待复核。
- backup directory/file symlink、权限和不可覆盖。
- backup 写入失败、v2 replace 失败、写后 parse 失败、自动恢复失败。
- 成功迁移的 key/content 语义等价和 opaque result。
- rollback 成功、revision 冲突、错误 id、缺失/不安全 backup。

### 集成与回归

- Task 写入得到 `model_candidate` metadata。
- `/remember` 写入得到 `user_command` metadata。
- v1 在 Task/CLI 中仍加载，但新 project write 返回 `migration_required`。
- session Memory、`--no-memory`、HTTP task 隔离和既有 golden replay 不回归。
- readiness CLI 输出不含 fixture 正文、secret、absolute root 或 injected exception。

### 完成门禁

Memory 专项和相关集成通过后，运行全量 pytest、Ruff check、Ruff format check、OpenSpec strict、Comet verify 与 `git diff --check`。最后重新搜索公开结果、日志和报告，确认没有正文、secret、完整 manifest 或绝对路径泄漏。

## 12. Rollout 决策

M42 首先在当前仓库运行 readiness。若为 `no_data`，记录 `migration_skipped` 并只启用新 v2 写入；这是预期成功路径。只有未来某个项目返回 `legacy_needs_metadata`，且操作者能够提供完整 manifest，才执行 migrate。`repair_required`、`unsafe` 或 manifest 不完整均停止迁移，不自动修复、不猜测、不扩大目录范围。
