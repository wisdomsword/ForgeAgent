# 里程碑 M22: Triad Mode

- 状态: 已完成
- 起止: 2026-07-24 ~ 2026-07-25
- 对应 ACTION_PLAN 行: M22（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_021](milestone_021.md)
- 技术设计: [2026-07-24-triad-mode-design](../docs/superpowers/specs/2026-07-24-triad-mode-design.md)
- 验证报告: [2026-07-24-triad-mode-verify](../docs/superpowers/reports/2026-07-24-triad-mode-verify.md)
- 结构化提交验证报告: [2026-07-25-collaboration-role-submission-verify](../docs/superpowers/reports/2026-07-25-collaboration-role-submission-verify.md)
- OpenSpec change: [`2026-07-24-triad-mode`](../openspec/changes/archive/2026-07-24-triad-mode/)
- 归档后修复: [`2026-07-24-collaboration-contract-hotfix`](../openspec/changes/archive/2026-07-24-collaboration-contract-hotfix/)（Planner WHAT-only 双字段校验与协作审计闭环；全量 `2073 passed, 11 skipped`；归档前 strict `18/18`、归档后主规格 `17/17`）
- 结构化提交收尾: [`2026-07-25-fix-collaboration-role-protocol`](../openspec/changes/archive/2026-07-25-fix-collaboration-role-protocol/)（三角色 required Submit、零载荷 `SubmitCandidate`、attempt/verdict 原子恢复、跨进程 state CAS）；合并前复核补充了并发 Runner Submit 归属和 Store 首次初始化保护，最终 `2155 passed, 10 skipped`
- 合并前复审归档: [`2026-07-25-prevent-cross-runner-submit-claim`](../openspec/changes/archive/2026-07-25-prevent-cross-runner-submit-claim/)、[`2026-07-25-align-collaboration-submission-docs`](../openspec/changes/archive/2026-07-25-align-collaboration-submission-docs/)

## 目标与范围

在现有 `Task` 上方交付可持久化、严格串行的协作控制器：Duo 由独立 Generator 与
Evaluator 组成，只有 Evaluator 的逐项全通过 verdict 能决定完成；Triad 前置 Planner，
输出只描述 WHAT 的可观察验收清单，经用户或明确 headless policy 确认后冻结。提供
`run --mode`、REPL `/duo`/`/triad`、既有 HTTP `/tasks` 和 Loop 接入，以及编程任务的
确定性强制 Triad 路由。

本里程碑不修改普通 `TaskOutcome`。归档后收尾为 `Step` 增加默认关闭的通用 completion signal，
只有 registry 显式登记 required completion tool 时启用，因此 single/Loop single 仍保持原完成语义。
不引入角色并行、Agent SDK、workflow engine、数据库、新 endpoint、新 dependency、公共协作
resume API 或默认 Evaluator Exec 权限。

## 方案设计

- `collaboration.py` 统一承载严格 schema、冻结计划/verdict、原子 state store、角色专用
  registry、确定性路由和 Task-level runner，避免新增 manager/service/factory 层。
- Duo 的系统验收项与 Triad 确认计划使用相同逐项 verdict 合同；Generator 只有成功调用零载荷
  `SubmitCandidate` 才提交当前 attempt，普通 completion/prose 不能启动 Evaluator。reject evidence
  进入 fresh Generator，打回次数默认 2 且有上限。
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
- [x] 结构化提交收尾 reviewer 发现跨 Store revision CAS 只受实例内锁保护；新增 per-ID
  `flock` 和并发/失败关闭回归后复审确认无阻塞 findings

### 验收评审

- [x] Task 1-4 focused/regression 证据已记录，Task 4 regression 为 `584 passed, 10 skipped`。
- [x] 文档合同遵循 RED→GREEN；初始 RED 为 `5 failed, 1 passed`。
- [x] 完整 pytest `2069 passed, 11 skipped`；协作专项 `281 passed`；golden 20/20
- [x] Ruff format/check、wheel+sdist build、OpenSpec strict `17/17`、diff check 全部通过
- [x] OpenSpec 归档前完整验证通过；归档后运行 strict 验证与合并结果复验
- [x] 结构化提交及并发归属收尾完整 pytest `2155 passed, 10 skipped`，OpenSpec 主规格 `17/17`
- [x] 两次真实模型 Triad 均 completed：一次 7/7 直接通过，一次 8/8 经一次 reject 后修正通过

## 遗留问题

- [ ] 真实模型 single/Triad 对照质量评估未运行 — 已完成两次真实 Triad 协议验收，但没有与同任务 single 形成质量/成本对照，因此不能声称 Triad 相对 single 提升；保持 opt-in，按明确评估方案另行执行。
- [x] 默认 Evaluator 无 Exec 的缺口已部分收口 — P2/P3 change 增加可信宿主冻结的 `RunCheck` ID、当前 Python 固定入口、临时副本与 restricted audit hook（禁止副本外文件内容访问、目录枚举、路径变更，以及网络、spawn/fork/exec 和进程信号控制）、timeout/cancel 和有界脱敏输出；标准 CLI/HTTP 仍不接受检查定义，默认工具集不变。
- [ ] Duo/Triad 严格串行且多次 rejection 增加模型成本 — 影响：延迟和费用高于 single — 计划：保持显式 mode、角色模型选择与有界 rejection，不在 M22 引入并行。
- [ ] 协作取消仍是 cooperative — 影响：不能强杀在途 provider/tool 调用 — 计划：沿用安全边界停止，不伪造硬截止。

## 续接指引

M22 已完成，结构化提交门和真实 Triad 协议验收也已收尾。下一会话先读本文件与
`ACTION_PLAN.md`，不要凭聊天推断 M23 范围；先更新技术规划，明确下一里程碑目标、非目标、
验证和门禁，再通过 Comet 创建新 change。真实模型 single/Triad 对照仍是 opt-in 成本项，
不得把已通过的 Triad 协议验收表述为相对 single 的质量提升。
