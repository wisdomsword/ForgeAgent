## MODIFIED Requirements

### Requirement: 协作模式使用隔离角色与串行编排
ForgeAgent SHALL 提供 `single`、`duo` 和 `triad` 三种运行模式。Duo MUST 按 Generator → Evaluator 串行执行；Triad MUST 按 Planner → 确认 → Generator ⇄ Evaluator 串行执行。每个角色 MUST 使用独立 Task、conversation、runtime、tool registry 与模型 client，不得共享另一角色的模型历史或可变执行状态。

#### Scenario: Duo 角色隔离
- **WHEN** 用户以 Duo 模式执行任务
- **THEN** Generator 与 Evaluator 分别创建独立 Task，Evaluator 只接收原始目标、冻结验收输入与允许根目录中的外部可观察产物

#### Scenario: Triad 严格串行
- **WHEN** 用户以 Triad 模式执行任务
- **THEN** Planner 完成且计划确认后才创建 Generator，Generator 提交后才创建 Evaluator，v1 不并行运行角色

#### Scenario: 单角色兼容
- **WHEN** 任务选择 single
- **THEN** 系统沿用既有单 Task 路径，不创建 Planner、Evaluator 或协作状态

### Requirement: 编程任务使用确定性路由且显式模式可审计
系统 MUST 在不调用额外模型或通用意图分类器的前提下确定协作模式。用户显式 `/single`、`/duo`、`/triad` 或 `--mode` MUST 直接生效；用户未显式选择且宿主为本次任务绑定非空冻结检查定义时 MUST 使用 Triad；其余任务，包括编程任务，MUST 默认使用 Single。候选文件就绪要求或任务文本分类不得单独触发自动 Triad。路由审计 MUST 记录稳定模式与原因，但不得记录目标、检查命令、路径或检查内容。

#### Scenario: 编程任务默认 Single
- **WHEN** 普通入口收到编程任务，用户未显式选择模式且宿主未绑定冻结检查
- **THEN** 系统选择 Single，不创建 Planner 或 Evaluator，也不为分类额外调用模型

#### Scenario: 宿主冻结检查触发 Triad
- **WHEN** 用户未显式选择模式且可信宿主为本次任务绑定至少一个冻结检查定义
- **THEN** 系统选择 Triad，并以不含检查内容的稳定原因记录该路由

#### Scenario: 显式模式直接生效
- **WHEN** 用户显式选择 Single、Duo 或 Triad
- **THEN** 系统直接使用该模式，不要求较弱模式覆盖确认，且显式选择优先于宿主证据默认值

#### Scenario: 候选文件要求不是完成证据
- **WHEN** 任务只配置候选文件就绪要求而没有冻结检查定义
- **THEN** 该配置不得触发自动 Triad
