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

### Requirement: 打回环有界且证据驱动
Evaluator 失败 SHALL 把有界、脱敏、逐项证据返回新的 Generator Task；每次修正 MUST 使用新的 Generator conversation，并保留原始目标与冻结计划。新的 Generator Task MUST 被明确要求先根据失败证据实质性修正 Candidate，再调用 `SubmitCandidate`；当失败证据报告要求文件不存在时，Generator MUST 被要求先成功执行对应 `FileWrite`，不得在 Candidate 未发生相应修正时原样重提。系统 MUST 支持可配置的最大打回次数，默认 2；达到上限、取消、角色失败或预算不足时 MUST 以稳定原因停止，不得无限重试。

#### Scenario: 缺失文件打回后先修正
- **WHEN** Evaluator 拒绝 Candidate 并明确报告冻结计划要求的文件不存在
- **THEN** 下一 Generator Task 的系统提示明确要求先成功创建对应文件、禁止原样调用 `SubmitCandidate`，且逐项拒绝证据继续作为有界 task data 提供

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

### Requirement: 协作角色使用结构化提交门完成工作
Planner、Generator 和 Evaluator MUST 分别通过本角色 registry 中唯一的结构化 Submit 工具完成
角色。成功 Submit MUST 在持久状态保存后立即完成当前角色，并 MUST 阻止同一响应中后续工具
执行。普通 prose 或 `task_status.completed` MUST NOT 代替 required Submit；运行时 MAY 对首次
缺失提交提供一次有界结构化恢复提示。未注册 required Submit 的 single 模式 MUST 保持既有
完成语义。

#### Scenario: 成功提交立即完成角色
- **WHEN** 协作角色在同一响应中先执行合法准备工具，再成功调用本角色 Submit 工具，并在其后声明其他工具调用
- **THEN** 运行时按 parser 的确定性工具顺序执行到 Submit，将持久状态保存并完成角色，且不执行或审计 Submit 后的工具

#### Scenario: 完成声明不能替代提交
- **WHEN** 协作角色声明 completed 但未成功调用 required Submit
- **THEN** 运行时首次返回精确的缺失工具恢复提示，重复绕过提交时以 `invalid_role_submission` 结束该协作

#### Scenario: Single 完成语义保持兼容
- **WHEN** single Task 使用未登记 required completion tool 的 registry
- **THEN** Step 保持既有工具、prose recovery 和 `task_status` 完成行为

### Requirement: Generator Candidate 与当前 attempt 原子绑定
在 Duo/Triad 中，Generator MUST 成功调用零载荷 `SubmitCandidate` 才能进入 Evaluator。
`SubmitCandidate` MUST 在同一次 revision-checked 保存中递增 `generator_attempts`、将 phase 切换为
`evaluator` 并清空旧 `last_evaluation`。Generator 的普通 Task completion MUST NOT 推进 phase。
Evaluator MUST NOT 在当前 Candidate 尚未提交时启动。

#### Scenario: 当前 Candidate 提交后进入验收
- **WHEN** Generator 在 generator phase 成功调用 `SubmitCandidate` 且 state revision 未过期
- **THEN** 状态原子变为 evaluator phase、Generator attempt 恰好增加一次、旧 verdict 被清空，Runner 才能启动 Evaluator

#### Scenario: Candidate 提交失败不推进 phase
- **WHEN** `SubmitCandidate` 在错误 phase、过期 revision 或无效调用中失败
- **THEN** phase、attempt 和 verdict 保持不变，工具返回结构化失败并允许当前角色在剩余轮次修正

### Requirement: Verdict 只属于当前已提交 Candidate
Evaluator MUST 只验收 evaluator phase 中当前已提交的 Candidate。`SubmitEvaluation` MUST 在同一次
revision-checked 保存中写入覆盖冻结计划的 verdict 并递增 `evaluator_attempts`，但 MUST NOT 自行
决定 pass、reject、rejection count 或协作终态。拒绝回到 Generator 时，运行时 MUST 暂存旧 verdict
用于恢复拒绝反馈；下一次 `SubmitCandidate` 成功时 MUST 清空该 verdict。恢复时 evaluator phase
中的空 verdict MUST 重跑 Evaluator，非空 verdict MUST 直接交由 Runner 判定且不得重复调用模型。

#### Scenario: 拒绝后恢复 Generator 反馈
- **WHEN** Evaluator 提交失败 verdict，Runner 未达 rejection limit 并在进入新 Generator 前发生恢复
- **THEN** generator phase 保留旧 verdict，新的 Generator Task 收到该有界拒绝证据，且旧 verdict 不能被当作新 Candidate 的结果

#### Scenario: 已提交 verdict 恢复时不重复验收
- **WHEN** collaboration 从 evaluator phase 且 `last_evaluation` 非空的持久状态恢复
- **THEN** Runner 直接执行 pass/reject 判定，不创建新的 Evaluator Task，也不重复增加 evaluator attempt

#### Scenario: 待验收 Candidate 恢复
- **WHEN** collaboration 从 evaluator phase 且 `last_evaluation` 为空的持久状态恢复
- **THEN** Runner 为当前已提交 Candidate 创建 Evaluator Task，并要求结构化 `SubmitEvaluation`

### Requirement: 宿主可冻结 Candidate 最小文件就绪门
协作宿主 SHALL 能为一次 Duo/Triad Runner 冻结零个或多个有界的顶层候选文件名。配置非空时，`SubmitCandidate` MUST 在原子状态变更前确认每个名字在 allowed root 下对应非符号链接普通文件；任一文件缺失、类型不安全、无法安全打开或 project root 绑定变化时，提交 MUST 返回结构化失败并保持 phase、Generator attempt、旧 verdict 与 rejection count 不变。该门禁 MUST NOT 读取或判断文件内容，Evaluator 仍独占冻结计划的逐项验收权。未配置文件时 MUST 保持现有 Candidate 提交行为。

#### Scenario: 空 Candidate 被当前 Generator Step 拦截
- **WHEN** 宿主要求 `calc.py` 和 `test_calc.py`，Generator 在两个文件尚未成为 allowed root 下普通文件时调用 `SubmitCandidate`
- **THEN** 工具返回列出缺失安全相对文件名的有界失败，协作保持 generator phase 且 attempt/verdict/rejection 均不改变，当前 Generator 可在剩余轮次调用 `FileWrite` 后重试

#### Scenario: 文件就绪后原子提交
- **WHEN** 所有宿主冻结文件都已是 allowed root 下的非符号链接普通文件，且当前 phase/revision 有效
- **THEN** `SubmitCandidate` 沿用既有原子语义切换到 evaluator phase、递增一次 Generator attempt 并清空旧 verdict

#### Scenario: 符号链接或目录不能满足门禁
- **WHEN** 任一要求名字对应符号链接、目录或 project root 在检查期间发生重绑定
- **THEN** 运行时按 Candidate 未就绪处理且不推进持久状态，不跟随链接读取或泄露宿主路径

#### Scenario: 默认协作路径保持兼容
- **WHEN** single 模式运行，或 Duo/Triad/Loop/HTTP 宿主未配置候选文件要求
- **THEN** 系统不执行额外 Candidate 文件门禁，既有提交、恢复与完成语义保持不变

