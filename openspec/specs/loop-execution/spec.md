# loop-execution Specification

## Purpose
TBD - created by archiving change loop-engineering. Update Purpose after archive.
## Requirements
### Requirement: Loop 可由现有运行入口显式触发
ForgeAgent SHALL 提供显式 CLI Loop 入口，并 SHALL 允许既有 HTTP 任务提交入口选择单任务或 Loop 模式。普通 `run`、REPL 和未选择 Loop 的 HTTP 请求 MUST 保持现有单 Task 语义。项目 MUST 只提供 cron、launchd 或 systemd 等外部调度示例，不得内置 scheduler 守护进程。

#### Scenario: CLI 启动新 Loop
- **WHEN** 用户以非空目标和合法预算调用 `forgeagent loop`
- **THEN** 系统创建唯一 Loop、在项目允许根目录内生成 checkpoint，并异步或同步执行现有 Task 迭代直到完成或命中停止条件

#### Scenario: 普通入口兼容
- **WHEN** 用户调用既有 `forgeagent run`、REPL 或未声明 Loop 模式的 HTTP 任务提交
- **THEN** 系统不创建 Loop checkpoint，且 Task/Step 的完成、工具和输出语义与 M21 前一致

#### Scenario: 外部调度器触发
- **WHEN** 操作系统调度器按文档调用 `forgeagent loop` 或 HTTP 提交接口
- **THEN** ForgeAgent 无需常驻 scheduler 即可启动或恢复一次 Loop 执行

### Requirement: Loop checkpoint 是版本化、原子且有界的耐久状态
Loop SHALL 将 schema 版本、Loop 身份、原始目标、预算配置、累计预算、迭代计数、连续失败数、已完成条目、未解问题、下轮交接信息、最近安全失败摘要和终态写入 checkpoint。checkpoint MUST 位于允许根目录内，MUST 使用原子替换写入，MUST 拒绝符号链接逃逸、未知字段、超限内容、无效状态组合和不支持的 schema 版本。

#### Scenario: 模型提交进度 checkpoint
- **WHEN** Loop 专用 `Checkpoint` 工具收到合法的已完成条目、未解问题和交接信息
- **THEN** 系统在返回工具成功反馈前原子持久化新状态，并保留此前已提交完成条目

#### Scenario: 进程在 Task 中途终止
- **WHEN** 模型已成功调用 `Checkpoint`，随后进程在当前 Task 返回前被终止
- **THEN** checkpoint 仍包含已提交进度，恢复提示明确要求跳过这些完成条目

#### Scenario: checkpoint 写入失败
- **WHEN** checkpoint 目录不可写、目标发生路径逃逸或原子替换失败
- **THEN** `Checkpoint` 工具返回结构化失败，Loop 不声称进度已持久化，且失败可进入现有 Task 反馈环

#### Scenario: checkpoint 内容或版本无效
- **WHEN** resume 读取到未知 schema、额外字段、超限文本、无效计数或互相矛盾的终态
- **THEN** 系统在调用模型或工具前拒绝恢复，并保留原文件不变

### Requirement: Resume 只续接兼容且未终结的同一 Loop
ForgeAgent SHALL 支持从 checkpoint 显式恢复，恢复时 MUST 使用 checkpoint 中冻结的目标与预算配置，MUST 延续累计迭代、轮次、token、墙钟和连续失败计数，并 MUST 把已完成条目、未解问题和交接信息注入下一 Task。已终结 checkpoint MUST 只返回其既有报告，不得再次执行模型或工具。

#### Scenario: 从中断 checkpoint 恢复
- **WHEN** 用户恢复一个有效且未终结的 checkpoint
- **THEN** 下一 Task 收到原目标和耐久交接状态，累计预算从已记录值继续，已完成条目不被要求重做

#### Scenario: 试图覆盖冻结配置
- **WHEN** resume 请求同时提供不同目标、预算或安全执行选项
- **THEN** 系统拒绝冲突输入，而不是静默改变原 Loop 的完成标准或资源上限

#### Scenario: 恢复已终结 Loop
- **WHEN** checkpoint 已记录 completed、budget exhausted、cancelled 或不可恢复失败终态
- **THEN** 系统返回既有有界报告且不创建新 Task

