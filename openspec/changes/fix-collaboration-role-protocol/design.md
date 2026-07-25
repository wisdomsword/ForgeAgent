## Context

协作角色使用独立 Task 和 registry。现有 Runner 把 Generator 的普通 Task completion 直接视为
可进入 Evaluator，并要求 Planner/Evaluator 在 Submit 成功后再发送 standalone
`task_status`。真实模型证明这两种隐式边界都不稳定。CollaborationStore 已提供 revision CAS，
因此可以在不新增持久字段的情况下把结构化提交作为原子状态边界。

## Goals / Non-Goals

**Goals:**

- 只有成功的结构化 Submit 才能完成 Planner、Generator 或 Evaluator 角色。
- Generator 候选与当前 attempt 绑定，拒绝、恢复和 verdict 不跨候选复用。
- Evaluator 独占外部可观察验收；Generator 不承担宿主冻结检查。
- single、Loop single、公开报告、权限和 collaboration schema 保持兼容。

**Non-Goals:**

- 不新增 Candidate manifest、逐项 Generator 证据或宿主检查权限。
- 不引入动态工具锁、provider 原生 function calling、新依赖或新状态字段。
- 不推断崩溃前尚未持久化的 rounds/usage。

## Decisions

1. `SubmitCandidate` 使用空参数 `{}`。冻结 plan 与 allowed root 是 Evaluator 的权威输入。
2. `ToolOutcome` 增加默认关闭的通用成功终止信号；Submit 工具仅在 CAS 保存成功后置位。
3. Step 按 parser 的确定性输出顺序执行工具（文本 ToolCall 后接 provider 原生 tool_calls）。
   第一个成功终止工具完成任务并截断后续调用；先前工具和
   非致命解析错误不回滚已持久化提交。
4. ToolRegistry 显式登记至多一个 required completion tool。缺失 Submit 的 completion 声明
   获得一次恢复提示，重复违规稳定失败。
5. `SubmitCandidate` 原子执行 `phase=evaluator`、`generator_attempts+1`、清空旧 verdict。
   `SubmitEvaluation` 原子保存 verdict、`evaluator_attempts+1`，仍保持 evaluator phase。
6. Runner 对成功提交只补记 rounds/usage；失败角色仍在角色边界计数。Runner 独占 verdict
   判定、rejection limit 和终态转换。
7. 拒绝回到 Generator 时保留旧 verdict 供崩溃恢复重建反馈；下一 Candidate 提交时才清空。

## Rejected Alternatives

- 隐式根据文件或工具活动判断 Candidate ready：部分写入和 clean completion 无法可靠区分。
- Candidate 携带 artifact manifest 或逐项证据：信息非权威并模糊 Generator/Evaluator 职责。
- 给 Generator 宿主冻结检查权限：扩大权限和成本，且重复 Evaluator 工作。
- Submit 后等待 standalone completion 或动态锁写工具：增加轮次与恢复复杂度。
- 新增 Candidate/evaluation 关联字段：现有 phase、attempt、verdict 已足够表达状态。

## Risks / Trade-offs

- 通用成功终止信号会改变 Submit 工具的 Step 生命周期；通过默认 false 和 single 回归隔离风险。
- Submit 已保存而统计尚未保存时崩溃会丢失本轮 rounds/usage；选择不做不可靠推断。
- registry required completion tool 若误配多个会产生歧义；注册时 fail fast。
- 提交前工具失败后仍可能提交不完整候选；这是允许的，Evaluator 必须独立发现并拒绝。
