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
- **[撤销与 dispatch 竞态]** -> store lock 给出确定顺序；若先消费，撤销返回 `consumed`，调用者转而检查 receipt。
- **[共享 receipt store 与 TaskService 生命周期不同]** -> HTTP 组装向两者注入同一 store 实例；service 只读/transition，进程 owner 负责最终关闭。
- **[基线缺失 attention 模块]** -> 先补入已被调用方依赖的最小模块和测试，再重跑原聚焦基线；不顺带合并主工作区其他改动。

## Migration Plan

1. 补齐 attention 基线文件并确认聚焦测试可收集。
2. 先加入审批 store 的纯状态机测试，再接入 HeadlessConfirmer 与 TaskService 原子绑定。
3. 增加 HTTP parser/routes 和 receipt reconcile 测试；旧请求体和旧 allowlist 测试必须保持通过。
4. 运行真实 loopback verifier，随后执行全量 pytest、Ruff、format 和 OpenSpec strict。
5. 回滚时删除新增路由和审批注入即可恢复静态 allowlist-only；receipt 文件 schema 未变化，无数据回滚。

## Open Questions

无。跨进程审批持久化、非 loopback transport security 和其他工具类型审批必须另立 change。
