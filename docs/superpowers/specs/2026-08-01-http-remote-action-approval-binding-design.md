---
comet_change: bind-http-remote-action-approvals
role: technical-design
canonical_spec: openspec
---

# M44 HTTP 远程动作审批绑定技术设计

## 1. 当前边界

HTTP service 已具备 Bearer 认证、严格 JSON、loopback-only、静态 exact allowlist、task registry 和持久化 MCP receipt。缺口是静态策略无法表达“只允许某一 task 以某一参数调用一次”，且 HTTP 不能显式 reconcile `unknown` receipt。

本设计不改变监听/传输信任边界。所谓 remote action approval 是“经 HTTP 控制面管理外部动作授权”，不是把 HTTP server 暴露到远端网络。

## 2. 权威对象与所有权

### 2.1 `HttpActionApproval`

严格冻结的公开记录：

```text
schema          forgeagent.http-action-approval.v1
approval_id     32 lowercase hex
action_type     mcp
scope           mcp/<server>/<tool>，现有 exact key 规则
request_digest  sha256 canonical JSON，64 lowercase hex
mode            allow_once
status          issued | bound | consumed | revoked | expired
task_id         null 或 32 lowercase hex
issued_at       UTC ISO-8601
expires_at      UTC ISO-8601
```

记录不保存 goal、arguments、prompt、evidence、路径、token 或异常。store 内部使用注入 clock 的 epoch deadline 判断过期，ISO 时间只用于安全投影。

### 2.2 `HttpActionApprovalStore`

单一 `RLock` 保护所有记录和状态迁移，构造参数为 `max_records`、可选 clock/audit。主要接口：

```python
issue(*, server, tool, request_digest, expires_in_seconds) -> HttpActionApproval
get(approval_id) -> HttpActionApproval
bind_many(approval_ids, task_id) -> tuple[HttpActionApproval, ...]
consume(*, task_id, scope, request_digest) -> HttpActionApproval | None
revoke(approval_id) -> HttpActionApproval
release_task(task_id) -> None
```

`bind_many` 先在锁内完成所有校验，再一次性 transition，禁止部分绑定。`consume` 只扫描当前 task 的 bound records，先惰性过期，再匹配 exact scope/digest；成功后立即 terminal。`release_task` 只把 bound 记录改为 revoked，不改变 consumed。

registry 使用 `HttpServiceConfig.max_records` 作为上限。签发前可按插入顺序移除 terminal record；若全是 issued/bound，返回 capacity error。

### 2.3 Receipt 权威不变

`ExternalActionReceipt` schema 和磁盘布局不变。approval consumed 表示授权额度已使用，receipt phase 表示执行事实。二者没有反向状态同步：receipt persistence 失败不能恢复 grant，receipt unknown 也不能重建 grant。

## 3. 状态迁移与竞态

```text
issue
  |
  v
issued -- bind(task) --> bound -- exact consume --> consumed
  |                       |
  +-- revoke/expire ------+---- revoke/expire --> revoked | expired
```

- `consumed/revoked/expired` 都是终态。
- bind 仅接受 issued；相同 ID 在提交列表重复直接拒绝。
- revoke 对 issued/bound 生效；对终态幂等返回当前记录。
- expiry 在 get/bind/consume/revoke/issue capacity cleanup 时惰性结算。
- consume/revoke 共享同一锁。先 consume 则 revoke 看到 consumed；先 revoke 则 consume 无匹配。
- 调度失败、queued cancel、loop ID 冲突、task terminal、shutdown 都调用 `release_task`，防止未消费 bound grant 悬挂。

## 4. 执行接入

`HeadlessConfirmer` 新增可选 approval consumer，但保留现有调用兼容：

1. 计算现有 `operation_key(args, root)`。
2. exact static allowlist 命中时保持 `preapproved`。
3. 未命中且 args 为 MCP、task ID 非空、approval store 可用时，计算 `canonical_request_digest(args.arguments)` 并调用 `consume`。
4. 其他情况 denied。

MCPTool 现有顺序保持：confirm -> receipt prepared -> receipt dispatched -> MCP call -> confirmed/unknown。因此只有 exact approval 被消费后才会尝试 receipt；receipt 写失败时动作不 dispatch，grant 保持 consumed。

FileWrite/WebFetch 不读取动态 approval store，避免把 M44 扩大成新的 receipt 体系。MCP CLI/REPL `autoApprove` 与 HTTP 静态 allowlist 保持现有兼容。

## 5. TaskService 原子绑定

`TaskRecord` 增加私有 `approval_ids: tuple[str, ...]`，不进入 `public_view`。`submit/submit_view` 新增 keyword-only approval IDs，旧调用保持兼容。

提交临界区顺序：

```text
validate public request
  -> capacity / loop-resume exclusion
  -> generate task_id
  -> approval_store.bind_many(all IDs, task_id)
  -> publish TaskRecord
  -> executor.submit(worker)
```

