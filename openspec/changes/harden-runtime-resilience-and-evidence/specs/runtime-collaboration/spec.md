## ADDED Requirements

### Requirement: Evaluator 只能执行宿主冻结的隔离检查
协作运行时 MUST 允许宿主为 Evaluator 注册零个或多个稳定检查 ID。Evaluator 只能提交检查 ID，MUST NOT 提交或覆盖 argv、shell 文本、工作目录、环境变量、超时或输出上限。检查 MUST 在项目临时工作副本内以无 shell 子进程执行，使用宿主冻结的参数、最小环境、固定超时和有界输出；检查结果 MUST 作为不含绝对路径和已知 secret 的结构化证据返回。未注册检查时 MUST 保持既有 Evaluator 工具集合与行为。

#### Scenario: Evaluator 运行已注册检查
- **WHEN** Evaluator 调用 `RunCheck` 并选择宿主已注册的检查 ID
- **THEN** 运行时在临时工作副本中执行该检查的冻结 argv，并返回稳定状态、退出码、耗时和有界脱敏输出

#### Scenario: Evaluator 请求未知检查
- **WHEN** Evaluator 提交不存在或未向本次协作注册的检查 ID
- **THEN** 运行时返回结构化失败且不启动任何子进程

#### Scenario: 检查超时
- **WHEN** 已注册检查超过其冻结超时
- **THEN** 运行时终止对应子进程组、返回稳定的 timeout 结果，并清理临时工作副本

#### Scenario: Evaluator 不能注入命令
- **WHEN** 模型输出尝试携带 argv、shell、路径、环境或其他未定义字段
- **THEN** 协议校验拒绝该调用，普通 `Exec` 仍不在 Evaluator registry 中

#### Scenario: 未配置检查保持兼容
- **WHEN** 宿主没有为本次协作注册任何检查
- **THEN** Evaluator registry 仍只包含既有只读文件与提交验收工具，不广告 `RunCheck`

### Requirement: 协作取消遵循可实现的有界停止语义
协作运行时 MUST 在每个安全边界检查取消并阻止启动新的 Planner、Generator、Evaluator 或 rejection attempt。已经进入 provider、工具或宿主检查的操作 MUST 由各自冻结超时或子进程终止机制收敛；运行时 MUST NOT 声称能够异步强杀 Python 线程。取消后返回的终态报告仍按既有 HTTP 终态优先级发布。

#### Scenario: 角色开始前取消
- **WHEN** cancel signal 在下一个协作角色或 rejection attempt 启动前已设置
- **THEN** 协作以 `cancelled` 停止且不构造或调用该角色

#### Scenario: 检查执行期间取消
- **WHEN** cancel signal 在 `RunCheck` 子进程执行期间设置
- **THEN** 运行时终止检查子进程组并返回取消结果，不等待完整检查超时

#### Scenario: 不可异步中断的宿主调用
- **WHEN** cancel signal 在一个没有安全强杀句柄的宿主线程调用期间设置
- **THEN** 运行时等待该调用自身冻结超时或返回，再于下一个安全边界停止，且文档不宣称即时硬取消
