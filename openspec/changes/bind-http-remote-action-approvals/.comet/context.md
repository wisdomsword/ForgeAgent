# Comet Design Handoff

- Change: bind-http-remote-action-approvals
- Phase: design
- Mode: compact
- Context hash: a474992009949a06f797200fb041326781949462fbc93f40caf1688fd72a3c21

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/bind-http-remote-action-approvals/proposal.md

- Source: openspec/changes/bind-http-remote-action-approvals/proposal.md
- Lines: 1-29
- SHA256: 986cb95ad5b0650bf3ae4502b26d7975015c12e00634ff419568586dbd1614ea

```md
## Why

现有 HTTP 入口只能依赖启动时静态 allowlist 批准外部动作，无法让经认证的控制面把一次审批精确绑定到某个任务、动作范围和参数摘要，也无法通过 HTTP 撤销未使用审批或显式恢复 `unknown` receipt。M44 在继续保持 loopback-only 的前提下补齐这条最小、可验证且不自动重放的控制链。

## What Changes

- 新增宿主拥有的短期 `allow-once` 审批记录，绑定精确 MCP scope、canonical request digest、有效期和唯一任务。
- 新增经现有 Bearer 认证保护的审批签发、查询、撤销接口；任务提交显式认领审批后才可消费。
- 让 HTTP headless confirmer 在静态 allowlist 之外仅消费与当前 `task_id + scope + digest` 完全匹配的有效审批。
- 新增按任务列出未决 receipt 和显式 reconcile 的 HTTP 接口；确认、放弃或允许新尝试都只更新 receipt，不执行原动作。
- 增加真实 loopback verifier，覆盖审批签发、任务绑定、一次性消费、receipt 生成和未知状态恢复。
- 保持监听地址为 loopback，不增加 TLS、反向代理、用户体系、Gateway、公开网络入口或自动重放。

## Capabilities

### New Capabilities

- `http-action-approvals`: 定义短期一次性远程动作审批的签发、任务认领、精确消费、过期和撤销契约。

### Modified Capabilities

- `http-task-service`: 增加审批引用、审批管理和按任务 receipt reconcile 的严格认证 HTTP 契约，同时保持 loopback-only 与安全公开投影。
- `external-action-receipts`: 允许经 HTTP 认证的宿主调用者显式列出和恢复未决 receipt，且禁止任何恢复操作自动 dispatch。

## Impact

- 主要影响 `headless.py`、`http_server.py`、`http_task_service.py`、HTTP CLI 组装、外部动作 receipt 接入及相应测试/文档。
- 新增一个项目内审批状态模块和一个真实 loopback verifier；不新增第三方依赖，不修改 MCP 协议，不开放非 loopback 监听。
- M44 分支还会补入已被现有源码引用但未纳入 Git 的 `attention.py` 及其契约测试，使干净检出恢复可验证基线；该修复不扩展审批能力。

```

## openspec/changes/bind-http-remote-action-approvals/design.md

- Source: openspec/changes/bind-http-remote-action-approvals/design.md
- Lines: 1-95
- SHA256: 19c6d779de67c41a1bfa72507a3bd87607f0f6d64df98542981de89c1621a152

[TRUNCATED]