如果 bind 失败，不发布 TaskRecord。若 executor submit 失败，现有 tombstone 逻辑先阻止 late worker 构造 Task，再 release bound approvals。worker 发布 terminal 后在锁外/确定边界 release remaining bound approvals；cleanup 失败只写固定日志并保持 fail-closed。

approval IDs 不进入 `options`，所以不能到达 Task、Loop、Collaboration、model prompt 或 checkpoint。

## 6. HTTP API

### 6.1 Approval

`POST /action-approvals`

```json
{
  "action_type": "mcp",
  "server": "github",
  "tool": "create_issue",
  "request_digest": "<64-hex>",
  "mode": "allow_once",
  "expires_in_seconds": 300
}
```

成功 `201`。TTL 必须是非 bool integer，范围 1-3600 秒；keys 必须精确一致。

`GET /action-approvals/{32hex}` 返回安全记录。`POST .../revoke` 只接受空 JSON，成功 `200`，对 terminal 幂等。

任务 body 可在任何现有合法 shape 上额外带：

```json
{"approval_ids":["<32hex>"]}
```

列表 1-16，必须 unique；空列表、非字符串、格式错误或重复为 `invalid_request`。parser 把列表与现有 scalar options 分离。

### 6.2 Receipt

`GET /tasks/{task_id}/receipts` 返回：

```json
{"receipts":[{"action_id":"...","action_type":"mcp","server_label":"...","tool_label":"...","request_digest":"...","phase":"unknown","resolution":"open","dispatch_certainty":"unknown","remote_ok":null,"evidence_code":"result_unknown","revision":2}]}
```

只列 authoritative `task_id` 匹配且 resolution=open 的记录。

`POST /tasks/{task_id}/receipts/{action_id}/resolve`

```json
{"expected_revision":2,"decision":"confirmed","evidence":"provider event 123"}
```

decision 只接受 `confirmed|abandoned|retry_approved`；confirmed evidence 必须非空且有界。handler 先验证 retained task，再由 service load receipt、验证 task ownership 和 open 状态，最后调用 store CAS。

### 6.3 固定错误

```text
400 invalid_request
404 approval_not_found | receipt_not_found | task not_found
409 approval_unavailable | receipt_conflict
429 approval_capacity
503 receipt_unavailable
500 internal_error
```

所有 detail 来自固定表。跨 task action 与未知 action 都投影为 receipt_not_found；不泄漏所有权。

## 7. 审计与公开面

新增固定事件：`http.approval_issue/query/revoke`、`http.receipt_list/resolve`，以及 store transition 的 `action_approval.state`。参数只含 approval/action/task ID、scope、digest、status/decision；不含 evidence 正文。现有 `confirmation.decision` 用 `allow_once` 标识动态命中。

公开 JSON 扫描 secret、goal、raw arguments、absolute root 和 raw exception。错误 handler 继续吞掉普通 Exception 并记录固定 message。

## 8. 测试矩阵

### 8.1 状态机单元测试

- 严格 schema/ID/digest/scope/TTL；safe projection。
- bind all-or-none、duplicate、wrong state、capacity terminal eviction。
- consume exact task/scope/digest、once-only、expiry。
- revoke-before-consume / consume-before-revoke 可控并发。
- release_task 只关闭 bound。

### 8.2 接入测试

- static allowlist 不消费 grant；dynamic exact grant 只消费一次。
- wrong task/scope/digest/expired 不调用 MCP。
- receipt unavailable 时 grant consumed 且 MCP 未调用。
- TaskService 不把 approval IDs 放入 options/public view；调度/取消/terminal/shutdown 清理。

### 8.3 HTTP 测试

- auth/method/content-type/length/body limit/unknown fields 矩阵。
- issue/get/revoke/status codes；task claim success/failure/rollback。
- receipt list/resolve、cross-task、stale revision、confirmed evidence。
- resolution 路径以 counting fake MCP 断言调用数不增加。
- non-loopback create_http_server 仍拒绝。

### 8.4 真实 verifier

在 ephemeral loopback port 启动真实 server，使用真实 HTTP client 请求；Task 使用 `MockClient` 产生确定的 MCP ToolCall，fake MCP manager 记录 dispatch。脚本验证：签发 -> submit claim -> exact consume -> one dispatch -> confirmed receipt；另造 unknown receipt并经 HTTP confirmed resolve，dispatch counter 不变。输出只含稳定计数/状态，退出码表达结果。

## 9. 实施与回滚

顺序为 attention 基线修复、状态机、confirmer、TaskService、HTTP routes、CLI wiring、verifier/docs。每一层先写失败测试再最小实现。

回滚删除动态 approval store/wiring/routes，恢复旧 task parser 即可；静态 allowlist 和 receipt schema 未迁移。进程内审批自然失效，磁盘 receipt 保持可由现有 CLI reconcile。