### Requirement: 所有停止条件按累计 Loop 预算执行
Loop MUST 支持累计轮次上限、累计 token 上限、累计墙钟上限、连续失败上限和协作取消；任一条件达到或超过边界时 MUST 在下一次模型调用前停止，原子写入稳定停止原因和有界报告。预算 MUST 使用实际已完成调用的 normalized `TokenUsage`，不得把缺失 usage 猜测为零以绕过已配置 token 上限。

#### Scenario: 累计轮次预算命中
- **WHEN** 已执行轮次达到配置上限
- **THEN** Loop 以 `max_rounds` 停止，恢复不会重置轮次计数

#### Scenario: token 预算命中
- **WHEN** 已记录输入、输出、缓存和 reasoning token 的规范化累计值达到配置上限，或 provider 未提供足够 usage 证明仍在预算内
- **THEN** Loop 在下一次模型调用前以 `token_budget` 停止并报告已知累计值与 usage 缺失状态

#### Scenario: 墙钟预算命中
- **WHEN** 当前执行段耗时加历史累计耗时达到配置上限
- **THEN** Loop 请求协作取消，并在当前不可中断调用返回后的首个安全边界以 `wall_clock` 停止；恢复不会重置已消耗墙钟

#### Scenario: 连续失败预算命中
- **WHEN** 连续未完成 Task 迭代达到配置上限
- **THEN** Loop 以 `consecutive_failures` 停止，成功完成才清零连续失败计数

#### Scenario: 外部取消
- **WHEN** CLI 中断或 HTTP cancellation 设置协作取消信号
- **THEN** Loop 不再启动新 Task，并以 `cancelled` 终结且不影响其他 Loop 或普通任务

### Requirement: 失败反馈环有界收敛且不引入独立 Evaluator
每个 Loop 迭代 SHALL 运行一个现有 Task；非完成结果 SHALL 生成脱敏、有界的失败摘要并与最近 checkpoint 交接信息一起进入下一迭代。Loop MUST 在停止预算内尝试修正，MUST 对明确不可恢复的配置、鉴权、checkpoint 或策略错误立即停止，并 MUST NOT 自动调用 M20 Evaluator 或实现 M22 Generator/Evaluator 打回语义。

#### Scenario: 可恢复失败后修正成功
- **WHEN** 一个 Task 因工具失败、上下文限制或轮次耗尽而未完成，但尚未命中 Loop 停止条件
- **THEN** 下一 Task 收到有界失败证据和继续要求，最终完成时 Loop 写入 completed 终态

#### Scenario: 反复失败不无限重试
- **WHEN** 每个 Task 均未完成且达到连续失败、轮次、token 或墙钟任一上限
- **THEN** Loop 停止并留下可诊断报告，不再调用模型

#### Scenario: Evaluator 边界保持隔离
- **WHEN** 普通 Loop 完成或失败
- **THEN** 系统不实例化、不导入热路径或自动调用独立 Evaluator，Loop 完成仍以现有 Task 的严格 completed 语义为准

### Requirement: Loop 终态报告稳定、有界且可离线验证
每个 Loop MUST 产生包含 schema、Loop ID、终态、停止原因、迭代/轮次/token/墙钟计数、连续失败数和 checkpoint 摘要计数的稳定报告。公开 CLI/HTTP 投影 MUST 脱敏、限制长度且不得暴露完整 prompt、checkpoint 正文、tool 参数、文件内容、绝对宿主路径或 secret。

#### Scenario: 成功完成报告
- **WHEN** 某次 Task 以严格 completed 终态结束
- **THEN** Loop 原子写入 completed 报告并返回累计预算与进度计数

#### Scenario: 预算停止报告
- **WHEN** 任一停止预算命中
- **THEN** 报告使用稳定枚举标识首个生效停止原因，并保留不超过上限的安全诊断

#### Scenario: 离线端到端恢复验证
- **WHEN** 测试使用 MockClient 在 checkpoint 后模拟中断并恢复
- **THEN** 恢复执行不重做已完成条目，每种停止条件均可由确定性断言验证且无需 API key
