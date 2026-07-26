## ADDED Requirements

### Requirement: 一键脚本运行真实模型 Triad 并保留人工计划确认
仓库 MUST 提供单命令人类冒烟入口，在隔离工作目录中使用现有 ForgeAgent CLI 运行真实模型
Triad。脚本 MUST 保留 Planner 计划的终端人工确认，不得隐式批准；默认模型 MUST 可通过有界、
明确的环境变量覆盖，且脚本不得打印 API key 或其他 credential。

#### Scenario: 人工批准后执行完整 Triad
- **WHEN** 用户运行一键脚本并在 Planner 计划确认提示中批准
- **THEN** 脚本继续运行 Generator 与 Evaluator，并将原 CLI 输出实时显示在当前终端

#### Scenario: 人工拒绝计划
- **WHEN** 用户在 Planner 计划确认提示中拒绝
- **THEN** 脚本以非零状态结束，明确报告 `needs_confirmation`，且保留隔离现场目录

#### Scenario: 非交互终端拒绝启动
- **WHEN** stdin 或 stdout 不是交互终端，无法提供 Planner 人工确认
- **THEN** 脚本在创建现场目录和调用任何真实模型前以非零状态结束，并明确提示需要交互终端

### Requirement: 脚本自动验证协作终态与可观察产物
脚本 MUST 在 ForgeAgent 进程结束后读取本次隔离目录中的协作状态，确认 mode 为 `triad`、status
为 `completed`、Planner 已提交计划、Generator 与 Evaluator attempts 均至少为 1，且 stop reason
不是 `invalid_role_submission`。随后 MUST 检查 `calc.py`、`test_calc.py`、pytest 成功和命令行 JSON
输出严格等于 `[1.5,2.5,3.5]`。

#### Scenario: 所有自动验收通过
- **WHEN** Triad 完成且生成产物、pytest 与 CLI 输出全部符合约定
- **THEN** 脚本以 0 退出，并打印 PASS、现场目录、collaboration ID、attempt 和 rejection 计数

#### Scenario: 协作或产物验收失败
- **WHEN** ForgeAgent 失败、协作状态不完整、文件缺失、pytest 失败或 CLI JSON 不匹配
- **THEN** 脚本以非零状态结束，列出失败阶段和有界诊断，并保留现场目录供人工检查

### Requirement: 一键入口具有无需真实模型的离线回归
脚本的命令组装、状态解析和产物验收 MUST 可通过依赖注入或子进程 fixture 离线测试；项目自动测试
MUST NOT 调用真实模型、访问真实用户 HOME 或消耗凭证。

#### Scenario: 离线成功与失败矩阵
- **WHEN** 测试分别提供成功、人工拒绝、ForgeAgent 失败、状态异常、pytest 失败和 CLI 输出错误 fixture
- **THEN** 测试可确定性验证对应退出码、诊断和现场保留行为，且不发起网络请求
