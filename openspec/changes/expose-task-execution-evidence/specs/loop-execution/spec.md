## MODIFIED Requirements

### Requirement: Loop 终态报告稳定、有界且可离线验证
每个 Loop MUST 产生包含 schema、Loop ID、终态、停止原因、迭代/轮次/token/墙钟计数、连续失败数、checkpoint 摘要计数和已尝试工具执行证据的稳定报告。公开 CLI/HTTP 投影 MUST 对执行证据按迭代稳定聚合、脱敏、限制条目和长度并标记截断；HTTP 只可包含安全任务相对程序制品引用。公开投影不得暴露完整 prompt、checkpoint 正文、tool 参数、生成代码、文件内容、绝对宿主路径或 secret；本地 CLI MAY 在专用本地路径字段显示程序制品绝对路径。Loop 报告 MAY additionally expose a bounded attention projection when its stop reason is `needs_input` or `blocked`; the attention projection MUST follow the attention-state-protocol contract and MUST NOT change the existing terminal status taxonomy. Loop 报告的公开 JSON 也 MUST 使用 `schema` 键，且与既有报告兼容。

#### Scenario: 成功完成报告
- **WHEN** 某次 Task 以严格 completed 终态结束
- **THEN** Loop 原子写入 completed 报告并返回累计预算、进度计数和有界执行证据，且 attention state 为 `ready`

#### Scenario: 预算停止报告
- **WHEN** 任一停止预算命中
- **THEN** 报告使用稳定枚举标识首个生效停止原因，保留停止前已尝试工具的有界安全证据，且不得伪装为 `needs_input` 或 `blocked`

#### Scenario: Attention stop report
- **WHEN** Loop 因需要用户输入或外部阻塞在安全边界停止
- **THEN** 报告使用 `status=stopped`、稳定 `stop_reason`（`needs_input` 或 `blocked`）、bounded attention metadata 和停止前的有界执行证据，resume 不得静默重放动作

#### Scenario: HTTP Loop evidence uses relative artifact references
- **WHEN** HTTP 查询的终态 Loop 包含一个或多个程序执行制品
- **THEN** Loop 公开 JSON 按迭代返回安全相对制品引用且不包含任何宿主绝对路径或生成代码内容

#### Scenario: 离线端到端恢复验证
- **WHEN** 测试使用 MockClient 在 checkpoint 后模拟中断并恢复
- **THEN** 恢复执行不重做已完成条目，每种停止条件、attention stop 和执行证据聚合均可由确定性断言验证且无需 API key
