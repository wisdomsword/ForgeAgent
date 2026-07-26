# triad-human-smoke Specification

## Purpose
TBD - created by archiving change add-m22-triad-human-smoke. Update Purpose after archive.
## Requirements
### Requirement: 一键脚本运行真实模型 Triad 并保留人工计划确认
仓库 MUST 提供单命令人类冒烟入口，在隔离工作目录中使用现有 ForgeAgent CLI 运行真实模型 Triad。脚本 MUST 保留 Planner 计划的终端人工确认，不得隐式批准；默认模型 MUST 可通过有界、明确的环境变量覆盖，且脚本不得打印 API key 或其他 credential。脚本 MUST 为本次验收隔离足够的 context feedback 预算，不得因用户全局低 feedback 限额而让 Evaluator 对完整短文件产生截断假拒绝，也不得修改或复制用户配置中的 credential。

#### Scenario: 用户配置低 feedback 限额
- **WHEN** 用户全局配置的 `tool_result_max_tokens` 和 `round_feedback_max_tokens` 低于本冒烟验收所需值
- **THEN** 一键脚本仅在本次 ForgeAgent 子进程中使用固定的足够预算，用户配置文件保持不变，Planner 人工确认和模型路由仍正常工作

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
脚本的命令组装、状态解析和产物验收 MUST 可通过依赖注入或子进程 fixture 离线测试；项目自动测试 MUST NOT 调用真实模型、访问真实用户 HOME 或消耗凭证。状态加载 MUST 通过控制流稳定区分超大文件与无效 JSON，不得依赖底层异常消息字符串；计划中重复的合法 ID MUST 被唯一性校验明确拒绝。

#### Scenario: 状态错误与重复 ID 精确分类
- **WHEN** JSON parser 抛出与文件过大诊断同文案的异常，或计划包含两个相同且格式合法的 ID
- **THEN** 前者仍稳定报告无效 JSON，后者精确报告 plan item ID 不唯一，且离线测试直接覆盖对应分支

