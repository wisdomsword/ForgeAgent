# 里程碑 M22: Triad Mode

- 状态: 已完成
- 起止: 2026-07-24 ~ 2026-07-25
- 对应 ACTION_PLAN 行: M22（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_021](milestone_021.md)
- 技术设计: [2026-07-24-triad-mode-design](../docs/superpowers/specs/2026-07-24-triad-mode-design.md)
- 验证报告: [2026-07-24-triad-mode-verify](../docs/superpowers/reports/2026-07-24-triad-mode-verify.md)
- OpenSpec change: [`triad-mode`](../openspec/changes/triad-mode/)

## 目标与范围

在现有 `Task` 上方交付可持久化、严格串行的协作控制器：Duo 由独立 Generator 与
Evaluator 组成，只有 Evaluator 的逐项全通过 verdict 能决定完成；Triad 前置 Planner，
输出只描述 WHAT 的可观察验收清单，经用户或明确 headless policy 确认后冻结。提供
`run --mode`、REPL `/duo`/`/triad`、既有 HTTP `/tasks` 和 Loop 接入，以及编程任务的
确定性强制 Triad 路由。

本里程碑不修改普通 `Step`/`TaskOutcome`，不引入角色并行、Agent SDK、workflow engine、
数据库、新 endpoint、新 dependency、公共协作 resume API 或 Evaluator Exec 权限。

## 方案设计

- `collaboration.py` 统一承载严格 schema、冻结计划/verdict、原子 state store、角色专用
  registry、确定性路由和 Task-level runner，避免新增 manager/service/factory 层。
- Duo 的系统验收项与 Triad 确认计划使用相同逐项 verdict 合同；Generator clean completed
  只提交验收，reject evidence 进入 fresh Generator，打回次数默认 2 且有上限。
- Planner/Generator/Evaluator 各自拥有 fresh Task/client/runtime/registry。Evaluator 默认
  restricted，仅有 `FileRead`、`FileList`、`SubmitEvaluation`。
- HTTP 保持 submit/query/cancel endpoint 集合，通过 strict body mode 与 server-owned role、
  tier、confirmation、override policy 控制协作；Loop checkpoint 以加法字段冻结 mode/ID/digest。
- 公开报告、持久状态投影与审计使用稳定枚举、计数和有界掩码证据，不披露完整任务/计划/
  verdict、prompt、raw reply、tool args、artifact、credential 或绝对路径。

## 子任务清单

- [x] 实现严格协作模型、原子 store、结构化 role tools 与确定性编程路由
- [x] 实现 Duo 独立验收、证据打回、rejection limit、usage 与资源关闭
- [x] 实现 Triad Planner、WHAT-only guard、确认门与冻结计划完整性
- [x] 接入 CLI、REPL、HTTP、Loop 与审计，保持 ordinary/single 路径兼容
- [x] 补齐 README、文本协议、HTTP、威胁模型与文档静态合同
- [x] 完成全量门禁、全 diff 独立审查、两轮最终自审与缺陷修复
- [x] 本地 fast-forward 合并到主分支，并归档 OpenSpec change `2026-07-24-triad-mode`

## 交付物清单

- [x] `src/forgeagent/collaboration.py` — models/store/tools/router/runner
- [x] `src/forgeagent/cli.py` — CLI/REPL/HTTP owner 装配与安全报告
- [x] `src/forgeagent/http_config.py`、`http_server.py`、`http_task_service.py` — strict mode/policy/view
- [x] `src/forgeagent/loop.py` — collaborative checkpoint fields、runner 与 resume 一致性
- [x] `tests/test_collaboration_*.py` — models/store/tools/routing/Duo/Triad/integration/docs 合同
- [x] README、文本协议、HTTP 文档、威胁模型与验证报告草稿
- [x] 最终验证数字、review 结论与 archive commit — 见验证报告和最终归档提交

## 三次评审

### 技术方案评审

- [x] Task 1-4 按 OpenSpec、技术设计和 implementation plan 执行，未引入被排除的框架/依赖/endpoint。
- [x] 普通 single Task/Loop 与 M20 `evaluate` 保持原完成权；协作完成权仅在 Duo/Triad 交给 Evaluator。
- [x] 最终逐项核对 12 个 requirements / 43 个 scenarios 与实现、测试、文档证据一致

### 代码评审

- [x] Task 1 经多轮架构审查，最终 gate reviewer 通过；Task 1 suite `211 passed`。
- [x] Task 2-4 分别修复 1、3、3 个 Important 后由 reviewer 通过。
- [x] 完整 M22 diff reviewer 发现 1 个 Important；`111d60a` 修复后独立定向复审 APPROVED

### 验收评审

- [x] Task 1-4 focused/regression 证据已记录，Task 4 regression 为 `584 passed, 10 skipped`。
- [x] 文档合同遵循 RED→GREEN；初始 RED 为 `5 failed, 1 passed`。
- [x] 完整 pytest `2069 passed, 11 skipped`；协作专项 `281 passed`；golden 20/20
- [x] Ruff format/check、wheel+sdist build、OpenSpec strict `17/17`、diff check 全部通过
- [x] OpenSpec 归档前完整验证通过；归档后运行 strict 验证与合并结果复验

## 遗留问题

- [ ] 真实模型 single/Triad 质量对比未运行 — 影响：不能据 mock replay 声称真实判别质量提升 — 计划：保持 opt-in，具备 provider key 且接受费用时单独执行。
- [ ] v1 Evaluator 没有 Exec — 影响：不能自行执行测试命令，只能读取外部产物或预生成报告 — 计划：如需只读 executor，另立安全设计 change。
- [ ] Duo/Triad 严格串行且多次 rejection 增加模型成本 — 影响：延迟和费用高于 single — 计划：保持显式 mode、角色模型选择与有界 rejection，不在 M22 引入并行。
- [ ] 协作取消仍是 cooperative — 影响：不能强杀在途 provider/tool 调用 — 计划：沿用安全边界停止，不伪造硬截止。

## 续接指引

M22 已完成。下一会话先读本文件与 `ACTION_PLAN.md`，不要凭聊天推断 M23 范围；先更新技术
规划，明确下一里程碑目标、非目标、验证和门禁，再通过 Comet 创建新 change。真实模型
single/Triad 对比仍是 opt-in 成本项，不得把离线 mock 结果表述为真实质量提升。
