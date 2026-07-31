# 里程碑 M42: Memory 元数据迁移

- 状态: 已完成
- 起止: 2026-07-31 ~ 2026-07-31
- 对应 ACTION_PLAN 行: M42（见该文件 §四里程碑表）
- 前置里程碑: [milestone_041](milestone_041.md)
- 分发边界: 包索引发布、tag、push 和发布自动化不在当前目标中

## 目标与范围

盘点现有长期 Memory 的真实状态，为每条持久化项目 Memory 建立宿主拥有的来源、写入者、
可见性、失效/复核、恢复和删除/纠错元数据；提供只读 readiness、显式 v1→v2 迁移、私有恢复
副本、写后 verifier 和冲突安全 rollback。先以真实数据决定是否迁移，不制造历史数据，不引入
数据库、向量检索、网络服务或新依赖。

## 方案设计

- 模型继续只能提交 `scope/kind/key/content` 候选；治理字段由受信宿主入口生成并校验。
- v2 采用单文件、单锁和原子替换，保留人类可读正文；旧 v1 只读兼容，普通写入返回
  `migration_required`，只有精确 manifest 可触发显式迁移。
- 迁移前创建 `0700` 目录中的不可覆盖 `0600` 恢复副本；写后验证失败自动恢复，rollback 绑定
  migration revision 且没有 force。
- 到期、待复核或 truth source unknown 的记录不进入 prompt；纠错、删除和复核均走宿主控制的
  read-modify-write 路径。
- 公开结果、渲染和审计只使用固定 reason 与动态 secret 投影，不暴露正文、manifest、绝对路径、
  raw exception 或写入后才进入敏感集合的 key。
- 技术设计、实施计划和运维手册分别见
  `docs/superpowers/specs/2026-07-31-memory-metadata-migration-design.md`、
  `docs/superpowers/plans/2026-07-31-memory-metadata-migration.md` 与 `docs/memory-migration.md`。

## 子任务清单

- [x] 盘点 Memory 文件与真实使用场景，确认当前仓库为 `no_data`。
- [x] 定义 v2 宿主治理元数据、生命周期和 v1 只读兼容契约。
- [x] 实现 readiness、显式迁移、恢复副本、verifier 与 revision 绑定 rollback。
- [x] 实现受控纠错、删除、复核和公开面最小披露。
- [x] 完成两轮自审、独立代码审查及所有发现项修复。
- [x] 完成 full verify、主规格同步和 Comet change 归档。

## 交付物清单

- [x] `src/forgeagent/memory.py`：v2 metadata、生命周期、迁移、验证、恢复与回滚。
- [x] `scripts/m42_memory_migration.py`：离线 readiness/migrate/verify/rollback 入口。
- [x] `tests/test_memory.py`、`tests/test_memory_migration.py`、`tests/test_memory_source_integration.py`：
  治理、边界、故障与来源集成回归。
- [x] `tests/test_m42_memory_migration_script.py`、`tests/test_memory_migration_docs.py`：离线入口与文档契约。
- [x] `docs/memory-migration.md`：迁移准备、备份、回滚和运维边界。
- [x] `docs/superpowers/reports/2026-07-31-memory-metadata-migration-verify.md`：完整验证证据。
- [x] `openspec/changes/archive/2026-07-31-migrate-memory-metadata/`：已归档需求、设计和任务账本。

## 三次评审

### 技术方案评审

- [x] 治理元数据由宿主拥有，未扩大模型权限或改变 `MemoryCandidate` 提交协议。
- [x] 旧 v1 保持只读兼容；显式迁移、恢复和 rollback 均有失败收敛与无条件重放禁令。
- [x] readiness 先于迁移；真实结果为 `memory_absent/no_data`，因此没有制造或迁移虚构数据。
- [x] 未引入数据库、向量检索、后台调度、新依赖或分发目标。

### 代码评审

- [x] 两轮自审覆盖权限、TOCTOU、symlink、manifest 等值、时钟回拨、stale manager 和公开面。
- [x] 独立 reviewer 发现的来源改写、非法时间、unknown 时钟回拨、动态 secret key、文档链接和
  审计事件表问题均已补 RED/GREEN 回归并修复。
- [x] 迁移验证比较完整 metadata；非法/secret key、正文、路径、manifest 和 raw exception 不进入
  公开结果或审计。

### 验收评审

- [x] Memory 专项 `89 passed`；最终全量 `2635 passed, 10 skipped in 176.70s`。
- [x] Ruff check、139 文件 format check、`git diff --check` 与真实 readiness 通过。
- [x] OpenSpec strict 归档前 `33/33`、归档后 `32/32`；Comet full verify 与 archive `7/7` 通过。
- [x] `.forgeagent` 没有 Memory 或 backup 文件；未执行 package build、PyPI、tag、push 或发布自动化。

## 遗留问题

M42 无未完成任务。备份保留周期、语义检索/排序和跨设备同步没有真实长期数据或可复现需求，
不在本里程碑实现；它们是条件候选，不是已承诺任务。

## 续接指引

读取本文件、`ACTION_PLAN.md` 与 `docs/memory-migration.md`。若未来出现真实 v1 数据，先运行只读
readiness，人工准备与 key 集完全一致的 manifest，再显式 migrate/verify；不得自动推断来源、
写入者或 truth source。新的 Rewrite/依赖变更和 HTTP 远程动作审批绑定仍须按触发条件独立立项。
继续保持分发目标移除，不执行包索引上传、tag、push 或发布自动化。
