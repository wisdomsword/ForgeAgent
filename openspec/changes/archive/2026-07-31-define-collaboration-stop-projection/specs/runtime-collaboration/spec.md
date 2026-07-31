## MODIFIED Requirements

### Requirement: 协作报告稳定、有界且兼容
协作执行 MUST 返回加法式稳定报告，包含 mode、终态、稳定原因、角色尝试计数、计划项计数、通过/失败计数、打回次数、累计轮次、normalized usage 与可选的有界 attention。报告 MUST NOT 包含完整目标、计划正文、模型回复、工具参数、文件内容、绝对路径、credential、原始异常或未掩码证据。普通 `TaskOutcome` 的既有字段与语义 MUST 保持兼容。

Task 与 Loop 的已知停止信号 MUST 使用确定性投影：正常打回上限保持 `stopped/rejection_limit`；`needs_info` 映射为 `stopped/needs_input`；`blocked` 和未决外部动作映射为 stopped 的阻塞原因；`max_rounds`、`wall_clock`、`token_budget`、`token_usage_unavailable` 与 `consecutive_failures` MUST 保留具体资源原因并映射为 stopped；`cancelled` 映射为 cancelled；auth、invalid-request、checkpoint/state/protocol 损坏与其他不可恢复角色错误映射为 failed。未知原因 MUST fail closed，不得成为任意公开枚举。

#### Scenario: 安全终态投影
- **WHEN** CLI 或 HTTP 输出协作终态
- **THEN** 输出只包含稳定枚举、计数、模型标识、可选安全 attention 和经过掩码截断的逐项证据摘要

#### Scenario: 普通结果未改变
- **WHEN** single 任务结束
- **THEN** 现有调用方仍收到原 `TaskOutcome` 形状，不需要解析协作字段

#### Scenario: 资源耗尽原因透传
- **WHEN** 内层 Task 或外层 Loop 因 `max_rounds`、`wall_clock`、`token_budget`、`token_usage_unavailable` 或 `consecutive_failures` 停止
- **THEN** Collaboration 投影为 `stopped` 并保留该稳定原因，不把它误报为 `rejection_limit` 或 `role_failed`

#### Scenario: 需要输入和阻塞保持可恢复
- **WHEN** 内层 Task 报告 `needs_info`，或 Task/Loop 报告 `blocked`、`external_action_pending`
- **THEN** Collaboration 投影为 `stopped`，分别使用 `needs_input` 或稳定阻塞原因，并附带不含敏感正文的匹配 attention

#### Scenario: 不可恢复错误保持失败
- **WHEN** 角色遭遇 auth、invalid-request、状态损坏、checkpoint 损坏、无效结构化提交或其他不可恢复错误
- **THEN** Collaboration 报告为 `failed` 且只暴露固定失败原因，不包含原始异常正文
