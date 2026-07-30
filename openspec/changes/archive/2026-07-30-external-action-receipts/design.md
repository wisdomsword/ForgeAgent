## 背景

MCP 运行在宿主进程中，位于 restricted/container executor 之外，可能修改外部系统。当前 `MCPTool` 已有确认门，但 `MCPManager.call_tool()` 对超时或异常只返回有界的 `{"ok", "text"}`，会把“可能已经发出”的动作折叠成普通失败。`LoopCheckpointStore` 能保存 Loop 进度，却不能覆盖普通 Task；审计又明确采用 fail-open 语义。因此需要一个同时服务普通 Task 和 Loop Task 的独立权威收据存储。

## 目标 / 非目标

**目标：**

- 对获准的非只读 MCP 调用，在发出前持久化严格、脱敏的收据。
- 区分未发出、收到协议响应和结果未知，不向模型暴露 SDK 异常。
- 在 Loop resume 和下一次迭代前阻断未决收据。
- 提供有界列举和显式 reconciliation，禁止自动重放。
- 复用现有确认门、MCP 生命周期、audit、allowed-root 和原子写入约定。

**非目标：**

- 本阶段不为配置的只读 `autoApprove` MCP 调用创建收据。
- 不把 `FileWrite`、`Exec`、`Edit` 或 `WebFetch` 改造成收据事务。
- 不提供远端 exactly-once 保证、通用补偿引擎、分布式数据库或新依赖。
- `unknown` 后不自动重试；新尝试必须有新的动作标识和显式授权。

## 技术决策

### 1. 使用独立的权威收据存储

新增 `ExternalActionReceiptStore` 模块，在项目 allowed root 下的 `.forgeagent/receipts/` 保存每个动作的严格版本化 JSON 收据。存储沿用 Loop checkpoint 的安全模式：目录描述符绑定、符号链接检查、有界字段、每动作锁文件、临时文件原子替换和 `fsync`。对外提供 create、phase-transition、list-pending、load、reconcile 操作；audit 只接收投影。

**不采用的方案：** 将收据字段直接写入 JSONL audit 会继承 audit fail-open 语义，无法安全阻断重放；只扩展 LoopCheckpoint 会漏掉普通 Task，并把不相关的进度状态耦合到外部动作。

### 2. 四阶段与独立决策字段分离

权威 delivery phase 严格限定为 `prepared`、`dispatched`、`confirmed`、`unknown`。另设有界 resolution 字段（`open`、`confirmed`、`abandoned`、`retry_approved`）记录人工决策，不把人工决策混入 delivery phase。`unknown` 即使已经 resolution 也保留历史；任何重试都创建新的 receipt/action ID，并链接原收据。

**不采用的方案：** 用 `abandoned` 或 `retried` 作为 delivery phase 会混淆远端是否被联系过；将 delivery certainty 与人工 resolution 分离才能保持四态契约清晰。

### 3. 收据边界放在 `MCPTool`

保留现有确认门。非 auto-approved MCP 调用通过确认后，`MCPTool` 请求 manager 提供安全目标摘要，创建 `prepared` 收据；在 `MCPManager` 调用 SDK session 前立即标记 `dispatched`；再根据 manager 的内部 certainty 结果转为 `confirmed` 或 `unknown`。已自动批准的调用保持当前路径。

**不采用的方案：** 让每个 `Tool.run()` 都理解收据会扩大本里程碑，并错误地把本地文件动作当成远端不确定投递。

### 4. Manager 保持兼容的内部扩展

`MCPManager.call_tool()` 保留现有 `ok/text` 字段，在结果映射中增加内部 certainty 字段；`MCPTool` 消费该字段，并为 unknown 返回固定反馈。SDK 异常文本仍不得进入模型、CLI 或 audit。

### 5. Loop 在模型构造前执行 gate

`LoopRunner.resume()` 在返回可运行 runner 前检查 pending receipts；`LoopRunner.run()` 在每次迭代前再次检查，覆盖上一迭代刚产生收据的情况。发现未决收据时写入稳定的 `external_action_pending` 停止原因并返回现有安全报告投影，不创建 Task，不调用 collaboration builder。

**不采用的方案：** 只把警告注入下一轮 prompt 会允许模型忽略警告并重放，违反 fail-closed 恢复要求。

### 6. CLI reconciliation 显式且有界

增加 `receipts` CLI 子命令，提供 `list` 和 `resolve`。`list` 只展示脱敏的标识、phase、resolution、目标标签、时间戳以及 Task/Loop 关联。`resolve` 要求 `--confirmed`、`--abandon`、`--retry` 三者恰选其一；确认时必须提供有界 evidence。`--retry` 只授权未来调用逻辑，不执行原动作。

## 风险 / 取舍

- [收据存储不可用] → 拒绝受保护 MCP dispatch，返回固定错误；覆盖权限、符号链接替换、畸形记录和原子写失败测试。
- [持久化 transition 与 SDK 调用之间崩溃] → `prepared`/`dispatched` 作为未决状态阻断 resume；由 reconciliation 保守处理。
- [MCP 协议错误不等于业务结果] → 只有收到协议层响应才记录 `confirmed`，另行保存 server error 状态，不宣称业务成功。
- [旧调用方只读取 `ok/text`] → 保留这两个字段，仅增加内部可选 certainty，并添加兼容测试。
- [CLI/HTTP 并发 reconciliation] → 单收据加锁并拒绝 stale revision，不覆盖更新的 transition。
- [audit sink fail-open] → pending 判断永远不读取 audit；权威收据独立决定，audit 只按既有语义报告 degraded。

## 迁移计划

1. 先新增收据模型/存储和单测，不改变现有工具行为。
2. 增加 MCP 内部 certainty 结果，仅让非 auto-approved 调用接入收据。
3. 增加 Loop gate 与 CLI 列举/reconciliation，再更新 audit/威胁模型文档。
4. 既有项目没有收据文件，因此行为不变；新出现的畸形或不安全收据 fail closed。
5. 回滚时移除新集成路径，收据文件保留为不可执行的历史；回滚过程不自动重放外部动作。

## 开放问题

本里程碑没有阻塞性问题。支持 provider-specific 幂等键的远端系统可在后续 change 接入；本阶段只记录 request digest，不宣称 MCP server 实际遵守幂等语义。
