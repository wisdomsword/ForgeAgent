# Brainstorm Summary

- Change: migrate-memory-metadata
- Date: 2026-07-31

## 确认的技术方案

采用单文件 `MEMORY.md` v2：文件头保存随机 revision 和可选迁移标识，每条 Markdown 正文前紧邻一行宿主生成的 JSON metadata comment。`MemoryCandidate` 保持现有模型协议，不增加治理字段；Task 模型候选、用户 `/remember` 和内部 host API 由可信调用点传入固定 write source，`MemoryManager` 分别记录受控入口 `source` 与内容权威边界 `truth_source`，并生成、校验完整治理元数据。

旧 v1 只读兼容。readiness 不写盘并区分 `no_data`、`legacy_needs_metadata`、`legacy_ready`、`current`、`repair_required` 和 `unsafe`。普通 project 写入遇到 v1 时返回 `migration_required`。显式迁移要求逐 key 完整 manifest，在项目锁内重验，先创建 `0600` 私有恢复副本，再原子写 v2 并做语义 verifier。历史值允许显式标记 `unknown`，但未知 truth source 的记录迁移后立即待复核且不进入有效上下文，禁止从正文猜测。rollback 只允许当前 revision 仍等于迁移 revision 的情况，任何后续写入都触发 `rollback_conflict`。

过期或到复核期的记录保留在存储层供纠错、删除和复核，但不进入 `render()`。时钟可注入；没有日期条件时仍要求明确 `revalidate_on`。当前仓库无 `MEMORY.md`，只运行 readiness 并以 `no_data` 收尾，不制造历史数据。

## 关键取舍与风险

- 选择单文件而非 sidecar，保持原子提交；选择 Markdown v2 而非 JSON 主存储，保留既有路径和人工可读性。
- v1 写入被拒绝是有意的兼容收紧，防止继续产生无元数据记录。
- 公开 readiness/migration/verify/rollback 结果只含固定状态、计数和 opaque id，不含正文、secret、路径、manifest 或 raw exception。
- 备份目录和文件必须在项目边界内、regular-file、symlink-safe，权限分别收紧；备份名称不含 key/content。
- 底层持续 I/O 失败时不能承诺恢复必成；返回 `recovery_failed` 并保留备份，不把未知状态包装成成功。
- 不新增依赖、数据库、向量检索、远程同步、后台 TTL 或 LLM 元数据推断。

## 测试策略

按 TDD 覆盖 v1/v2 parser、readiness 最小披露、host-owned source、生命周期时钟、并发 read-modify-write、manifest 完整性、备份权限和 symlink、各故障注入点、写后自动恢复、`recovery_failed`、revision 冲突 rollback、Task/CLI source 集成和当前仓库 `no_data` verifier。完成后运行 Memory 专项、相关集成、全量 pytest、Ruff、format、OpenSpec strict、Comet verify 和 `git diff --check`。

## Spec Patch

已修正“任一步失败必须恢复成功”的不可实现绝对表述：替换后验证失败必须尝试并验证恢复；若底层存储导致恢复无法确认，返回 `recovery_failed`、保留备份并视状态未知，不得报告成功。
