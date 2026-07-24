# runtime-collaboration Specification

## Purpose
定义隔离、串行的 Duo/Triad 运行时协作、冻结验收计划、独立评估与 single 模式兼容路由。
## Requirements
### Requirement: 协作模式使用隔离角色与串行编排
ForgeAgent SHALL 提供 `single`、`duo` 和 `triad` 三种运行模式。Duo MUST 按 Generator → Evaluator 串行执行；Triad MUST 按 Planner → 确认 → Generator ⇄ Evaluator 串行执行。每个角色 MUST 使用独立 Task、conversation、runtime、tool registry 与模型 client，不得共享另一角色的模型历史或可变执行状态。

#### Scenario: Duo 角色隔离
- **WHEN** 用户以 Duo 模式执行任务
- **THEN** Generator 与 Evaluator 分别创建独立 Task，Evaluator 只接收原始目标、冻结验收输入与允许根目录中的外部可观察产物

#### Scenario: Triad 严格串行
- **WHEN** 用户以 Triad 模式执行任务
- **THEN** Planner 完成且计划确认后才创建 Generator，Generator 提交后才创建 Evaluator，v1 不并行运行角色

#### Scenario: 单角色兼容
- **WHEN** 任务选择 single 且未命中强制 Triad 路由
- **THEN** 系统沿用既有单 Task 路径，不创建 Planner、Evaluator 或协作状态

### Requirement: Planner 生成冻结且不可降级的验收清单
Triad Planner MUST 只定义 WHAT：每个清单项包含稳定 ID、可观察行为与验收标准，不得指定实现步骤。系统 MUST 对 `behavior` 与 `acceptance` 两个字段同时执行 WHAT-only 校验。计划提交后系统 MUST 规范化并计算摘要；确认后的条目、顺序和标准 MUST 冻结，后续角色不得删除、替换、重排或降低标准。

#### Scenario: 合法计划确认
- **WHEN** Planner 提交非空、唯一 ID 且全部字段有界的计划，并由交互用户确认或由 headless 预授权策略接受
- **THEN** 系统冻结规范化计划和摘要并允许 Generator 开始

#### Scenario: Planner 在任一计划字段指定实现方法
- **WHEN** Planner 在 `behavior` 或 `acceptance` 中把工具调用、库选择或具体实现步骤当作验收内容
- **THEN** 系统通过结构化反馈要求其改写为外部可观察行为，不接受或冻结该版本计划

#### Scenario: 后续角色改变计划
- **WHEN** Generator、Evaluator、Loop resume 或打回轮次提供缺项、改项、重排或不同摘要的计划
- **THEN** 系统拒绝变更并保持已确认计划不变

### Requirement: Evaluator 独立验收并决定协作完成
在 Duo/Triad 模式中，Generator 的严格 `completed` SHALL 仅表示提交验收。Evaluator MUST 使用结构化逐项结果判定外部可观察产物；只有所有要求通过时协作结果才能为 completed。Evaluator 默认 MUST 使用 restricted tier，写工具 MUST 不可用，且其模型和 tier MAY 与 Generator 独立配置但不得扩大服务端或 CLI 所有者授予的权限。

#### Scenario: Generator 错误完成被拦截
- **WHEN** Generator 声明完成但 Evaluator 发现至少一项外部可观察行为不满足
- **THEN** 协作结果保持未完成并生成有界、脱敏的实际行为、期望行为和定位证据

#### Scenario: 全部验收通过
- **WHEN** Evaluator 对冻结计划或 Duo 验收目标的全部项目返回 pass
- **THEN** 系统返回 completed，并保留 Generator 与 Evaluator 的轮次、usage 和验收计数投影

#### Scenario: Evaluator 无写权限
- **WHEN** Evaluator 尝试修改被验收产物
- **THEN** 请求被工具注册表、确认门或 sandbox 拒绝，且该尝试不能形成 pass

### Requirement: 打回环有界且证据驱动
Evaluator 失败 SHALL 把有界、脱敏、逐项证据返回新的 Generator Task；每次修正 MUST 使用新的 Generator conversation，并保留原始目标与冻结计划。系统 MUST 支持可配置的最大打回次数，默认 2；达到上限、取消、角色失败或预算不足时 MUST 以稳定原因停止，不得无限重试。

#### Scenario: 一次打回后修复通过
- **WHEN** 首次 Evaluator 拒绝且下一 Generator 根据证据修复产物，随后 Evaluator 全部通过
- **THEN** 系统返回 completed，并报告一次 rejection 和两次 evaluation attempt

#### Scenario: 打回次数耗尽
- **WHEN** Evaluator 连续拒绝达到最大打回次数后仍有未通过项目
- **THEN** 系统以 `rejection_limit` 停止，返回逐项有界报告且不再调用 Generator

#### Scenario: 角色调用失败或取消
- **WHEN** 任一角色返回鉴权错误、不可恢复失败或收到协作取消
- **THEN** 系统在下一安全边界停止，以稳定角色和原因标识终态，并关闭已创建资源

### Requirement: 编程任务使用确定性路由且显式模式可审计
系统 MUST 使用有界、表驱动的产物类型与动作规则识别直接要求创建或修改代码、测试、构建配置或软件项目的任务，并将其路由到 Triad。用户显式 `/duo`、`/triad` 或 `--mode` MUST 被识别；显式 single 与强制 Triad 冲突时 MUST 提示确认，headless 无确认且无预授权时 MUST 拒绝。该规则不得调用额外模型或充当通用意图路由器。

#### Scenario: 编程任务强制 Triad
- **WHEN** 普通入口收到确定性规则明确识别的编程任务且用户未显式选择更强模式
- **THEN** 系统选择 Triad 并在 Planner 确认后执行

#### Scenario: 非编程任务默认 single
- **WHEN** 任务不匹配编程规则且用户未显式选择 Duo/Triad
- **THEN** 系统保持 single，不为分类额外调用模型

#### Scenario: 显式 single 冲突
- **WHEN** 用户显式要求 single 但任务匹配强制 Triad
- **THEN** 交互入口要求明确确认风险；headless 入口仅在服务端预授权该覆盖时允许，否则拒绝

### Requirement: 协作报告稳定、有界且兼容
协作执行 MUST 返回加法式稳定报告，包含 mode、终态、稳定原因、角色尝试计数、计划项计数、通过/失败计数、打回次数、累计轮次与 normalized usage。报告 MUST NOT 包含完整目标、计划正文、模型回复、工具参数、文件内容、绝对路径、credential 或未掩码证据。普通 `TaskOutcome` 的既有字段与语义 MUST 保持兼容。

#### Scenario: 安全终态投影
- **WHEN** CLI 或 HTTP 输出协作终态
- **THEN** 输出只包含稳定枚举、计数、模型标识和经过掩码截断的逐项证据摘要

#### Scenario: 普通结果未改变
- **WHEN** single 任务结束
- **THEN** 现有调用方仍收到原 `TaskOutcome` 形状，不需要解析协作字段

