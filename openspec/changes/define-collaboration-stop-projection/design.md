## Context

Task 已提供稳定 `reason` 与可选 `attention`，Loop 也有独立的预算、等待输入、阻塞和失败原因；CollaborationRunner 却只识别少数不可恢复错误，其余非完成结果大多变成 `role_failed`。此外，`state.goal` 是角色实际执行输入，`HandoffPacket.goal` 是跨边界公开投影，二者用途不同但目前没有显式命名其信任边界。

本 change 必须保持既有 Collaboration JSON 兼容、M27 路由迁移兼容、结构化 Submit 门禁和公开审计安全边界，不引入新的调度器、异常正文或发布动作。

## Goals / Non-Goals

**Goals：**

- 让 Task/Loop 的停止信号稳定映射为 Collaboration 的正常停止、资源耗尽、需要输入、阻塞、取消或失败。
- 公开报告以附加式 attention 表达恢复责任，同时保留既有 status/reason。
- 保留内部执行 goal 的合法路径，公开 handoff/report/audit 继续去除绝对路径、secret 和原始 prompt 正文。
- 用单一确定性函数承载映射，便于单元测试和后续调用方复用。

**Non-Goals：**

- 不让 CollaborationRunner 直接运行或嵌套 LoopRunner。
- 不修改 Loop handoff 自由文本结构；该议题留给独立 change。
- 不改变 Duo 验收计划；该议题由 M39 第三个 change 处理。
- 不新增依赖、HTTP endpoint、发布自动化、tag、push 或 PyPI 工作。

## Decisions

1. **保留原始稳定原因，按终态分组。** 投影函数返回 `(status, stop_reason, attention)`。`needs_info -> stopped/needs_input`，`blocked -> stopped/blocked`，资源上限保留其原 reason 并归入 stopped，`cancelled` 归入 cancelled，auth/invalid-request 和协议/状态错误归入 failed。把资源原因统一改名为 `resource_exhausted` 会丢失调用方所需诊断，因此不采用。

2. **Task 与 Loop 使用同一输入词表，但不制造不存在的嵌套。** 当前角色返回 `TaskOutcome`，因此 Runner 直接使用 Task reason；同时提供并测试 Loop 原因投影表，供外层或后续适配复用。LoopRunner 仍负责自己的预算，CollaborationRunner 不复制计时器和 token 预算逻辑。

3. **attention 为兼容的公开附加字段。** CollaborationState/Report 增加可选 `Attention`。只有 `needs_input` 和 `blocked` 停止持久化对应 attention；预算停止与普通终态由公开 HTTP 层根据稳定 reason 派生 ready，不把它们误报为等待外部动作。

4. **执行输入与公开投影分离。** `_role_task_data` 和 `_planner_task_data` 的 `goal` 继续取 `state.goal`，保证 `/data/input.csv` 等合法路径可执行；`build_handoff_packet` 明确通过公开 goal helper 构造 `HandoffPacket.goal`。审计只记录 digest、枚举和计数，不记录两个 goal 视图正文。

5. **失败关闭且不泄漏。** 未知 Task/Loop reason 归为 `failed/role_failed`，不把任意字符串加入公开 stop reason。异常处理继续只记录固定事件和异常类型，不记录 message、路径、secret 或 goal。

## Risks / Trade-offs

- [风险] 新 stop reason 使旧严格枚举校验失败。→ 扩展 CollaborationState 的固定允许集合，并增加旧 JSON 与 HTTP 回归测试；不删除旧原因。
- [风险] attention 与 status/reason 漂移。→ 在模型 validator 中约束 needs_input/blocked 必须携带匹配 attention，其他终态不得持久化待处理 attention。
- [风险] handoff task data 同时出现原始 goal 和脱敏 goal。→ 这是有意的信任边界：前者只供内部角色执行，后者是模型间公开摘要；审计测试禁止记录任一正文。
- [风险] 过度扩展为通用状态机。→ 只实现静态映射常量和小型纯函数，不新增配置或注册机制。

## Migration Plan

旧 Collaboration snapshot 没有 attention 时继续加载；已有 stop reason 保持有效。新增原因只在对应 Task/Loop 信号出现时写入。回滚时可移除新增字段和映射，不需要磁盘数据重写。

## Open Questions

无。M39 已授权在两轮自评后采用推荐方案。
