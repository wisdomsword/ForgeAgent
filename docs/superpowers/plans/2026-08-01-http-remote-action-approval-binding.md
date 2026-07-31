---
change: bind-http-remote-action-approvals
design-doc: docs/superpowers/specs/2026-08-01-http-remote-action-approval-binding-design.md
base-ref: 6b5b2476c1369f37f1c01c89c55d83fb0f1ab47a
---

# M44 HTTP Remote Action Approval Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 loopback HTTP 控制面增加精确、短期、一次性的 MCP 动作审批，以及不自动重放的 task-scoped receipt 恢复接口。

**Architecture:** 进程内 `HttpActionApprovalStore` 管授权额度，现有 `ExternalActionReceiptStore` 管执行事实。HTTP 先签发 grant，任务提交全有或全无绑定，`HeadlessConfirmer` 在 dispatch 前精确消费；receipt HTTP API 只做显式 CAS transition。

**Tech Stack:** Python 3.12+、Pydantic v2、标准库 `http.server`/threading、pytest、Ruff、OpenSpec/Comet；不新增依赖。

## Global Constraints

- HTTP listener 必须继续只允许 loopback IP；不增加 TLS、Gateway、反向代理或公网入口。
- 动态审批仅覆盖 MCP，必须绑定 task ID、exact scope、canonical digest、1-3600 秒 TTL 和 `allow_once`。
- 审批与 receipt 分离；reconcile、resume、retry 和启动过程都不得自动 dispatch。
- HTTP/审计不得泄漏 secret、Bearer token、goal、prompt、raw arguments、evidence 正文、绝对路径或 raw exception。
- 保持旧 task 请求、静态 allowlist、CLI/REPL autoApprove 和 receipt 磁盘 schema 兼容。
- 不执行 PyPI、tag 或发布自动化。

---

### Task 1: 恢复干净检出基线

**Files:**
- Create: `src/forgeagent/attention.py`
- Create: `tests/test_attention.py`
- Modify: `src/forgeagent/skills.py`
- Modify: `openspec/changes/bind-http-remote-action-approvals/tasks.md`

**Interfaces:**
- Consumes: 已提交调用方对 `Attention` 与 `attention_for_reason(reason, detail)` 的引用。
- Produces: `Attention(state, reason, owner, required_action, recovery)` 和安全公开映射。
- Produces: 已提交 Skill v2 exit-condition 测试依赖的解析、渲染和安全校验实现。

- [x] **Step 1: 复制主工作区现有权威 attention 契约测试到隔离 worktree**

测试必须覆盖 `None/completed/needs_info/blocked/external_action_pending` 映射、secret/path/control masking、500 字符边界和 extra/invalid reason 拒绝。

- [x] **Step 2: 运行失败基线并确认根因**

Run: `uv run pytest -q tests/test_attention.py tests/test_http_server.py tests/test_http_task_service.py`

Expected: collection FAIL，`ModuleNotFoundError: No module named 'forgeagent.attention'`。

- [x] **Step 3: 补入最小权威实现**

实现 `AttentionState`、`AttentionOwner`、严格 Pydantic model、`_public_text()` 和 `attention_for_reason()`；逻辑与已提交调用方期望一致，不合并主工作区其他文件。

- [x] **Step 4: 验证基线恢复**

Run: `uv run pytest -q tests/test_attention.py tests/test_http_server.py tests/test_http_task_service.py tests/test_external_actions.py tests/test_tools.py`

Expected: PASS，无 collection error。

- [x] **Step 5: 提交基线修复**

```bash
git add src/forgeagent/attention.py tests/test_attention.py openspec/changes/bind-http-remote-action-approvals
git commit -m "fix: restore attention state contract"
```

### Task 2: 实现审批状态机

**Files:**
- Create: `src/forgeagent/http_action_approvals.py`
- Create: `tests/test_http_action_approvals.py`
- Modify: `src/forgeagent/headless.py`

**Interfaces:**
- Consumes: `headless.mcp_operation_key(server, tool)` 与 `AuditSink`。
- Produces: `HttpActionApproval`, `HttpActionApprovalStore.issue/get/bind_many/consume/revoke/release_task`，以及 fixed exception types。

