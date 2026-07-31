# 里程碑 M33: 借鉴清单与任务开发流程规划基线闭环

- 状态: 已完成
- 起止: 2026-07-30 ~ 2026-07-30
- 对应 ACTION_PLAN 行: M33（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_032](milestone_032.md)
- OpenSpec change: [align-borrowing-roadmap-baseline](../openspec/changes/archive/2026-07-30-align-borrowing-roadmap-baseline/)

## 目标与范围

M33 只收敛规划事实，不增加运行时能力：

- 将归档 `external-action-receipts` 与 M29-M32 映射回综合借鉴清单和 `ACTION_PLAN.md`；
- 明确五项借鉴候选已完成，运行时 Skill 自动拒绝、既有 Memory 元数据迁移和新的 Rewrite/依赖
  仍需真实需求后独立立项；
- 将 `openspec/specs/external-action-receipts/spec.md` 的 `Purpose: TBD` 改为实现边界；
- 不建立外部分发目标；原 `publish-v0-1-0` 后续已撤销并归档。

## 方案设计

- 规划来源为综合借鉴清单，实际完成状态以 `ACTION_PLAN.md`、里程碑和归档 change 为证据；
- 归档收据能力只覆盖已批准的非只读 MCP 动作，不扩展到远程 API、消息、支付、FileWrite、Exec、
  Edit 或 WebFetch；
- M33 不修改源码、公开 API、持久化 schema、依赖或发布流程；文档契约测试保持离线、确定性、
  不启动模型/MCP。

## 子任务清单

- [x] 更新借鉴清单 frontmatter、完成状态映射和候选边界。
- [x] 更新综合借鉴清单、`ACTION_PLAN.md`、M32 续接说明和归档收据规格 Purpose。
- [x] 增加规划基线离线契约测试。
- [x] 完成专项、全量、Ruff、格式、diff 和 OpenSpec strict 验证。

## 交付物清单

- [x] `docs/reviews/2026-07-30-agent开发指南评审-借鉴清单.md` — 真实完成状态与后续边界。
- [x] `docs/reviews/2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md` — 候选映射与流程入口。
- [x] `openspec/specs/external-action-receipts/spec.md` — Purpose 澄清。
- [x] `tests/test_borrowing_roadmap.py` — 离线规划契约。
- [x] `ACTION_PLAN.md`、`milestones/milestone_032.md`、`milestones/milestone_033.md`、`milestones/latest`。

## 三次评审

### 技术方案评审

- [x] 第一轮自评确认不重复实现已归档的外部动作收据、M29-M32 或任何运行时能力。
- [x] 第二轮自评发现并修正收据候选仍写成“真缺口”、M28 基线过期和 `Purpose: TBD` 漂移。
- [x] 确认 M33 只做规划基线闭环，不把候选清单变成下一项运行时承诺。

### 代码评审

- [x] 本 M33 无运行时代码改动；逐文件复核文档映射、链接、release freeze 和 active change 未变。
- [x] 规划契约测试只读本地文件，不访问网络、不启动 MCP、不调用模型、不执行发布。

### 验收评审

- [x] 规划专项测试通过。
- [x] 完整 pytest、Ruff、format、diff check 和 OpenSpec strict 通过。
- [x] 原 `publish-v0-1-0` 已撤销归档；未执行外部分发，不创建公开发布证据。

## 遗留问题

- [ ] 运行时 Skill 自动拒绝 — 影响：治理门禁目前不自动阻止缺少退出条件的运行时内容 — 计划：真实需求出现后另立 full change。
- [ ] 既有 Memory 元数据迁移 — 影响：历史 `MEMORY.md` 保持旧格式 — 计划：明确迁移来源、回滚和 verifier 后另立 change。
- [ ] 新 Rewrite/依赖 — 影响：当前没有量化重写需求 — 计划：触发后按六项指标门禁另立 change。

## 续接指引

M33 已完成规划基线闭环。下一会话继续读取 `milestones/latest` 和 `ACTION_PLAN.md`；当前没有已授权
的下一运行时 change。若出现真实需求，优先按 `docs/agent-governance-gates.md` 建立问题卡和独立
Comet change；外部分发不在当前路线图，原 `publish-v0-1-0` 已撤销归档。
