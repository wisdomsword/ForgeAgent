---
comet_change: external-action-receipts
role: technical-design
canonical_spec: openspec
---

# 外部动作收据与未知状态恢复：技术设计

## 1. 设计范围

本设计只处理 MCP 宿主调用可能造成的外部副作用。现有 `MCPTool` 的确认门、MCP server generation 生命周期、任务审计和 Loop checkpoint 都保留；新增能力负责把“是否已经发出、结果是否可确定、是否允许继续”从普通工具结果中分离出来。

明确不纳入本 change：`FileWrite`、`Exec`、`Edit`、`WebFetch` 的收据化，远端 exactly-once，自动补偿编排，新的数据库或第三方依赖，HTTP reconciliation endpoint。

## 2. 当前边界与问题

当前调用链是：

```text
模型 ToolCall
    -> Step._dispatch
    -> MCPTool.run
    -> confirmer / HTTP allowlist / autoApprove
    -> MCPManager.call_tool
    -> MCP session.call_tool
    -> ToolOutcome(ok, text)
    -> tool.operation audit
```

`MCPManager.call_tool()` 的同步 facade 在 SDK 超时或异常时返回固定失败文本；在 dispatch 已经发生但响应丢失时，调用方无法区分“没有发出”和“结果未知”。Loop 的 checkpoint 只记录进度，普通 Task 没有可恢复的外部动作状态；audit sink 又允许 fail-open。因此不能把 audit 或 Loop checkpoint 直接当作收据权威。

## 3. 收据数据模型

新增 `src/forgeagent/external_actions.py`，定义严格、冻结的 Pydantic 模型：

```text
schema             forgeagent.external-action-receipt.v1
action_id          32 位十六进制稳定标识
parent_action_id   可选的上一动作标识（新尝试关联历史）
task_id            有界任务标识
loop_id            可选的 Loop 标识
action_type        固定为 mcp
server_label       MCP public server label
tool_label         MCP public tool label
request_digest     原始参数 canonical JSON 的 SHA-256
phase              prepared | dispatched | confirmed | unknown
resolution         open | confirmed | abandoned | retry_approved
dispatch_certainty not_dispatched | confirmed | unknown | null
remote_ok          true | false | null
evidence_ref       有界、脱敏、控制字符转义的固定代码/摘要
revision           非负整数
created_at         UTC 时间字符串
updated_at         UTC 时间字符串
```

不持久化原始 server/tool identity、原始 arguments、凭据、完整异常或绝对路径。`request_digest` 只用于关联和比对，不是幂等承诺。

状态约束：

- 创建必须是 `phase=prepared`, `resolution=open`。
- dispatch 前只能从 `prepared` 到 `dispatched`。
- 收到 MCP 协议响应时从 `dispatched` 到 `confirmed`, `dispatch_certainty=confirmed`, `remote_ok` 取 `isError` 的相反值。
- 能证明 SDK session 尚未被调用时，从 `prepared` 或 `dispatched` 到 `confirmed`, `dispatch_certainty=not_dispatched`, `remote_ok=false`, `evidence_ref=no_dispatch`。
- dispatch 后 timeout/cancel/exception 或 facade 等待超时一律到 `unknown`, `dispatch_certainty=unknown`, `remote_ok=null`, `resolution=open`。
- `unknown` 的 reconciliation 只改变 `resolution`，不把 phase 改成 `confirmed`；否则会错误地宣称收到远端响应。
- `resolution=retry_approved` 不触发执行；后续显式调用必须创建新的 action ID，并可写入 `parent_action_id`。

## 4. 存储与并发

`ExternalActionReceiptStore` 使用 `<allowed_root>/.forgeagent/receipts/<action_id>.json`，每个动作有稳定的私有 lock 文件。实现复用 `LoopCheckpointStore` 的安全原则：

1. 解析并绑定 canonical allowed root，拒绝符号链接和目录替换。
2. 以 descriptor-relative 方式打开 receipt/lock，限制权限为 `0600`。
3. 在 lock 内重新读取当前 revision，验证 expected revision。
4. 将严格 JSON 写入随机临时文件，flush + `fsync` 后原子替换并同步目录。
5. load/list 拒绝未知 schema、额外字段、非法 phase/resolution、超限文本、非有限 JSON 和路径越界。
6. 任何 store 失败都不删除历史、不回退到 audit、不允许受保护 MCP dispatch。

核心接口保持小范围：

```text
create_prepared(...)->Receipt
mark_dispatched(action_id, expected_revision)->Receipt
mark_confirmed(action_id, expected_revision, certainty, remote_ok, evidence)->Receipt
mark_unknown(action_id, expected_revision, evidence)->Receipt
list_pending(loop_id=None, task_id=None)->tuple[Receipt, ...]
resolve(action_id, expected_revision, decision, evidence)->Receipt
```

## 5. MCP 数据流

```text
MCPTool.run
  ├─ autoApprove 命中
  │    └─ 保留现有直接路径（只读兼容，不创建 receipt）
  └─ 非 autoApprove
       ├─ 现有 confirmer / headless allowlist
       ├─ receipt.create_prepared（失败则拒绝 dispatch）
       ├─ receipt.mark_dispatched（失败则拒绝 dispatch）
       ├─ manager.call_tool -> {ok, text, dispatch_certainty}
       ├─ confirmed/not_dispatched -> receipt.mark_confirmed
       └─ unknown -> receipt.mark_unknown，固定 result-unknown ToolOutcome
```