- [x] **Step 1: 写严格 schema、签发和安全投影失败测试**

测试 API：

```python
store = HttpActionApprovalStore(max_records=2, clock=clock)
record = store.issue(
    server="github",
    tool="create_issue",
    request_digest="a" * 64,
    expires_in_seconds=60,
)
assert record.status == "issued"
assert set(record.public_view()) == {
    "schema", "approval_id", "action_type", "scope", "request_digest",
    "mode", "status", "task_id", "issued_at", "expires_at",
}
```

另断言非法 segment/digest/TTL、extra 字段和容量 fail closed。

- [x] **Step 2: 运行 RED**

Run: `uv run pytest -q tests/test_http_action_approvals.py`

Expected: FAIL，因为模块/API 不存在。

- [x] **Step 3: 实现 record、异常和 bounded issue/get**

固定状态 `issued|bound|consumed|revoked|expired`；schema alias 为 `forgeagent.http-action-approval.v1`；registry 达容量时只淘汰 terminal，无法淘汰则抛 `ApprovalCapacityError`。

- [x] **Step 4: 写 bind/consume/expiry/revoke/release RED 测试**

覆盖：多 ID 全有或全无、duplicate、wrong state；精确 task/scope/digest；一次消费；fake clock 过期；revoked 不消费；release 只关闭 bound；两个线程由 barrier 验证消费/撤销只能一方先改变状态。

- [x] **Step 5: 最小实现状态迁移并跑 GREEN**

Run: `uv run pytest -q tests/test_http_action_approvals.py`

Expected: PASS。

- [x] **Step 6: 提交状态机**

```bash
git add src/forgeagent/http_action_approvals.py src/forgeagent/headless.py tests/test_http_action_approvals.py
git commit -m "feat: add bounded HTTP action approvals"
```

### Task 3: 将一次性审批接入 HeadlessConfirmer

**Files:**
- Modify: `src/forgeagent/headless.py`
- Modify: `tests/test_headless.py`
- Modify: `tests/test_tools.py`

**Interfaces:**
- Consumes: `HttpActionApprovalStore.consume(task_id, scope, request_digest)`、`canonical_request_digest()`。
- Produces: `HeadlessConfirmer(..., approval_store=None)`，静态 allowlist 优先，动态 MCP exact consume 次之。

- [x] **Step 1: 写动态 exact consume RED 测试**

签发并绑定 grant，调用 `confirm_with_context(MCPArgs(...), task_id=...)`；断言 exact 为 True 且 status=consumed，第二次 False。分别修改 task/server/tool/arguments 后必须 False 且 grant 仍 bound。

- [x] **Step 2: 运行 RED**

Run: `uv run pytest -q tests/test_headless.py tests/test_tools.py -k 'approval or headless_mcp'`

Expected: FAIL，因为 confirmer 尚未接收/消费 store。

- [x] **Step 3: 实现最小接入**

在静态 allowlist 不命中、`MCPArgs`、task ID 非空且 store 可用时调用 consume。动态命中审计 `result_status=allow_once`；FileWrite/WebFetch 不进入此分支。

- [x] **Step 4: 验证 MCP dispatch/receipt 边界**

测试 `MCPTool` 对 exact grant 只调用 fake MCP 一次并创建 confirmed receipt；wrong/expired/reused 时调用次数不增加；receipt store 失败时 grant consumed 但 dispatch 为零。

Run: `uv run pytest -q tests/test_headless.py tests/test_tools.py tests/test_external_actions.py`

Expected: PASS。

- [x] **Step 5: 提交 confirmer 接入**

```bash
git add src/forgeagent/headless.py tests/test_headless.py tests/test_tools.py
git commit -m "feat: consume exact approvals before MCP dispatch"
```

### Task 4: TaskService 认领与清理审批

**Files:**
- Modify: `src/forgeagent/http_task_service.py`
- Modify: `tests/test_http_task_service.py`

