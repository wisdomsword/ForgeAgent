# ForgeAgent 文档入口

本页是当前文档的导航入口，不复制第二份路线图。当前状态以最高宪法、行动计划和最新里程碑为准；历史文件保留原路径，用于追溯当时的设计、验证和治理证据。本次入口整理记录见 [M46](../milestones/milestone_046.md)；最新里程碑见 [M52](../milestones/milestone_052.md)，交付标准 Skills SDK 兼容路径；M51 [安全与契约加固归档](../openspec/changes/archive/2026-08-12-split-runtime-boundaries/)；M50 外部工具文本恢复、M49 REPL 会话/反馈限额、M48 任务执行证据与 M47 生命周期加固记录继续作为历史证据保留。

## 当前权威入口

- [最高宪法：`spec.md`](../spec.md) — 项目使命、范围和不可违反的工程约束。
- [`ACTION_PLAN.md`](../ACTION_PLAN.md) — 当前里程碑计划、验证门禁和已裁决路线。
- [`MILESTONE_GUIDE.md`](../MILESTONE_GUIDE.md) — 里程碑收尾记录格式与续接规则。
- [`milestones/latest`](../milestones/latest) — 指向最新已完成里程碑文件；当前指针为 `milestone_052.md`。
- [Agent 治理门禁](agent-governance-gates.md) — Prompt/Skill、Memory、Rewrite/Dependency 和分发边界的 canonical 入口。

## 开发流程

- [行动计划](../ACTION_PLAN.md)：查看当前阶段、前置条件和验证要求。
- [里程碑规范](../MILESTONE_GUIDE.md)：新会话先读 `milestones/latest` 的“续接指引”。
- [`openspec/`](../openspec/)：查看当前或已归档的变更生命周期；没有 active change 不代表历史证据缺失。
- [文本协议](text-protocol-spec.md)、[威胁模型](threat-model.md)：了解运行时协议和安全边界。

## 里程碑与证据

- [最新里程碑](../milestones/milestone_052.md)：当前 latest 指针指向的 M52 标准 Skills SDK 兼容路径；native 严格格式、安全与信任摘要合同继续保留。M51 安全与契约加固见 [milestone_051](../milestones/milestone_051.md)。M50 外部工具文本恢复见 [milestone_050](../milestones/milestone_050.md)，M49 REPL 完整历史与复杂执行路由见 [milestone_049](../milestones/milestone_049.md)。
- [`milestones/`](../milestones/)：按 M 编号保存交付范围、验证输出、三次评审和续接指引。
- [`docs/superpowers/reports/`](superpowers/reports/)：Comet/Superpowers 验证报告；报告是当时执行的证据，不替代当前状态。
- [M47 环境依赖复验](superpowers/reports/2026-08-03-m47-environment-revalidation.md)：归档后补证，包含 Docker 隔离、跨 Python digest 和全量回归结果。
- [`docs/evaluation/`](evaluation/)：离线评估协议、原始运行记录和派生报告；结果只适用于各自记录的模型、平台和日期。

## 评审与治理

- [治理综合清单](reviews/2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md)：Prompt/Skill、Memory 和 Rewrite 的立项模板及条件触发规则。
- [治理借鉴清单](reviews/2026-07-30-agent开发指南评审-借鉴清单.md)：当前借鉴结论和基线标识。
- [M45 对账报告](reviews/2026-08-01-m45-m29-m38-artifact-reconciliation.md)：历史工件恢复、拒绝项和当前祖先链证据。
- [发布说明](releases/0.1.0.md)：正式发布门禁；当前不表示已发布。
- [第三方声明](../THIRD_PARTY_NOTICES.md)：第三方材料来源与许可说明；其余均为本项目原创。

## 运行时参考

- [Memory v2 与迁移](memory-migration.md)：Memory readiness、显式迁移、备份和回滚；当前仓库 readiness 为 `no_data`，不自动迁移历史数据。
- [HTTP 任务服务](http-task-service.md)：当前 HTTP 控制面保持 loopback-only；未知外部动作不自动重放。
- [平台支持](platform-support.md)：平台矩阵和 CI 证据边界。
- [模型客户端契约](model-client-contract.md)、[MCP/工具说明](m7-tools-mcp-survey.md)：运行时能力参考。

## 历史资料

- [`openspec/changes/archive/`](../openspec/changes/archive/)：已完成并归档的变更；归档状态是生命周期证据，不是当前待办。
- [`docs/reviews/`](reviews/)：历史评审和借鉴记录；若与当前入口冲突，以 `spec.md`、`ACTION_PLAN.md` 和 `milestones/latest` 为准。
- [`docs/evaluation/`](evaluation/)：历史评估原始数据和报告；不得把单次结果外推为产品承诺。
- [`docs/superpowers/plans/`](superpowers/plans/) 与 [`docs/superpowers/specs/`](superpowers/specs/)：历史设计/计划工件，按对应 change 的归档状态阅读。

## 当前边界

- Memory 只有在出现真实持久化数据时才触发独立迁移；当前 readiness 是 `no_data`。
- Rewrite/Dependency 只有在六项指标具备 baseline、threshold、evidence、migration 和 rollback trigger，且实际越过阈值时才进入试验；M43 的当前裁决仍是 `keep_python`。
- HTTP 仍为 `loopback-only`；不先开放公网入口，不引入完整 Gateway。
- PyPI、正式 tag 和发布自动化不在当前路线图；普通开发分支 push 只用于版本控制交接，不构成分发授权。
- 本索引只引用项目内文件，不包含宿主绝对路径或凭据；文档契约测试保持离线、无网络和 release-neutral。
