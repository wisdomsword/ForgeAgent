# 里程碑 M32: Prompt、Memory 与重写治理门禁

- 状态: 已完成
- 起止: 2026-07-30 ~ 2026-07-30
- 对应 ACTION_PLAN 行: M32（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_031](milestone_031.md)
- 技术设计: [2026-07-30-prompt-memory-rewrite-governance-design](../docs/superpowers/specs/2026-07-30-prompt-memory-rewrite-governance-design.md)
- 实施计划: [2026-07-30-prompt-memory-rewrite-governance](../docs/superpowers/plans/2026-07-30-prompt-memory-rewrite-governance.md)
- OpenSpec change: [prompt-memory-rewrite-governance](../openspec/changes/archive/2026-07-30-prompt-memory-rewrite-governance/)

## 目标与范围

M32 将评审清单中的 P2 流程纪律落为可追溯、可回归的开发期门禁：

- 长期 Prompt/Skill：五类退出条件（`success`、`failure`、`blocked`、`needs-input`、`timeout-or-budget`）、condition/verifier、模型升级版本、最小回归集和过时 scaffolding 清理。
- 长期 Memory：核心四问（谁可写、什么是真相、何时失效、崩溃后哪份恢复）以及为什么记、谁可见、如何删除/更正两个安全字段。
- Rewrite/依赖：性能、可靠性、维护成本、兼容性、团队能力、迁移/回滚风险六项指标，每项提供 baseline、threshold、evidence、migration、rollback trigger。

本里程碑只新增治理文档和离线文档契约测试，不改变 Skill/Memory/Prompt 运行时格式，不迁移既有 `MEMORY.md`，不实现 stop-reason 运行时映射，也不执行 Rewrite 自动评分。

## 方案设计

- `docs/agent-governance-gates.md` 是 canonical 入口；`spec.md`、`MILESTONE_GUIDE.md`、综合借鉴清单和 threat model 只做可定位引用。
- 测试采用稳定 Markdown 表格行检查，确认每个退出/Memory/Rewrite 行字段成组存在；测试仅使用 `pathlib`/AST，不访问网络或发布工具。
- 兼容边界明确：旧 Skill、旧 Memory 和旧 Prompt 不自动迁移；运行时强制拒绝缺少退出条件的能力需另立 change。
- 综合借鉴清单的“stop-reason 映射与运行时边界测试”保留为后续独立候选，不在本 M32 宣称已完成。

## 子任务清单

- [x] 新增文档契约测试并完成 TDD 红-绿验证。
- [x] 新增 canonical 治理规范和 Prompt/Skill、Memory、Rewrite 模板。
- [x] 接入 `spec.md`、`MILESTONE_GUIDE.md`、综合借鉴清单和 threat model，补阶段级检查与范围边界。
- [x] 更新 `ACTION_PLAN.md` M32 台账行。
- [x] 完成专项、全量、Ruff、格式、diff 和 OpenSpec strict 验证。

## 交付物清单

- [x] `docs/agent-governance-gates.md` — canonical 治理门禁。
- [x] `tests/test_governance_docs.py` — 表格行级文档契约测试与离线/发布中立检查。
- [x] `spec.md`、`MILESTONE_GUIDE.md` — 宪法与阶段入口引用。
- [x] `ACTION_PLAN.md` — M32 规划与验收台账。
- [x] `docs/reviews/2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md` — 候选 5 范围和验收修订。
- [x] `docs/threat-model.md` — 开发期治理漂移风险。
- [x] OpenSpec proposal/design/spec/tasks、Superpowers Design Doc/Plan。

## 三次评审

### 技术方案评审

- [x] 第一轮自评否决运行时 schema、Memory 数据迁移、数据库和自动 Rewrite 评分器，选择 canonical 文档 + 静态契约测试。
- [x] 第二轮自评补齐写入权限、模型升级回归集、过时 scaffolding 清理、阶段级检查和 stop-reason 范围边界。
- [x] 明确运行时 stop-reason 映射、旧 Memory 迁移和 Skill 自动拒绝不属于本里程碑。

### 代码评审

- [x] 请求并完成一次指定文件只读评审。
- [x] 修复评审发现：Memory 漏写入者、候选验收与实际范围矛盾、测试字段成组不足、退出字段命名漂移、阶段检查声明过强、Prompt 升级回归集遗漏。
- [x] 修复后重新运行专项测试、OpenSpec strict 和全量回归。

### 验收评审

- [x] `uv run pytest tests/test_governance_docs.py -q`：`5 passed`。
- [x] `uv run pytest`：`2461 passed, 10 skipped`。
- [x] `uv run ruff check .`、`uv run ruff format --check .`、`git diff --check`：通过。
- [x] `openspec validate --all --strict --no-interactive`：`28 passed, 0 failed`。
- [x] 未执行外部分发；`publish-v0-1-0` 已撤销并归档。

## 遗留问题

- [ ] 运行时 stop-reason 映射和 Skill 自动拒绝 — 影响：当前仍是开发期治理，不自动阻止运行时内容 — 计划：若有真实需求，另立 full change，先定义迁移和 verifier 信任边界。
- [ ] 既有 Memory 未补元数据 — 影响：历史内容保持旧格式 — 计划：只有在用户明确需要运行时治理时另立迁移 change。
- [x] 正式外部分发目标已移除 — 影响：不产生公开上传证据 — 处理：保留 RC 历史记录，无恢复路径。

## 续接指引

M32 已完成治理门禁、验证和自评。下一阶段为 M33“借鉴清单与任务开发流程规划基线闭环”：只登记
已归档外部动作收据与 M29-M32 的映射，修正归档收据规格 Purpose，并保持发布冻结；不把候选清单
当作新的运行时执行令。

## M45 对账注记

- 本文件于 M45 从已验证历史工件恢复；原测试计数只对应当时快照，当前 HEAD 由 M45 全量门禁证明。
- 包索引发布、正式 tag 和发布自动化仍不在路线图；经用户授权的普通开发分支 push 仅用于版本控制交接。
- 当前基线以 `ACTION_PLAN.md` 和 `milestones/latest` 为准，本文件中的旧“续接指引”只保留历史语境。