**Interfaces:**
- Consumes: `HttpActionApprovalStore.bind_many/release_task`。
- Produces: `TaskRecord.approval_ids` 私有字段；`submit/submit_view(..., approval_ids=())`；approval/receipt service wrappers。

- [x] **Step 1: 写原子认领 RED 测试**

断言 valid IDs 在 factory 运行前均为 bound 且 task ID 匹配；invalid second ID 时 first 保持 issued、records 不增加；options/public view 不含 approval IDs。

- [x] **Step 2: 运行 RED**

Run: `uv run pytest -q tests/test_http_task_service.py -k 'approval'`

Expected: FAIL，因为 TaskService 没有 approval store/参数。

- [x] **Step 3: 实现 bind-before-publish**

构造函数注入可选 approval/receipt stores；在 service lock 内完成容量/loop 检查、task ID 生成和 bind，再发布 record/worker。所有既有调用使用默认空 IDs 保持兼容。

- [x] **Step 4: 写生命周期清理与 receipt wrapper RED 测试**

覆盖 executor submit raise、loop conflict、queued cancel、worker terminal、shutdown；未消费 grant 均 revoked，consumed 不变。receipt list 只返回当前 task open records；cross-task/stale resolve 固定失败；resolve 不调用任何 MCP seam。

- [x] **Step 5: 实现 release 和 service wrappers，跑 GREEN**

Run: `uv run pytest -q tests/test_http_task_service.py tests/test_external_actions.py`

Expected: PASS。

- [x] **Step 6: 提交 TaskService 接入**

```bash
git add src/forgeagent/http_task_service.py tests/test_http_task_service.py
git commit -m "feat: bind approvals to HTTP tasks"
```

### Task 5: 实现 HTTP 路由与严格请求解析

**Files:**
- Modify: `src/forgeagent/http_server.py`
- Modify: `tests/test_http_server.py`

**Interfaces:**
- Consumes: TaskService approval/receipt wrappers。
- Produces: `/action-approvals`、approval query/revoke、task receipt list/resolve 路由和 `approval_ids` task extension。

- [x] **Step 1: 写 parser/routes RED 测试**

覆盖 issue strict keys/TTL/digest/mode、auth、method、empty revoke；approval get/revoke；所有原 task shape + approval IDs；空/超 16/duplicate/invalid ID；旧 `_parse_task_submission()` 两值兼容。

- [x] **Step 2: 运行 RED**

Run: `uv run pytest -q tests/test_http_server.py -k 'approval'`

Expected: FAIL，路由不存在或请求被 invalid_request 拒绝。

- [x] **Step 3: 实现 approval 路由和 task parser**

新增 path regex/fixed error detail；`_parse_task_request()` 返回 `(goal, options, approval_ids)`，旧 helper 委托后仍返回两值。handler 不记录 body。

- [x] **Step 4: 写 receipt routes RED 测试**

覆盖 retained task 与 restart durable-receipt ownership、open list、unknown confirmed + evidence、abandoned/retry、cross-task 404、stale 409、invalid decision 400，并用 counting fake 证明 resolve 前后 dispatch count 不变。

- [x] **Step 5: 实现 receipt routes 并跑完整 HTTP GREEN**

Run: `uv run pytest -q tests/test_http_server.py tests/test_http_task_service.py`

Expected: PASS；旧 HTTP 矩阵保持通过。

- [x] **Step 6: 提交 HTTP 契约**

```bash
git add src/forgeagent/http_server.py tests/test_http_server.py
git commit -m "feat: expose approval and receipt control endpoints"
```

### Task 6: 组装、真实 verifier、文档和聚焦门禁

**Files:**
- Modify: `src/forgeagent/_cli_http.py`
- Modify: `tests/test_cli.py`
- Create: `scripts/m44_http_action_approval_smoke.py`
- Create: `tests/test_m44_http_action_approval_smoke.py`
- Modify: `docs/http-task-service.md`
- Modify: `docs/threat-model.md`
- Modify: `openspec/changes/bind-http-remote-action-approvals/tasks.md`

**Interfaces:**
- Consumes: 同一 `HttpActionApprovalStore` 与 `ExternalActionReceiptStore` 实例。
- Produces: production wiring、可独立运行的真实 loopback verifier 和用户文档。