`MCPManager` 保留已有 `ok` 和 `text`，仅增加内部 `dispatch_certainty`。状态判定必须在 loop-owned `_call_tool_on_loop` 中完成：无 state/session、未通过 generation 检查且没有进入 SDK 时返回 `not_dispatched`；SDK 返回任何 MCP response（包括 `isError=true`）返回 `confirmed`；SDK 异常、取消、超时或同步 facade 失去确定性返回 `unknown`。不向上层传递 SDK exception text。

`MCPTool` 为每次受保护调用生成独立的 receipt/action ID；现有任意格式的 `ToolContext.operation_id`/ToolCall ID 不收紧，仅作为有界的 `source_operation_id` 关联字段写入 receipt audit projection。这样可保证 `confirmation.decision`、`external_action.receipt` 和 `tool.operation` 可关联，同时不破坏既有调用协议。确认被拒绝时不创建 receipt；受保护调用没有 receipt store 时固定 fail closed。

## 6. Task、HTTP 与协作装配

`Task` 与 `ToolContext` 新增可选 `receipt_store`。CLI `run`、REPL、`loop` 和 HTTP service 在自己的 allowed root 下创建/复用一个 store，并将其注入所有相关 Task。Duo/Triad 只有 Generator 暴露 MCP，因此只需给 Generator Task 同一 store；Planner/Evaluator 保持现有无 MCP registry。

无 MCP 的 Task 不创建、不读取 store，保持现有行为。直接构造带 MCP 的 Task 时若没有显式 store，受保护调用返回 receipt-unavailable；这样不会因为测试或第三方调用绕过 fail-closed 边界。

CLI 增加：

```text
forgeagent receipts list [--loop-id ID] [--task-id ID]
forgeagent receipts resolve ACTION_ID (--confirmed | --abandon | --retry) [--evidence TEXT]
```

`--confirmed` 必须有 bounded evidence；三个 decision flag 互斥。命令只操作当前 cwd 的 allowed root，不启动 MCP manager，不执行任何外部动作。resolve 成功后发出一条 `external_action.receipt` audit projection。

## 7. Loop gate 与终态

将 `external_action_pending` 加入 `LoopStopReason` 的 stopped 集合。`LoopRunner` 持有可选 receipt store：

- `resume()` 读取 checkpoint 并绑定同一 allowed root 的 store；不创建模型 Task。
- `run()` 获得 run lock 后、首个 `_run_iteration` 前调用 `list_pending(loop_id=checkpoint.loop_id)`。
- 每次 `_record_outcome` 后和下一次迭代前再次检查 pending receipts。
- 发现任一 `resolution=open` 收据时，调用 `_stop("external_action_pending")`，返回现有 `LoopReport` 安全投影；不调用 task builder、collaboration builder、model 或 tool。
- `resolution=confirmed|abandoned|retry_approved` 的历史收据不再阻断；任何新尝试由新的 action ID 表示。

这个 gate 放在模型构造前，而不是 prompt 中，因为模型无法替宿主判断远端动作是否已发生。

## 8. Audit 合同

每次权威 receipt create/dispatch/confirmed/unknown/resolve 成功后，调用 `emit_audit` 发送 `event_type="external_action.receipt"`：

```text
operation_id = action_id
action_id / phase / resolution / dispatch_certainty
remote_ok / evidence_code / masked target label
task_id（若有）/ source_operation_id（若有，限长脱敏）
```

不得包含原始参数、凭据、完整 evidence、绝对路径。audit sink 失败沿用既有 degraded 语义，但不影响 receipt 的 pending 判断；若 receipt transition 本身失败，外部动作按 store 失败策略处理。

## 9. 测试与验证矩阵

### 收据存储

- 正常四态迁移与 resolution 分离；confirmed protocol error 仍有 `remote_ok=false`。
- dispatch 前崩溃、dispatch 后崩溃、timeout/cancel、no-dispatch 证明。
- stale revision、并发写、符号链接/目录替换、非法 schema、超限字段、secret/control masking。

### MCP

- autoApprove 仍不创建 receipt；确认拒绝不创建 receipt。
- store 不可用时不进入 manager；prepared/dispatched transition 失败时 fail closed。
- MCP response、`isError` response、无 session、generation mismatch、SDK exception、facade timeout 分别得到正确 certainty。
- `ok/text` 兼容、固定 unknown feedback、现有确认/HTTP allowlist 和 audit event 数量不回归。

### Loop 与入口

- resume 和迭代前 pending gate 不创建 Task；reconciliation 后可以继续。
- 新 action ID 与 parent link；普通无 MCP/no receipt Loop 全部现有测试保持通过。
- CLI list/resolve 的互斥参数、evidence 上限、脱敏、stale revision 和无自动 dispatch。

完成前运行专项 pytest、全量 pytest、Ruff、构建、OpenSpec strict；出现测试或构建失败时先按 systematic debugging 调查根因，再修复和重跑。

## 10. 残余风险

- MCP server 可能在返回协议响应前已经执行部分业务操作；`confirmed` 只代表协议层确定，不代表业务语义完成。
- `unknown` reconciliation 依赖用户或受信任宿主的外部核实；ForgeAgent 不拥有远端查询或补偿能力。
- 收据锁依赖本地文件系统 advisory locking；恶意绕过锁的进程和不可靠网络文件系统不在保证范围内。
- 收据只保护纳入本 change 的 MCP 路径；本地代码、可信宿主和未纳入的远端工具仍由现有威胁模型约束。
