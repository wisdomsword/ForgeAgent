## MODIFIED Requirements

### Requirement: Loop checkpoint 是版本化、原子且有界的耐久状态
Loop SHALL 将 schema 版本、Loop 身份、原始目标、预算配置、累计预算、迭代计数、连续失败数、已完成条目、未解问题、下轮交接信息、最近安全失败摘要和终态写入 checkpoint。checkpoint MUST 位于允许根目录内，MUST 使用原子替换写入，MUST 拒绝符号链接逃逸、未知字段、超限内容、无效状态组合和不支持的 schema 版本。每个 Loop ID 的 create 与 save MUST 使用稳定 lock file 的跨进程排他锁，将存在性或 expected revision 校验与原子替换纳入同一临界区；同一旧 revision 的重叠提交最多一个成功。Checkpoint 的 Pydantic 字段名 MAY 使用内部保留名，但序列化和反序列化 MUST 保持公开 JSON 键 `schema`，并兼容既有 checkpoint。

#### Scenario: 模型提交进度 checkpoint
- **WHEN** Loop 专用 `Checkpoint` 工具收到合法的已完成条目、未解问题和交接信息
- **THEN** 系统在返回工具成功反馈前原子持久化新状态，并保留此前已提交完成条目

#### Scenario: 旧 checkpoint 使用 schema 键加载
- **WHEN** 旧 checkpoint JSON 使用 `schema` 键且其他字段有效
- **THEN** 系统成功加载并继续以 `schema` 键序列化，不要求调用方改写文件

#### Scenario: checkpoint 写入失败
- **WHEN** checkpoint 目录不可写、目标发生路径逃逸、lock file 不安全、加锁失败或原子替换失败
- **THEN** `Checkpoint` 工具返回结构化失败，Loop 不声称进度已持久化，且失败可进入现有 Task 反馈环

#### Scenario: checkpoint 内容或版本无效
- **WHEN** resume 读取到未知 schema、额外字段、超限文本、无效计数或互相矛盾的终态
- **THEN** 系统在调用模型或工具前拒绝恢复，并保留原文件不变

#### Scenario: 同一旧 revision 跨进程重叠提交
- **WHEN** 两个进程都读取 revision N 并以 `expected_revision=N` 提交不同 checkpoint
- **THEN** 第一个锁内提交写入 revision N+1，第二个锁内重读后收到 stale revision 错误且不得覆盖第一份状态

#### Scenario: 不同 Loop ID 并行提交
- **WHEN** 两个进程同时保存不同 Loop ID
- **THEN** 它们使用不同稳定 lock file，不因全目录锁而互相串行化

### Requirement: Loop 终态报告稳定、有界且可离线验证
每个 Loop MUST 产生包含 schema、Loop ID、终态、停止原因、迭代/轮次/token/墙钟计数、连续失败数和 checkpoint 摘要计数的稳定报告。公开 CLI/HTTP 投影 MUST 脱敏、限制长度且不得暴露完整 prompt、checkpoint 正文、tool 参数、文件内容、绝对宿主路径或 secret。Loop 报告 MAY additionally expose a bounded attention projection when its stop reason is `needs_input` or `blocked`; the attention projection MUST follow the attention-state-protocol contract and MUST NOT change the existing terminal status taxonomy. Loop 报告的公开 JSON 也 MUST 使用 `schema` 键，且与既有报告兼容。

#### Scenario: 成功完成报告
- **WHEN** 某次 Task 以严格 completed 终态结束
- **THEN** Loop 原子写入 completed 报告并返回累计预算与进度计数，且 attention state 为 `ready`

#### Scenario: 预算停止报告
- **WHEN** 任一停止预算命中
- **THEN** 报告使用稳定枚举标识首个生效停止原因，并保留不超过上限的安全诊断，且不得伪装为 `needs_input` 或 `blocked`

#### Scenario: Attention stop report
- **WHEN** Loop 因需要用户输入或外部阻塞在安全边界停止
- **THEN** 报告使用 `status=stopped`、稳定 `stop_reason`（`needs_input` 或 `blocked`）和 bounded attention metadata，resume 不得静默重放动作

#### Scenario: 离线端到端恢复验证
- **WHEN** 测试使用 MockClient 在 checkpoint 后模拟中断并恢复
- **THEN** 恢复执行不重做已完成条目，每种停止条件及 attention stop 均可由确定性断言验证且无需 API key
