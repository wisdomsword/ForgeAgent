# 里程碑 M46: 文档入口与知识库整理

- 状态: 已完成并归档
- 起止: 2026-08-01 ~ 2026-08-01
- 对应 ACTION_PLAN 行: M46（见该文件 §四里程碑表）
- 前置里程碑: [milestone_045](milestone_045.md)
- OpenSpec change: [organize-documentation-index](../openspec/changes/archive/2026-08-01-organize-documentation-index/)

## 目标与范围

建立一个可维护的文档入口，归纳当前权威契约、开发流程、里程碑证据、评审治理、运行时参考和历史资料；用离线测试固定本地链接、`milestones/latest`、当前 latest 完成状态及发布/外部 HTTP 边界。历史文档只分类和链接，不整体搬迁、删除或改写；不改变运行时、CLI、HTTP、Memory、Rewrite、依赖或发布行为。

## 方案设计

- `docs/README.md` 是导航入口，不复制第二份路线图；当前状态仍以 `spec.md`、`ACTION_PLAN.md` 和 `milestones/latest` 为准。
- 索引测试只解析自身的本地 Markdown 链接和选定当前指针，不遍历所有历史资料、不联网、不读取凭据、不执行发布命令。
- M46 当前基线同步到 `docs/platform-support.md` 的单一汇总行；历史平台运行段落保持原始证据和限制。
- Memory、Rewrite/Dependency 和 HTTP 仍分别是条件触发、`keep_python`、`loopback-only`；PyPI、正式 tag 和发布自动化仍不在当前路线图。

## 子任务清单

- [x] 创建 `documentation-index-integrity` OpenSpec delta、proposal、design 和 tasks。
- [x] 新增离线文档索引契约测试，覆盖分区、链接、latest、完成状态和边界。
- [x] 新增 `docs/README.md`，分类并链接当前、证据和历史文档。
- [x] 更新根 `README.md`、`ACTION_PLAN.md` 和当前平台汇总入口，不改写历史证据。
- [x] 完成全量验证、两轮自评、独立评审和归档。

## 交付物清单

- [x] `docs/README.md` — 当前文档导航、分类和边界说明。
- [x] `tests/test_documentation_index.py` — 离线入口、链接和生命周期契约。
- [x] `docs/platform-support.md` — 当前 M46 基线汇总与既有历史平台证据分离。
- [x] `openspec/changes/archive/2026-08-01-organize-documentation-index/` — Comet tweak 生命周期工件。
- [x] `milestones/latest` — 验证完成后指向本里程碑。

## 三次评审

### 技术方案评审

- [x] 第一轮确认任务可收敛为单一文档治理 tweak，不需要 runtime、API 或依赖变更。
- [x] 第二轮确认不批量搬迁/改写历史证据，并把 M45 当前状态与条件触发边界放在索引中。
- [x] 最终复核：索引 latest 动态绑定，当前计数与平台矩阵一致，历史证据仍保持原语义。

### 代码评审

- [x] 已委派只读 reviewer 审查本里程碑 diff。
- [x] 发现问题已修复：latest 硬编码、当前测试计数和平台基线漂移均已修正。
- [x] 发现问题未处理：无 Critical/Important 遗留项。

### 验收评审

- [x] ACTION_PLAN M46 验证列全部满足 — 全量 `2739 passed, 10 skipped`、Ruff、format、`uv build`、diff check 通过。
- [x] ACTION_PLAN M46 门禁列全部满足 — 归档后 OpenSpec strict `36/36`，无运行时或发布边界变化。

## 遗留问题

- [x] 本仓库历史 Markdown 仍可能包含与当前基线不同的旧计数 — 影响：历史证据可读性；计划：以本入口和当前权威来源为准，不在本里程碑批量改写。

## 续接指引

M46 完成后，先读本文件和 `docs/README.md`。若用户提出新任务，先核对 `ACTION_PLAN.md` 与最新里程碑；只有真实 Memory 数据、Rewrite 六项指标越过阈值或跨主机 HTTP 需求出现时，才启动对应独立 change。HTTP 继续 loopback-only，未知外部动作不自动重放，PyPI/tag/发布自动化继续不在路线图。
