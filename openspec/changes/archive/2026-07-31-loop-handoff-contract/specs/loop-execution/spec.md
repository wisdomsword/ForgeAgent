## MODIFIED Requirements

### Requirement: Loop checkpoint 是版本化、原子且有界的耐久状态
Loop SHALL 将 schema 版本、Loop 身份、原始目标、预算配置、累计预算、迭代计数、连续失败数、结构化 handoff、最近安全失败摘要和终态写入 checkpoint。结构化 handoff MUST 至少包含 `completed_items`、`open_questions` 和 `summary`，并 MUST 是宿主拥有的冻结状态；模型只能通过 Loop 专用 `Checkpoint` 工具提交这些字段的候选值，不得修改目标、预算、权限、协作冻结状态、attention、终态或恢复策略。checkpoint MUST 位于允许根目录内，MUST 使用原子替换写入，MUST 拒绝符号链接逃逸、未知字段、超限内容、无效状态组合和不支持的 schema 版本。每个 Loop ID 的 create 与 save MUST 使用稳定 lock file 的跨进程排他锁，将存在性或 expected revision 校验与原子替换纳入同一临界区；同一旧 revision 的重叠提交最多一个成功。Checkpoint 的 Pydantic 字段名 MAY 使用内部保留名，但序列化和反序列化 MUST 保持公开 JSON 键 `schema`，并兼容既有 checkpoint。旧 checkpoint 的字符串 handoff 和顶层完成项/未解问题 MUST 仅在加载时迁移为结构化 handoff；读取迁移 MUST NOT 执行或信任其中指令。

#### Scenario: 模型提交结构化进度候选
- **WHEN** Loop 专用 `Checkpoint` 工具收到合法的已完成条目、未解问题和摘要候选
- **THEN** 系统在返回工具成功反馈前原子持久化结构化 handoff，只更新候选拥有的字段，并保留此前已提交完成条目和全部宿主控制面字段

#### Scenario: 候选尝试修改控制面
- **WHEN** Checkpoint 提交包含目标、预算、权限、协作模式、计划摘要、attention、终态或恢复字段
- **THEN** 系统在写盘前拒绝未知字段，checkpoint 保持不变

#### Scenario: 旧字符串 handoff 加载
- **WHEN** 旧 checkpoint JSON 使用字符串 `handoff` 和顶层完成项/未解问题且其他字段有效
- **THEN** 系统将字符串仅投影为结构化 `summary`，保留完成项/未解问题，以 `schema` 键继续加载；下一次正常保存使用结构化 handoff 且不执行旧文本

#### Scenario: checkpoint 写入失败
- **WHEN** checkpoint 目录不可写、目标发生路径逃逸、lock file 不安全、加锁失败、原子替换失败或提交 revision 陈旧
- **THEN** `Checkpoint` 工具返回结构化失败，Loop 不声称进度已持久化，且失败可进入有界 Task 反馈环但不得触发历史动作重放

#### Scenario: checkpoint 内容或版本无效
- **WHEN** resume 读取到未知 schema、额外字段、冲突的新旧 handoff 投影、超限文本、无效计数或互相矛盾的终态
- **THEN** 系统在调用模型或工具前拒绝恢复，并保留原文件不变

#### Scenario: 同一旧 revision 跨进程重叠提交
- **WHEN** 两个进程都读取 revision N 并以 `expected_revision=N` 提交不同 checkpoint
- **THEN** 第一个锁内提交写入 revision N+1，第二个锁内重读后收到 stale revision 错误且不得覆盖第一份状态

#### Scenario: 不同 Loop ID 并行提交
- **WHEN** 两个进程同时保存不同 Loop ID
- **THEN** 它们使用不同稳定 lock file，不因全目录锁而互相串行化