- [x] **Step 1: 写 CLI wiring RED 测试**

注入 recording bindings，断言 approval store 只创建一次并同时传给 confirmer/TaskService；receipt store 同一实例传给 Task/Loop 和 service；startup 失败仍关闭 MCP/service。

- [x] **Step 2: 实现 production wiring 并验证**

Run: `uv run pytest -q tests/test_cli.py -k 'serve and approval'`

Expected: PASS。

- [x] **Step 3: 先写 verifier 契约测试再实现脚本**

测试用 subprocess 运行脚本并解析单一 JSON：`approval_status=consumed`、`dispatch_count=1`、`receipt_phase=confirmed`、`unknown_resolution=confirmed`、`reconcile_dispatch_delta=0`，且输出不含 temp absolute path、secret、goal、arguments 或 traceback。

Run: `uv run pytest -q tests/test_m44_http_action_approval_smoke.py`

Expected first: FAIL，因为脚本不存在；实现后 PASS。

- [x] **Step 4: 更新 HTTP/threat model 文档**

记录 canonical digest 规则、API 示例、进程内 expiry/重启语义、撤销竞态、receipt reconcile 无 replay、loopback-only 和残余风险。

- [x] **Step 5: 运行聚焦门禁并勾选 build tasks**

```bash
uv run pytest -q tests/test_attention.py tests/test_http_action_approvals.py tests/test_headless.py tests/test_tools.py tests/test_external_actions.py tests/test_http_task_service.py tests/test_http_server.py tests/test_cli.py tests/test_m44_http_action_approval_smoke.py
uv run ruff check src/forgeagent tests scripts
uv run ruff format --check src/forgeagent tests scripts
openspec validate bind-http-remote-action-approvals --strict --no-interactive
```

Expected: 全部 PASS；然后更新 `tasks.md` 1.1-4.1 的 checkbox。

- [x] **Step 6: 提交组装与聚焦验证**

```bash
git add src/forgeagent/_cli_http.py tests/test_cli.py scripts/m44_http_action_approval_smoke.py tests/test_m44_http_action_approval_smoke.py docs/http-task-service.md docs/threat-model.md openspec/changes/bind-http-remote-action-approvals
git commit -m "feat: complete HTTP action approval binding"
```

### Task 7: 自审、全量验证与 build 收口

**Files:**
- Create: `docs/superpowers/reports/2026-08-01-http-remote-action-approval-binding-verify.md`
- Modify: `openspec/changes/bind-http-remote-action-approvals/tasks.md`

**Interfaces:**
- Consumes: `base-ref..HEAD` 全部 M44 diff。
- Produces: 两轮自审证据、全量门禁结果和 build-complete 状态。

- [x] **Step 1: 第一轮 fresh diff 审查**

按信任边界、状态迁移、竞态、兼容、泄漏、错误投影、资源生命周期逐文件审查 `git diff 6b5b2476..HEAD`；发现问题先写回归测试，观察 RED 后修复。

- [x] **Step 2: 第二轮从 OpenSpec 场景反向审查**

逐个 requirement/scenario 映射到测试名；扫描 wildcard、raw body logging、auto replay、non-loopback weakening、approval IDs 进入 options/checkpoint。所有发现立即修复并重跑聚焦测试。

- [x] **Step 3: 运行零排除全量门禁**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
openspec validate --all --strict --no-interactive
```

Expected: 全部 PASS；无 xfail/新增 skip 掩盖 M44。

- [x] **Step 4: 写验证报告并完成 tasks**

报告记录基线 collection 失败、RED/GREEN 命令、聚焦/全量计数、两轮自审发现与修复、公开面扫描、未执行发布操作。勾选 4.2；4.3 留给 archive 阶段最终完成。

- [x] **Step 5: 提交验证证据**

```bash
git add docs/superpowers/reports/2026-08-01-http-remote-action-approval-binding-verify.md openspec/changes/bind-http-remote-action-approvals/tasks.md
git commit -m "docs: record M44 verification evidence"
```
