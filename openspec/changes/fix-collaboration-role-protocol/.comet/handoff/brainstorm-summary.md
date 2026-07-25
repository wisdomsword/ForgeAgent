# Brainstorm Summary

- Change: fix-collaboration-role-protocol
- Date: 2026-07-25

## 已确认事实

- 用户选择将 hotfix 升级为完整 Comet design。
- 原始 Planner `invalid_role_submission` 来自角色提示未暴露 ToolCall 格式/schema；registry-aware recovery 后真实 Planner 能稳定提交计划。
- 多次真实 Triad 中 Generator 均正确生成产物，独立 pytest 分别为 9、19、12 passed，CLI 输出正确，但协作仍可能在 Generator clean submission 前耗尽。
- 真实 Generator 会尝试用 restricted Exec 验证刚由 FileWrite 写入的宿主文件；两者文件视图/执行边界不同，模型因此反复尝试 subprocess、绝对路径或内联验证。
- 一次诊断中 Generator 成功进入 Evaluator，但 Evaluator 未调用 SubmitEvaluation 就声明完成；提示不能替代确定性提交门。
- 当前实验性实现和测试仍未提交，仅作为设计输入保留。

## 确认的核心语义

- Generator 只负责实现并结构化提交候选；Evaluator 独占逐项验收责任。
- 引入 Generator 专用 `SubmitCandidate` 工具；Generator 成功调用后才能 clean completion，不要求它在 restricted Exec 中重复证明宿主文件。
- 用户已确认设计第 1 节“状态机与提交协议”。

## 状态与恢复约束

- 现有 `CollaborationStore.save(..., expected_revision=...)` 已提供原子持久化和乐观并发控制，可复用为候选提交边界。
- 已选复用现有状态：`SubmitCandidate` 原子递增 `generator_attempts` 并把 `phase` 从 `generator` 切到 `evaluator`，不新增 Candidate 字段或状态迁移。
- Evaluator 只在 `phase=evaluator` 时消费最近一次已提交候选；拒绝只把 phase 切回 `generator`，下一次提交必须再次递增 attempt。
- 拒绝后 `phase=generator` 时暂时保留旧 `last_evaluation`，使崩溃恢复仍能重建 Generator 的拒绝反馈；新一轮 `SubmitCandidate` 保存成功时将其清空。
- `phase=evaluator` 且 `last_evaluation` 为空表示当前候选待验收；非空表示当前候选已有持久化 verdict，恢复时不得重复要求模型提交。
- attempt 由成功提交工具同步计数：`SubmitCandidate` 的原子保存包含 `generator_attempts + 1`；`SubmitEvaluation` 的原子保存包含 `evaluator_attempts + 1`。
- 未成功提交而退出的角色仍由 Runner 在角色边界递增对应 attempt，保持现有失败计数语义；Runner 不得对已由 Submit 工具计数的成功角色重复递增。
- `SubmitEvaluation` 只保存当前 verdict、递增 attempt 并保持 `phase=evaluator`；Runner 继续独占 pass/reject、`rejections`、rejection limit 和终态转换。
- Generator 的普通任务完成状态不能隐式推进 phase；只有成功的 `SubmitCandidate` 才能使候选进入可评估状态。
- 已选统一终止语义：`SubmitPlan`、`SubmitCandidate`、`SubmitEvaluation` 保存成功即完成当前角色；不再要求独立 `task_status` completion。
- Step 必须在成功提交后停止分派同一响应中的后续工具，防止提交后继续修改候选；提交失败则照常反馈并允许重试。
- 状态保存与角色终止是连续的确定性边界，而非单一存储事务：只有保存成功的工具结果才能触发 Step completion。
- 同一响应按模型声明顺序执行：Submit 前的合法工具正常运行；第一个成功 Submit 立即终止角色并跳过后续调用。
- 同一响应中的其他非致命解析错误不回滚已持久化的成功提交；Evaluator 仍负责发现因前置工具失败而不完整的候选。
- Step 不读取 collaboration phase；Submit 工具在保存成功后返回通用的“成功终止任务”信号，保持执行层与协作状态解耦。
- Planner、Generator、Evaluator 声明 `task_status.completed=true` 但未成功调用对应 Submit 时，统一获得一次结构化恢复提示；下一轮成功提交即可完成。
- 同一角色第二次声明完成仍未提交时，Step 失败，Runner 映射为 `invalid_role_submission`；不得把 `task_status` 当作隐式提交。
- Submit 调用自身校验失败时返回具体工具反馈，并可在剩余轮次内修正；这与“绕过 Submit 的完成声明”分别处理。
- 缺失 Submit 的一次性恢复状态属于单个 Step/角色 attempt：Step 维护已发送恢复提示的工具集合；Runner 不维护模型轮次计数，只根据最终 TaskOutcome 映射 `invalid_role_submission`。
- 用户已确认设计第 2 节“Step 与工具层契约”。
- 用户已确认设计第 3 节“Runner 边界、失败映射与恢复”。
- `needs_confirmation` 是现有 `CollaborationPhase` 值和状态 invariant，不需要新增 schema 字段或枚举迁移。
- 用户已确认设计第 4 节“提示协议、测试矩阵与验收标准”。

