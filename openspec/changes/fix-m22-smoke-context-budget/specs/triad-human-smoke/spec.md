## MODIFIED Requirements

### Requirement: 一键脚本运行真实模型 Triad 并保留人工计划确认
仓库 MUST 提供单命令人类冒烟入口，在隔离工作目录中使用现有 ForgeAgent CLI 运行真实模型 Triad。脚本 MUST 保留 Planner 计划的终端人工确认，不得隐式批准；默认模型 MUST 可通过有界、明确的环境变量覆盖，且脚本不得打印 API key 或其他 credential。脚本 MUST 为本次验收隔离足够的 context feedback 预算，不得因用户全局低 feedback 限额而让 Evaluator 对完整短文件产生截断假拒绝，也不得修改或复制用户配置中的 credential。

#### Scenario: 用户配置低 feedback 限额
- **WHEN** 用户全局配置的 `tool_result_max_tokens` 和 `round_feedback_max_tokens` 低于本冒烟验收所需值
- **THEN** 一键脚本仅在本次 ForgeAgent 子进程中使用固定的足够预算，用户配置文件保持不变，Planner 人工确认和模型路由仍正常工作
