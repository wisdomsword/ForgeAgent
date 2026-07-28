## MODIFIED Requirements

### Requirement: Evaluator 独立验收并决定协作完成
在 Duo/Triad 模式中，Generator MUST 成功调用零载荷 `SubmitCandidate` 提交当前候选；普通 prose、
`task_status.completed` 或其他 Task 终态 MUST NOT 代替候选提交，也 MUST NOT 启动 Evaluator。
Evaluator MUST 使用结构化逐项结果判定外部可观察产物；只有所有要求通过，且宿主为本次协作注册的全部冻结检查都对当前 Candidate 通过时，协作结果才能为 completed。Evaluator 默认 MUST 使用 restricted tier，写工具 MUST 不可用，且其模型和 tier MAY 与 Generator 独立配置但不得扩大服务端或 CLI 所有者授予的权限。宿主未注册检查时 MUST 保持仅依据冻结验收项判定完成的兼容行为。

#### Scenario: Generator 未结构化提交被拦截
- **WHEN** Generator 声明完成但未成功调用当前 attempt 的 `SubmitCandidate`
- **THEN** 运行时不得启动 Evaluator，并在一次有界恢复仍失败后以 `invalid_role_submission` 结束协作

#### Scenario: Generator 候选验收失败
- **WHEN** Generator 成功调用 `SubmitCandidate`，但 Evaluator 发现至少一项外部可观察行为不满足
- **THEN** 协作结果保持未完成并生成有界、脱敏的实际行为、期望行为和定位证据

#### Scenario: 全部验收与冻结检查通过
- **WHEN** Evaluator 对冻结计划或 Duo 验收目标的全部项目返回 pass，且本次注册的全部冻结检查都对当前 Candidate 返回 pass
- **THEN** 系统返回 completed，并保留 Generator 与 Evaluator 的轮次、usage 和验收计数投影

#### Scenario: Evaluator 无写权限
- **WHEN** Evaluator 尝试修改被验收产物
- **THEN** 请求被工具注册表、确认门或 sandbox 拒绝，且该尝试不能形成 pass

### Requirement: Evaluator 只能执行宿主冻结的隔离检查
协作运行时 MUST 允许宿主为 Evaluator 注册零个或多个稳定检查 ID。Evaluator 只能提交检查 ID，MUST NOT 提交或覆盖 argv、shell 文本、工作目录、环境变量、超时、输出上限、检查状态或快照证据。检查 MUST 在项目临时工作副本内以无 shell 子进程执行，使用宿主冻结的参数、最小环境、固定超时和有界输出；检查 worker MUST 能读取和枚举当前 Python 解释器环境以导入宿主已安装依赖，并 MUST 能读写当前平台固定的 null device 以支持测试框架捕获，但 MUST 继续拒绝项目副本和 Python 运行时之外的宿主目录枚举、其他宿主文件写入、网络与进程创建。检查结果 MUST 作为不含绝对路径和已知 secret 的结构化证据返回。

当 Evaluator 提交全部验收项通过的 verdict 时，运行时 MUST 要求每个已注册检查都有当前 Evaluator Task 内产生的最新 `passed` 结果，且所有结果 MUST 绑定当前 Generator attempt 和同一当前 Candidate 快照。检查缺失、失败、超时、取消、执行错误、属于旧 attempt、对应不同快照或 Candidate 在检查后变化时，`SubmitEvaluation` MUST 拒绝全通过 verdict且不得保存 verdict或递增 Evaluator attempt。Evaluator 提交至少一个验收项失败的 verdict 时 MAY 不运行全部检查。恢复待验收 Candidate 时 MUST 不复用中断前的进程内检查证据。未注册检查时 MUST 保持既有 Evaluator 工具集合与行为。