```md
## Context

HTTP Task Service 当前以 Bearer token 和 loopback-only listener 作为控制面边界。`HeadlessConfirmer` 只接受启动时静态 exact allowlist；MCP 受保护动作在确认后由 `ExternalActionReceiptStore` 记录 `prepared -> dispatched -> confirmed|unknown`，但 HTTP 客户端不能签发一次性审批、撤销未使用审批或显式 reconcile receipt。

M44 只扩展已认证的本地控制面。它不把 HTTP listener 暴露到非 loopback，也不把审批权交给模型、任务 goal、工具参数、MCP server 或静态配置热更新。

干净 HEAD 还存在一个独立基线缺口：多个已提交模块导入 `forgeagent.attention`，但该文件和测试未被纳入 Git。实施前需补入现有权威实现，使基线可收集；这不是审批协议的一部分。

## Goals / Non-Goals

**Goals:**

- 让已认证 HTTP 调用者预先签发一个精确、短期、一次性的 MCP 动作审批。
- 在任务提交时由 `TaskService` 原子地把审批绑定到新任务；模型不能选择、扩大或转移审批。
- 在 MCP dispatch 前按 `task_id + action type + exact scope + canonical request digest + expiry` 原子消费一次。
- 支持审批查询、撤销和确定性的撤销/消费竞态。
- 通过 HTTP 按任务列出未决 receipt，并显式确认、放弃或允许新尝试；任何操作都不 dispatch。
- 提供真实 loopback socket verifier，证明从审批签发到 receipt 恢复的完整路径。

**Non-Goals:**

- 非 loopback 监听、TLS、反向代理、Gateway、多租户身份或细粒度 RBAC。
- 通配 scope、批量永久授权、审批续期、跨进程审批持久化或审批转移。
- 为 FileWrite/WebFetch 增加 receipt 或远程一次性审批；M44 仅覆盖已有 receipt 语义的 MCP 动作。
- 自动重新运行普通任务、自动恢复 Loop、自动确认外部结果或自动重放原动作。

## Decisions

### 1. 审批与 receipt 分离

新增宿主拥有的进程内 `HttpActionApprovalStore`。审批回答“是否允许这次 dispatch”，receipt 回答“dispatch 实际发生到哪一步”。二者不能合并：审批可在 dispatch 前撤销或过期，而 receipt 必须在进程重启后保留执行证据。

审批状态为 `issued -> bound -> consumed`，以及终态 `revoked|expired`。只支持 `mode=allow_once`。记录包含版本化 schema、32 位 approval ID、`action_type=mcp`、规范化 scope、64 位 request digest、有效期和可选 task ID；不包含 goal、原始 arguments、prompt、路径、credential 或异常正文。

替代方案“把审批字段写进 receipt”被拒绝，因为它会让未批准候选污染执行证据并破坏既有 receipt phase 不变量。

### 2. 先签发，提交时原子绑定

控制面流程为：

1. `POST /action-approvals` 以 server/tool、canonical digest、`allow_once` 和有限 TTL 签发 `issued` 记录。
2. `POST /tasks` 可附带最多 16 个唯一 `approval_ids`。HTTP parser 将其与普通 task options 分离。
3. `TaskService` 生成 task ID 后、发布任务和启动 worker 前，一次性校验并绑定全部审批。任一审批未知、过期、非 `issued` 时整个提交失败，且不创建任务、不部分绑定。
4. worker 结束、排队取消、调度失败或 shutdown 时，所有仍为 `bound` 的审批转为 `revoked`；`consumed` 不可回退。

不采用“运行后补审批并重新运行原任务”，因为普通任务没有安全 checkpoint，重跑可能重复早先副作用。Loop 恢复仍由现有显式 resume 完成，并在新的 resume submission 上绑定新的审批。

### 3. dispatch 前精确消费

`HeadlessConfirmer` 保留现有启动时 exact allowlist。仅当静态 allowlist 未命中且参数是 MCP 动作时，它才请求 store 消费与当前 task 完全匹配的 `bound` 审批。scope 复用现有严格 `mcp/<server>/<tool>` 规范化；digest 复用 `canonical_request_digest(args.arguments)`。

消费与撤销在同一 store lock 下串行：先取得锁的一方决定结果。消费成功后审批立即为 `consumed`，即使后续 receipt 持久化失败也不恢复额度；这是 fail-closed，且避免同一 grant 二次 dispatch。静态 allowlist 行为不变，但 HTTP 动态审批必定经过 digest 检查。

### 4. 有界 HTTP 契约

新增认证路由：

- `POST /action-approvals`：严格签发，TTL 为 1-3600 秒。
- `GET /action-approvals/{approval_id}`：返回固定公开字段。
- `POST /action-approvals/{approval_id}/revoke`：空 body，幂等返回当前终态；不能撤销已消费动作。
- `GET /tasks/{task_id}/receipts`：只返回属于该 retained task 的 open receipts 的有界公开投影。
- `POST /tasks/{task_id}/receipts/{action_id}/resolve`：携带 expected revision 和 `confirmed|abandoned|retry_approved` 决策；confirmed 必须有有界 evidence。

错误只使用固定 kind/detail。未知 ID、跨任务 action、stale revision、过期审批和状态冲突不返回原始记录或异常。所有路由继续使用相同 Bearer token、body 限制、origin-form target 和 no-store 响应。

### 5. reconcile 不等于 replay

HTTP reconcile 只调用现有 receipt store 的 CAS transition。`confirmed` 记录权威外部证据，`abandoned` 关闭未决动作，`retry_approved` 仅允许未来建立新 action ID；三者均不调用 MCP。未来新尝试仍需新的有效审批或现有静态 allowlist，并生成新 receipt。

### 6. 公开投影与审计

审批公开面只包含 approval ID、action type、规范化 scope、digest、mode、status、到期时间和绑定 task ID。receipt 公开面沿用已掩码的 labels/digest/phase/resolution/revision/evidence code；不返回原始 arguments。

审计事件只记录固定 event type、稳定 ID、状态、scope/digest 等有界元数据，不记录 Bearer token、goal、prompt、raw arguments、evidence 正文、绝对路径或 raw exception。运行时审计失败沿用现有 degraded 语义，不改变审批/receipt 的权威状态。

## Risks / Trade-offs

- **[进程重启会丢失未消费审批]** -> 审批本来就是短期能力；重启后客户端重新签发。receipt 仍持久化，未知执行事实不会丢失。
- **[客户端必须预先知道 canonical arguments digest]** -> 这是精确绑定的代价；文档和 verifier 固定 canonical JSON 规则，不接受通配或服务器代存原始 arguments。
- **[审批消费后 receipt 写入失败会浪费额度]** -> 选择 fail-closed，不恢复已消费 grant；客户端可签发新 grant，不存在隐式执行。

```

