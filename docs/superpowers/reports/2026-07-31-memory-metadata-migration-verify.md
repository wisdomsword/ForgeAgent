# Memory 元数据迁移验证报告

- 变更：`migrate-memory-metadata`
- 里程碑：M42
- 日期：2026-07-31
- 验证模式：full
- 基线提交：`35fe8cce29cdb781fcfcd385c54791c7e1a10795`
- 归档：`openspec/changes/archive/2026-07-31-migrate-memory-metadata/`

## 结论

M42 已实现项目 Memory v2 的宿主治理元数据、只读 readiness、v1 显式迁移、私有恢复副本、
写后 verifier、生命周期过滤、受控纠错/删除/复核和 revision 绑定 rollback。当前仓库没有
`.forgeagent/MEMORY.md`，真实 readiness 为 `no_data`，因此没有制造历史数据，也没有执行迁移。

## Verification Report: migrate-memory-metadata

| Dimension | Status |
| --- | --- |
| Completeness | 16/16 build tasks；6/6 requirements、23/23 scenarios 有实现证据 |
| Correctness | readiness、迁移、恢复、回滚、生命周期和最小披露场景均有回归 |
| Coherence | v1 只读兼容；v2 单文件、单锁、宿主元数据；无新依赖 |

### Issues by Priority

- CRITICAL：无。
- WARNING：无未处理项。
- SUGGESTION：备份保留周期、跨设备同步、检索/排序需等真实长期数据和使用证据后独立立项。

最终判断：build 与 full verify 门禁通过；主规格已同步，Comet change 已归档。

## 范围与实现

- `MemoryCandidate` 继续只承载模型可提交的 scope/kind/key/content；治理字段由宿主生成。
- v2 记录保存 source、writer、truth source、可见性、时间、复核、恢复和纠错策略；解析与写入均受
  64 条、32 KiB active render、64 KiB storage 上限约束。
- source/writer 表示原始受控入口并在复核时保持不变；truth source 可由宿主复核更新。
- `truth_source=unknown` 无条件保持待复核，不因时钟回拨重新进入 prompt。
- v1 继续只读加载；普通 project 写入返回 `migration_required`，迁移必须提供精确 manifest。
- 迁移在项目锁内重读源文件，先创建 `0700` 目录下的不可覆盖 `0600` 副本，再原子写入并精确
  校验完整 metadata、key/content、migration id、revision 和大小边界。
- 写后验证失败自动恢复原 v1；恢复未确认返回 `recovery_failed`。rollback 没有 force，revision
  变化返回 `rollback_conflict`。
- readiness、verify 和迁移运维脚本只输出固定状态；非法或 secret key、正文、manifest、绝对路径
  和 raw exception 不进入公开结果或审计。

## 验证证据

- M42/Task/CLI/Golden 聚焦：`426 passed in 6.10s`。
- 最终审查修复后全量：`2635 passed, 10 skipped in 176.70s`。
- 动态敏感 key 回归：session render、project render、lifecycle audit 共 `3 passed`；Memory 专项
  `89 passed`。
- 敏感公开面：`13 passed, 74 deselected`；静态敏感表达式搜索无命中。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：`139 files already formatted`。
- `openspec validate --all --strict --no-interactive`：归档前 `33 passed, 0 failed`，归档后
  `32 passed, 0 failed`。
- `git diff --check`：通过。
- 真实 readiness：`{"entry_count":0,"format_version":"none","reason":"memory_absent","status":"no_data"}`。
- `.forgeagent` 文件清单为空；没有 `MEMORY.md` 或 `memory-backups/`。

## 两轮自评与独立审查

- 第一轮逐 requirement/scenario 检查格式、来源、生命周期、迁移事务和恢复语义，修复 readiness
  辅助路径校验、active render 上限、时钟变化后的投影上限和文档兼容表述。
- 第二轮按权限、TOCTOU、symlink、故障注入、stale manager、clock rollback 和公开面检查，修复
  disabled/untrusted 运维门禁、完整 manifest metadata 等值验证、readiness manifest CLI、临时
  session 与 project verifier 的职责分离，以及 unknown truth 的永久待复核语义。
- 独立 reviewer 发现并验证 source/writer 被复核改写、非法/secret key 泄漏、悬空治理文档链接
  和运行手册旧三元组表述；续审又发现 unknown manifest 的非法复核时间可能在解析前被字符串
  比较覆盖，以及写入后才进入敏感集合的 key 仍可能进入渲染和生命周期审计。以上问题均以
  RED/GREEN 回归修复：时间收敛只比较已解析的 UTC datetime，渲染与审计在公开边界重新投影 key。

## 迁移决策与未执行动作

当前仓库为 `no_data`，结论是 `migration_skipped`。没有创建 manifest、Memory 文件或恢复副本；
没有访问网络、凭据或项目外数据。未执行包索引发布、package build、tag、push 或发布自动化。
用户已预授权本里程碑的非破坏性决策点；两轮自审后选择保留当前分支并确认归档，未执行合并或远程操作。

## 剩余边界

M42 不提供语义检索、排序、跨设备同步或自动备份清理。真实长期 Memory 出现并形成可复现的
检索/纠错/过期需求后，再以独立 change 定义指标和数据迁移；不得从本次 `no_data` 推断这些能力
已经得到生产数据验证。