#### Scenario: Evaluator 运行已注册检查
- **WHEN** Evaluator 调用 `RunCheck` 并选择宿主已注册的检查 ID
- **THEN** 运行时在临时工作副本中执行该检查的冻结 argv，并返回稳定状态、退出码、耗时和有界脱敏输出，同时由宿主记录该结果对应的当前 attempt 与 Candidate 快照

#### Scenario: 检查导入宿主已安装依赖
- **WHEN** 宿主冻结的 Python 检查通过当前解释器导入 pytest 等已安装包及其子模块
- **THEN** check worker 允许只读枚举当前 Python 运行时目录并正常执行检查，不把合法子模块误报为缺失

#### Scenario: Evaluator 请求未知检查
- **WHEN** Evaluator 提交不存在或未向本次协作注册的检查 ID
- **THEN** 运行时返回结构化失败且不启动任何子进程

#### Scenario: 检查超时
- **WHEN** 已注册检查超过其冻结超时
- **THEN** 运行时终止对应子进程组、返回稳定的 timeout 结果，并清理临时工作副本

#### Scenario: Evaluator 不能注入命令或证据
- **WHEN** 模型输出尝试携带 argv、shell、路径、环境、检查状态、快照摘要或其他未定义字段
- **THEN** 协议校验拒绝该调用，普通 `Exec` 仍不在 Evaluator registry 中

#### Scenario: 未运行检查时不能全通过
- **WHEN** 宿主注册至少一个检查，而 Evaluator 未运行全部检查就提交所有验收项通过
- **THEN** `SubmitEvaluation` 返回列出缺失检查 ID 的有界失败，持久状态和 Evaluator attempt 不变

#### Scenario: 失败检查不能被自报通过覆盖
- **WHEN** `RunCheck` 对当前 Candidate 返回 failed、timeout、cancelled、copy_error 或 start_error，而 Evaluator 仍提交所有验收项通过
- **THEN** `SubmitEvaluation` 拒绝该 verdict，模型不能通过参数覆盖宿主记录的检查状态

#### Scenario: Candidate 变化使检查证据失效
- **WHEN** 一个或多个检查通过后 Candidate 文件树发生变化，或多个检查对应不同 Candidate 快照
- **THEN** `SubmitEvaluation` 拒绝全通过 verdict，并要求在同一当前快照上重新运行全部冻结检查

#### Scenario: 新 attempt 不能复用旧证据
- **WHEN** Evaluator 拒绝 Candidate，Generator 提交新的 attempt，且新 Evaluator 尚未重新运行冻结检查
- **THEN** 新 Evaluator 的证据集合为空，旧 attempt 的通过结果不能满足全通过门禁

#### Scenario: 待验收 Candidate 恢复后重新检查
- **WHEN** 协作从 evaluator phase 且 verdict 为空的持久状态恢复
- **THEN** Runner 为当前 Candidate 创建新的 Evaluator Task，且中断前未持久化的检查结果不能满足全通过门禁

#### Scenario: 只读观察支持提前拒绝
- **WHEN** Evaluator 通过只读观察已确定至少一个冻结验收项失败
- **THEN** Evaluator 可以不运行全部冻结检查而提交包含失败项的 verdict

#### Scenario: 检查审计不泄露执行内容
- **WHEN** Evaluator 运行宿主冻结检查
- **THEN** 审计只记录检查 ID、当前 Generator attempt、稳定状态和耗时，不记录 argv、绝对路径、文件内容、完整输出或 Candidate 快照摘要

#### Scenario: 未配置检查保持兼容
- **WHEN** 宿主没有为本次协作注册任何检查
- **THEN** Evaluator registry 仍只包含既有只读文件与提交验收工具，不广告 `RunCheck`，全部冻结验收项通过时可沿用现有完成路径

#### Scenario: Python 运行时之外的宿主目录仍不可枚举
- **WHEN** 检查代码尝试列出项目副本与当前 Python 运行时之外的宿主目录
- **THEN** worker 返回固定的 restricted 失败且不泄露目录条目
