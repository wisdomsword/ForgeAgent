## MODIFIED Requirements

### Requirement: Evaluator 只能执行宿主冻结的隔离检查
协作运行时 MUST 允许宿主为 Evaluator 注册零个或多个稳定检查 ID。Evaluator 只能提交检查 ID，MUST NOT 提交或覆盖 argv、shell 文本、工作目录、环境变量、超时或输出上限。检查 MUST 在项目临时工作副本内以无 shell 子进程执行，使用宿主冻结的参数、最小环境、固定超时和有界输出；检查 worker MUST 能读取和枚举当前 Python 解释器环境以导入宿主已安装依赖，并 MUST 能读写当前平台固定的 null device 以支持测试框架捕获，但 MUST 继续拒绝项目副本和 Python 运行时之外的宿主目录枚举、其他宿主文件写入、网络与进程创建。检查结果 MUST 作为不含绝对路径和已知 secret 的结构化证据返回。未注册检查时 MUST 保持既有 Evaluator 工具集合与行为。

#### Scenario: Evaluator 运行已注册检查
- **WHEN** Evaluator 调用 `RunCheck` 并选择宿主已注册的检查 ID
- **THEN** 运行时在临时工作副本中执行该检查的冻结 argv，并返回稳定状态、退出码、耗时和有界脱敏输出

#### Scenario: 检查导入宿主已安装依赖
- **WHEN** 宿主冻结的 Python 检查通过当前解释器导入 pytest 等已安装包及其子模块
- **THEN** check worker 允许只读枚举当前 Python 运行时目录并正常执行检查，不把合法子模块误报为缺失

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

#### Scenario: Python 运行时之外的宿主目录仍不可枚举
- **WHEN** 检查代码尝试列出项目副本与当前 Python 运行时之外的宿主目录
- **THEN** worker 返回固定的 restricted 失败且不泄露目录条目