Full source: openspec/changes/bind-http-remote-action-approvals/design.md

## openspec/changes/bind-http-remote-action-approvals/tasks.md

- Source: openspec/changes/bind-http-remote-action-approvals/tasks.md
- Lines: 1-21
- SHA256: d27deab7c715f2e7ba4c7d28c78422998e4a3934f58cc26acc619519ab9b8d3b

```md
## 1. 基线与协议状态机

- [ ] 1.1 补入已被现有模块引用的 `attention.py` 和契约测试，重跑 M44 聚焦基线并记录原始缺失原因。
- [ ] 1.2 以 RED/GREEN 测试实现有界 `HttpActionApprovalStore`，覆盖严格字段、全有或全无任务绑定、一次性消费、过期、撤销竞态、容量和安全公开投影。

## 2. 执行边界接入

- [ ] 2.1 以测试证明 `HeadlessConfirmer` 只在静态 allowlist 未命中时消费当前任务精确匹配的 MCP scope/digest 审批，且拒绝错 task/scope/digest、过期和复用。
- [ ] 2.2 让 `TaskService` 在 worker 发布前认领审批，并在拒绝、调度失败、取消、终态和 shutdown 时关闭未消费绑定，不把审批 ID 传给模型或普通 options。

## 3. HTTP 控制面与 receipt 恢复

- [ ] 3.1 增加严格认证的审批签发、查询、撤销路由和任务 `approval_ids` 解析，保持旧请求/错误/loopback-only 契约。
- [ ] 3.2 增加按 retained task 列出 open receipts 和 CAS reconcile 路由，覆盖跨任务、stale revision、evidence、无自动 dispatch 与固定错误。
- [ ] 3.3 在 HTTP CLI 组装中向 confirmer 与 TaskService 注入同一审批/receipt 权威实例，并验证资源生命周期。

## 4. 验证、文档与里程碑

- [ ] 4.1 增加真实 loopback verifier，覆盖审批签发、任务绑定、一次消费、receipt 确认和 unknown 显式恢复，并扫描公开面无 secret、goal、raw arguments、路径或异常泄漏。
- [ ] 4.2 更新 HTTP/threat-model 文档，完成两轮代码与契约自审，修复发现后通过聚焦/全量 pytest、Ruff、format、OpenSpec strict 和 Comet verify。
- [ ] 4.3 同步主规格、归档 change，产出 M44 里程碑记录并推送开发分支；不执行 PyPI、tag 或发布自动化。

```

