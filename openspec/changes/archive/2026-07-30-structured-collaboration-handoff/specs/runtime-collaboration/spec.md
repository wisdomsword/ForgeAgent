# runtime-collaboration Specification Delta

## MODIFIED Requirements

### Requirement: 协作模式使用隔离角色与串行编排
ForgeAgent SHALL 提供 `single`、`duo` 和 `triad` 三种运行模式。Duo MUST 按 Generator → Evaluator 串行执行；Triad MUST 按 Planner → 确认 → Generator ⇄ Evaluator 串行执行。每个角色 MUST 使用独立 Task、conversation、runtime、tool registry 与模型 client，不得共享另一角色的模型历史或可变执行状态。角色边界 MUST 传递由持久 state 和宿主能力投影生成的有界结构化 handoff；该 handoff 不得成为角色间共享可变执行状态。

#### Scenario: Duo 角色隔离
- **WHEN** 用户以 Duo 模式执行任务
- **THEN** Generator 与 Evaluator 分别创建独立 Task，Evaluator 只接收原始目标、冻结验收输入、允许根目录中的外部可观察产物和当前结构化 handoff

#### Scenario: Triad 严格串行
- **WHEN** 用户以 Triad 模式执行任务
- **THEN** Planner 完成且计划确认后才创建 Generator，Generator 提交后才创建 Evaluator，v1 不并行运行角色；每个边界都生成新的有界 handoff

#### Scenario: 单角色兼容
- **WHEN** 任务选择 single
- **THEN** 系统沿用既有单 Task 路径，不创建 Planner、Evaluator 或协作 handoff 状态