## 最终设计结论

- 三个结构化 Submit 工具保存成功即通过通用 `ToolOutcome.completes_task` 完成角色；Step 按声明顺序执行并截断成功 Submit 后的调用。
- `ToolRegistry` 显式登记至多一个 required completion tool；Step 不硬编码协作角色、phase 或 Submit 工具名称。
- Generator 使用零载荷 `SubmitCandidate`，原子切换到 evaluator、递增 Generator attempt 并清空旧 verdict；Evaluator 独占验收。
- Runner 负责状态 invariant、统计边界、pass/reject、拒绝上限、恢复和稳定失败映射；不重复计算 Submit 已持久化的 attempt。
- 不新增依赖，不新增 collaboration state 字段，不迁移 `forgeagent.collaboration.v1` schema；single 行为保持不变。
- 验证包含 Step/工具/Runner/恢复/模式/安全回归、完整测试，以及两个全新临时目录中的连续真实模型 Triad 成功运行。

## 设计确认状态

- 四个分节均已由用户确认。
- 用户已整体批准设计，并授权编写正式 Design Doc、delta spec 与实施计划。

## SubmitCandidate 载荷决议

- 已选方案 1：零业务载荷，只提交持久化 ready 信号；冻结 plan 与 allowed root 是 Evaluator 的权威输入。
- 排除方案 2：artifact manifest 非权威，却增加路径、完整性和状态校验，并模糊 Generator/Evaluator 边界。
- 排除方案 3：逐项证据直接重复 Evaluator 的验收职责，并扩大模型格式失败面。

## 架构方向决议

- 已选 A：新增 Generator 专用结构化提交工具；成功调用后才允许 clean completion，验证责任归 Evaluator/宿主检查。
- 排除 B：运行时根据文件/工具活动隐式判断候选就绪，无法可靠区分部分写入、回滚和 clean completion。
- 排除 C：让 Generator 获得宿主冻结检查能力会扩大权限和成本，并与 Evaluator 的独占验收职责重复。

## 测试策略决议

- mock 覆盖三个角色成功 Submit 即终止、缺失 Submit 一次恢复、重复缺失稳定失败的确定性门。
- 真实模型覆盖 Planner 偏离恢复、Generator 正确产物提交、Evaluator verdict 提交和最终 completed。
- single、Duo、Triad、Loop 以及稳定失败原因回归必须保持兼容。

## Spec Patch

- 修改 `runtime-collaboration` requirement：Generator 必须成功调用 `SubmitCandidate` 才能 clean completion；普通任务完成状态不推进 phase。
- 候选状态绑定当前 Generator attempt；拒绝回退时保留旧 verdict 供恢复反馈，新一轮 `SubmitCandidate` 成功时清空。
- Evaluator 只消费当前 attempt 已提交的候选；未提交候选不得进入 evaluation。

## 兼容性边界

- `single` 不含 Evaluator，行为保持不变，不注册或要求 `SubmitCandidate`。
- `Duo` 和 `Triad` 都运行 Generator + Evaluator，因此二者统一采用候选提交门；Triad 仅额外包含 Planner/确认阶段。
- Loop 的 `single` 模式保持不变；Loop 的 `duo`/`triad` 模式继承对应协作语义，不另建一套 Candidate 状态机。
- Candidate 引入不得改变现有 plan freeze、rejection limit、loop checkpoint/budget 和终态判定契约。