## openspec/changes/bind-http-remote-action-approvals/specs/external-action-receipts/spec.md

- Source: openspec/changes/bind-http-remote-action-approvals/specs/external-action-receipts/spec.md
- Lines: 1-16
- SHA256: a31636d6b5f92554028273554b5588cc22e0153a142d65d05ecdbae3771409d0

```md
## ADDED Requirements

### Requirement: Authenticated HTTP reconciliation preserves receipt authority
ForgeAgent SHALL permit its authenticated loopback HTTP control plane to read bounded open receipt projections and apply explicit reconciliation decisions through the authoritative receipt store. HTTP reconciliation MUST use the current receipt revision, MUST preserve receipt history, and MUST NOT dispatch, retry, resume, or fabricate delivery evidence.

#### Scenario: HTTP confirmation records external evidence only
- **WHEN** an authenticated caller confirms an open receipt with the current revision and bounded evidence
- **THEN** ForgeAgent updates only the receipt resolution/evidence and does not call the external server

#### Scenario: HTTP retry approval does not replay
- **WHEN** an authenticated caller marks an open receipt `retry_approved`
- **THEN** ForgeAgent closes the original receipt without dispatch and requires a separate future action with a new ID and valid authorization

#### Scenario: Process restarts after an unknown action
- **WHEN** a durable `unknown` receipt remains after restart while process-local action approvals have disappeared
- **THEN** the HTTP control plane can reconcile the receipt explicitly, but it cannot reconstruct or silently replay the expired approval

```

## openspec/changes/bind-http-remote-action-approvals/specs/http-action-approvals/spec.md

- Source: openspec/changes/bind-http-remote-action-approvals/specs/http-action-approvals/spec.md
- Lines: 1-47
- SHA256: e2f545c709e62ad38a0798b000f94b1245da27c9fac9ada9fbdbcd3e551ff5da

```md
## ADDED Requirements

### Requirement: HTTP action approvals bind exact authority
ForgeAgent SHALL let an authenticated HTTP caller issue only short-lived `allow_once` approvals for an exact MCP action scope and canonical request digest. The host MUST bind every approval to exactly one newly accepted task before execution, and the model, goal, tool output, MCP server, or task options MUST NOT widen or transfer that authority.

#### Scenario: Exact approval is bound during task submission
- **WHEN** a caller issues an approval for one normalized MCP server/tool scope and request digest and submits its unique ID with a valid task
- **THEN** the host atomically binds the approval to the new server-owned task ID before scheduling the worker

#### Scenario: One approval in a submission is unavailable
- **WHEN** any supplied approval ID is unknown, duplicated, expired, revoked, consumed, or already bound
- **THEN** ForgeAgent rejects the entire submission without creating a task or partially binding any approval

#### Scenario: Model attempts to change approved authority
- **WHEN** an MCP call differs in task ID, action type, normalized scope, or canonical request digest
- **THEN** the approval does not match and ForgeAgent does not consume it or dispatch under it

### Requirement: Allow-once expiry and revocation are deterministic
Every HTTP action approval MUST have a bounded expiry and MUST authorize at most one dispatch. Expiry, revocation, and consumption MUST be serialized by the host; terminal approvals MUST NOT become active again.

#### Scenario: Matching approval is consumed once
- **WHEN** the bound task reaches an MCP dispatch whose exact scope and digest match an unexpired approval
- **THEN** ForgeAgent atomically marks the approval consumed before dispatch and refuses to use it for any later call

#### Scenario: Approval expires before consumption
- **WHEN** the approval deadline passes while the approval is issued or bound
- **THEN** ForgeAgent marks it expired and does not dispatch under it

#### Scenario: Revocation wins the race
- **WHEN** revocation acquires the approval state lock before a matching dispatch consumes the approval
- **THEN** the approval becomes revoked and the dispatch is denied

#### Scenario: Consumption wins the race
- **WHEN** a matching dispatch consumes the approval before revocation acquires the approval state lock
- **THEN** revocation reports the consumed terminal state and does not claim to undo the action

### Requirement: Approval state has a bounded safe projection
Approval APIs and audit events MUST expose only fixed, bounded metadata and MUST NOT expose bearer tokens, goals, prompts, raw tool arguments, evidence text, credentials, raw exceptions, or absolute host paths. The in-memory approval registry MUST be bounded and MUST fail closed at capacity.

#### Scenario: Caller queries an approval
- **WHEN** an authenticated caller queries a retained approval ID
- **THEN** ForgeAgent returns only its ID, action type, normalized scope, digest, mode, status, expiry and optional bound task ID

#### Scenario: Approval registry is at capacity
- **WHEN** no terminal record can be evicted and a caller tries to issue another approval
- **THEN** ForgeAgent returns a stable capacity error and creates no partial approval


```

