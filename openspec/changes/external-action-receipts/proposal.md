## Why

ForgeAgent 的 MCP 调用运行在宿主进程并可能产生真实外部副作用；当前调用在请求已发出但进程、网络或 facade 超时导致结果丢失时，只会返回普通失败，Loop 恢复后可能再次执行同一动作。M28 已明确把这类 replay 风险列为残余边界，因此下一阶段先建立可持久化、可审计、可人工 reconciliation 的最小收据协议。

## What Changes

- 新增项目内耐久外部动作收据，使用 `prepared`、`dispatched`、`confirmed`、`unknown` 四态记录动作身份、请求摘要、目标安全标签、任务/Loop 关联和结果证据。
- 对需要确认的 MCP 调用启用收据；现有 `autoApprove` 只读调用保持当前轻量路径，不纳入首期副作用收据。
- MCP 调用结果区分“未进入远端调用”“收到权威结果”和“可能已发出但结果未知”，不再把 facade 超时等不确定结果折叠为可安全重试的普通失败。
- 新增只读列举和显式 reconciliation 命令；用户可在外部核实后把未知动作标记为已确认、允许重试或放弃，系统不会自动替用户作出副作用决策。
- Loop 在启动下一次迭代或 resume 前检查同一 Loop 的未决收据；存在未决动作时以稳定停止原因返回，不调用模型、不调用工具、不静默重放。
- 收据迁移写入脱敏 audit 投影；audit 保持现有 fail-open 诊断角色，不作为阻止重放的权威状态。
- 更新威胁模型、CLI 文档和离线回归测试。
- 不改变 `FileWrite`、`Exec`、`Edit` 的现有语义，不实现通用补偿编排，不承诺远端 exactly-once。

## Capabilities

### New Capabilities

- `external-action-receipts`: 定义外部副作用动作的耐久收据、确定性状态迁移、未决动作阻断和人工 reconciliation 合同。

### Modified Capabilities

- `mcp-resilience`: MCP 调用需要向收据层报告未发出、已确认或结果未知的确定性，并让需要确认的调用接入收据协议。
- `loop-execution`: Loop 启动和恢复需要在执行下一迭代前检测未决外部动作并停止，禁止自动重放。
- `audit-logging`: 审计需要记录脱敏的外部动作收据状态迁移，同时保持与权威收据存储的职责分离。

## Impact

- 主要影响 `src/forgeagent/tools.py`、`src/forgeagent/mcp_manager.py`、`src/forgeagent/task.py`、`src/forgeagent/step.py`、`src/forgeagent/loop.py`、CLI/HTTP Task 装配和新增的收据存储模块。
- 增加项目根目录下 `.forgeagent` 内的私有、原子、版本化收据文件；不新增第三方依赖。
- 增加收据专项单测、MCP/Loop/CLI/Audit 回归，以及威胁模型和用户文档更新。
- `publish-v0-1-0` 保持独立暂停；本 change 不上传 PyPI、不创建或推送正式 tag。