## openspec/changes/bind-http-remote-action-approvals/specs/http-task-service/spec.md

- Source: openspec/changes/bind-http-remote-action-approvals/specs/http-task-service/spec.md
- Lines: 1-40
- SHA256: 50452c1a3b1d5f0f70cf9bdf8e7ca700bf1ba9ac8a9d1e472a665f118e760f15

```md
## ADDED Requirements

### Requirement: Authenticated HTTP callers manage one-time action approvals
The HTTP task service SHALL expose authenticated endpoints to issue, query, and revoke bounded `allow_once` MCP approvals and SHALL accept a bounded list of approval IDs during task submission. These routes MUST preserve the existing Bearer authentication, origin-form, body-size, no-store, loopback-only, and fixed-error boundaries.

#### Scenario: Valid approval lifecycle over HTTP
- **WHEN** an authenticated caller issues a valid exact approval, queries it, and revokes it before use
- **THEN** the service returns deterministic safe projections and the revoked approval cannot authorize a task action

#### Scenario: Task claims approvals
- **WHEN** an authenticated task submission includes a valid bounded list of issued approval IDs
- **THEN** the service binds all of them to the created task before worker publication and does not pass those IDs to the model or ordinary task options

#### Scenario: Approval fields appear in an unsupported location
- **WHEN** a client places approval scope, digest, expiry, or authority fields in goal text, ordinary options, Loop resume fields, or any schema location other than the documented approval endpoints and approval ID list
- **THEN** the service rejects or ignores them as data and grants no authority

#### Scenario: Listener configuration attempts remote exposure
- **WHEN** action approval endpoints are enabled while the configured bind address is not loopback
- **THEN** service startup still fails closed and exposes no listener

### Requirement: HTTP receipt recovery is explicit and task-scoped
The HTTP task service SHALL let an authenticated caller list open external-action receipts for one retained task and apply an explicit compare-and-swap reconciliation decision. It MUST NOT expose receipts owned by another task, raw arguments, or an automatic replay operation.

#### Scenario: List one task's pending receipts
- **WHEN** an authenticated caller lists receipts for a retained task
- **THEN** the service returns only bounded public fields for open receipts whose authoritative task ID matches the route

#### Scenario: Resolve an unknown receipt with evidence
- **WHEN** an authenticated caller supplies the current revision, the `confirmed` decision, and bounded evidence for an unknown receipt owned by the task
- **THEN** the service records the resolution and returns the updated safe projection without invoking MCP

#### Scenario: Abandon or permit a new attempt
- **WHEN** an authenticated caller chooses `abandoned` or `retry_approved` for an open task-owned receipt at its current revision
- **THEN** the service records that decision without dispatch, and any future attempt requires a new action ID and independent authorization

#### Scenario: Receipt does not match route authority
- **WHEN** the action ID is unknown, belongs to a different task, is already resolved, or has a stale revision
- **THEN** the service returns a fixed non-disclosing not-found or conflict error and performs no transition


```
