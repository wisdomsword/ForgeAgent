---
change: http-task-service
design-doc: docs/superpowers/specs/2026-07-21-http-task-service-design.md
base-ref: e02c5104ef30e19433fc88562e9d7cc78a330130
---

# M16 HTTP Task Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在严格 loopback/token 信任边界下提供有界异步 HTTP 任务服务、协作取消、安全结果投影、headless allowlist 确认门和 JSONL 审计日志，同时保持现有 CLI/Task API 行为不变。

**Architecture:** 新增标准库 HTTP 适配层、`TaskService` 注册表和注入式 `AuditSink`。HTTP handler 只负责认证、解析和序列化；worker 通过服务端 task factory 创建现有 `Task`，共享 Step/工具/sandbox 语义。HTTP confirmer 使用精确 allowlist，显式关闭 MCP `autoApprove` 继承；取消通过 `threading.Event` 在 Step 轮次和工具边界协作完成。

**Tech Stack:** Python 3.11 标准库 `http.server.ThreadingHTTPServer`、`threading`、`concurrent.futures`、`json`、`pathlib`；现有 Pydantic、pytest、ruff；不新增运行时依赖。

## Global Constraints

- HTTP 仅允许 loopback bind；非 loopback 地址在配置校验时拒绝；M16 不提供 TLS。
- bearer token 从 `FORGEAGENT_HTTP_TOKEN` 或用户配置读取，环境变量优先；空白 token 拒绝启动，token 不写日志/响应。
- HTTP body 默认上限 64 KiB，结果 detail/列表元素有字符和字节上限；不得返回 prompt、模型原文、工具参数、文件内容或 host path。
- HTTP 请求 schema 只允许 `goal` 和明确的低风险选项；客户端不得覆盖 tier、backend、allowed root、container、identity、confirmer、凭据或 MCP 策略。
- 服务默认最多 4 个 worker、32 个排队任务、256 条保留记录，终态 TTL 默认 1 小时；上限由服务端配置持有。
- `Termination.CANCELLED` 是独立终态；终态发布使用一次性锁/CAS，取消不强杀正在执行的线程。
- HTTP allowlist 是 HTTP 唯一预授权路径；HTTP 不读取 MCP `autoApprove`，该兼容语义仅保留给 CLI/REPL。
- 审计运行时写入失败采用 fail-open，设置 degraded 标志且响应不得声称事件已持久化；启动时无法打开审计路径则拒绝启动服务。
- 所有敏感字段在 JSON 序列化前复用 `secret_policy` 掩码；每个逻辑 tool、每次模型 attempt/outcome、每次确认和 HTTP lifecycle 操作各写一条事件。
- 既有直接 `Task(...)`、CLI、golden runner 和 MCP 配置行为必须保持兼容。

## 文件与边界

- `src/forgeagent/http_config.py`：`HttpServiceConfig`、环境变量/配置装配、loopback/token/上限校验。
- `src/forgeagent/audit.py`：`AuditEvent`、注入式 sink、JSONL append/轮转/掩码/degraded 状态。
- `src/forgeagent/headless.py`：HTTP allowlist 规范化及 `HeadlessConfirmer`，不继承 `autoApprove`。
- `src/forgeagent/http_task_service.py`：`TaskRecord`、有界注册表、worker 生命周期、取消、TTL/容量和安全结果投影。
- `src/forgeagent/http_server.py`：`ThreadingHTTPServer`、handler、鉴权、路由、请求/响应边界和 lifecycle 埋点。
- `src/forgeagent/task.py`、`src/forgeagent/step.py`：新增取消原语、可选 task-scoped audit sink 并保持旧调用默认行为；Step 记录模型 request attempt/outcome。
- `src/forgeagent/tools.py`、`src/forgeagent/mcp_manager.py`：注入可选 audit context，记录逻辑 tool/confirmation 事件；区分 HTTP headless 与 CLI 的确认策略，保留 CLI `autoApprove`。
- `src/forgeagent/cli.py`、`src/forgeagent/__init__.py`：opt-in 服务入口和公共导出，不改变默认 CLI。
- `tests/test_http_config.py`、`tests/test_audit.py`、`tests/test_headless.py`、`tests/test_http_task_service.py`、`tests/test_http_server.py`：按边界覆盖单元/集成测试。
- `README.md`、`docs/threat-model.md`、`docs/http-task-service.md`：运行、配置、审计和安全边界文档。

---

### Task 1: 配置与取消核心契约

**Files:**
- Create: `src/forgeagent/http_config.py`
- Modify: `src/forgeagent/task.py`
- Modify: `src/forgeagent/step.py`
- Test: `tests/test_http_config.py`
- Test: `tests/test_task.py`
- Test: `tests/test_step.py`

**Interfaces:**
- Produces `HttpServiceConfig.from_sources(config: Mapping[str, object] | None = None, env: Mapping[str, str] | None = None) -> HttpServiceConfig`。
- Produces `Task.run(goal, *, images=None, cancel_event: threading.Event | None = None)` and `Step(..., cancel_event: threading.Event | None = None)`；`None` 保持现有行为。

- [x] **Step 1: 写配置和 loopback/token 的失败测试**

```python
def test_http_config_rejects_missing_token():
    with pytest.raises(ValueError, match="token"):
        HttpServiceConfig.from_sources(config={"port": 8765}, env={})

def test_http_config_rejects_non_loopback_and_env_wins():
    with pytest.raises(ValueError, match="loopback"):
        HttpServiceConfig.from_sources(
            config={"bind_host": "0.0.0.0", "token": "file-token"}, env={}
        )
    cfg = HttpServiceConfig.from_sources(
        config={"token": "file-token"}, env={"FORGEAGENT_HTTP_TOKEN": "env-token"}
    )
    assert cfg.token == "env-token"
```

- [x] **Step 2: 实现最小配置模型和来源优先级**

```python
@dataclass(frozen=True)
class HttpServiceConfig:
    bind_host: str = "127.0.0.1"
    port: int = 8765
    token: str = ""
    max_workers: int = 4
    max_queue: int = 32
    max_records: int = 256
    terminal_ttl_seconds: float = 3600.0
    max_body_bytes: int = 64 * 1024
    audit_path: Path = Path("~/.forgeagent/http-audit.jsonl")
    audit_max_bytes: int = 10 * 1024 * 1024
    audit_retention_files: int = 5
    allowlist: tuple[str, ...] = ()

    @classmethod
    def from_sources(cls, config=None, env=None):
        values = dict(config or {})
        source_env = os.environ if env is None else env
        token = source_env.get("FORGEAGENT_HTTP_TOKEN", values.get("token", ""))
        host = str(values.get("bind_host", cls.bind_host))
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError("HTTP service must bind to loopback")
        if not str(token).strip():
            raise ValueError("HTTP bearer token is required")
        return cls(bind_host=host, token=str(token), **_bounded_values(values))
```

- [x] **Step 3: 写取消终态和竞态失败测试**

```python
def test_step_cancel_event_stops_before_next_model_call():
    event = threading.Event(); event.set()
    step = Step(MockClient(script=[_reply(_done())]), TrustedBackend(), Runtime(), cancel_event=event)
    rounds = step.run([Message(role=Role.USER, content="go")])
    assert rounds[-1].stopped_reason == Termination.CANCELLED

def test_task_status_exposes_cancelled_without_marking_solved():
    status = TaskStatus(completed=False, reason=Termination.CANCELLED)
    assert status.solved is False
```

- [x] **Step 4: 实现协作式取消和一次性终态入口**

```python
class Termination(StrEnum):
    CANCELLED = "cancelled"

class Step:
    def __init__(self, ..., cancel_event: threading.Event | None = None):
        self._cancel_event = cancel_event

    def _cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()

    def run(self, messages):
        for _round in range(self._max_rounds):
            if self._cancelled():
                return [RoundResult(text="", stopped_reason=Termination.CANCELLED)]
            # existing request/parse/dispatch path
            if self._cancelled():
                rounds[-1].stopped_reason = Termination.CANCELLED
                break
```

`Task.run` 将 `cancel_event` 传递给 `Step`；`Task._derive_status` 将其作为非 solved 终态。工具执行后、准备发布完成前再次检查 event，并由后续 TaskService 状态锁决定取消是否已胜出。

- [x] **Step 5: 运行专项测试并提交**

Run: `pytest tests/test_http_config.py tests/test_task.py tests/test_step.py -q`
Expected: PASS。

```bash
git add src/forgeagent/http_config.py src/forgeagent/task.py src/forgeagent/step.py tests/test_http_config.py tests/test_task.py tests/test_step.py
git commit -m "feat: add HTTP config and cooperative cancellation contract"
```

### Task 2: 注入式审计 sink 与安全序列化

**Files:**
- Create: `src/forgeagent/audit.py`
- Modify: `src/forgeagent/secret_policy.py`
- Modify: `src/forgeagent/task.py`
- Modify: `src/forgeagent/step.py`
- Modify: `src/forgeagent/tools.py`
- Test: `tests/test_audit.py`
- Test: `tests/test_task.py`
- Test: `tests/test_step.py`

**Interfaces:**
- `AuditEvent` 为不可变模型，包含 `timestamp`, `event_type`, `task_id`, `risk_level`, `operation_id`, `attempt`, `parameters`, `result_status`, `duration_ms`, `audit_degraded`。
- `AuditSink.emit(event: AuditEvent) -> bool`；`JsonlAuditSink.degraded` 在运行时写失败后为 `True`。

- [x] **Step 1: 写字段、掩码和异常 fallback 测试**

```python
def test_audit_event_masks_secret_and_never_serializes_raw_path(tmp_path):
    sink = JsonlAuditSink(tmp_path / "audit.jsonl", max_bytes=1024, retention_files=2,
                          secret_values={"super-secret-token"})
    assert sink.emit(AuditEvent(event_type="http.submit", task_id="t1",
                                parameters={"token": "super-secret-token", "path": "/Users/a"}))
    record = json.loads((tmp_path / "audit.jsonl").read_text())
    assert "super-secret-token" not in json.dumps(record)
    assert "/Users/a" not in json.dumps(record)
```

- [x] **Step 2: 实现稳定事件模型和 JSONL sink**

```python
class AuditEvent(BaseModel):
    timestamp: str = Field(default_factory=_utc_now)
    event_type: str
    task_id: str | None = None
    risk_level: str = "low"
    operation_id: str = Field(default_factory=lambda: uuid4().hex)
    attempt: int | None = None
    parameters: dict[str, object] = Field(default_factory=dict)
    result_status: str = "unknown"
    duration_ms: int | None = None
    audit_degraded: bool = False

class JsonlAuditSink:
    def emit(self, event: AuditEvent) -> bool:
        with self._lock:
            try:
                payload = _safe_payload(event, self._secret_values)
                self._rotate_if_needed(len(json.dumps(payload)) + 1)
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
                return True
            except OSError:
                self._degraded = True
                return False
```

同时为 `Task`、`Step` 和 `ToolContext` 增加可选 audit sink/context；`None` 保持既有 CLI/direct Task 行为。Step 在每次模型 request 前后发出一条 attempt/outcome 事件，工具和确认门在核心 dispatch 路径发出逻辑操作/decision 事件。

- [x] **Step 3: 覆盖轮转、并发 append、fail-open degraded 和 attempt 语义**

```python
def test_audit_rotation_and_degraded(tmp_path):
    sink = JsonlAuditSink(tmp_path / "audit.jsonl", max_bytes=80, retention_files=2)
    for attempt in range(4):
        assert sink.emit(AuditEvent(event_type="llm.attempt", attempt=attempt))
    assert list(tmp_path.glob("audit.jsonl*"))
    sink._path = tmp_path / "missing" / "audit.jsonl"
    assert sink.emit(AuditEvent(event_type="http.query")) is False
    assert sink.degraded is True
```

- [x] **Step 4: 运行审计、Task 和 Step 测试并提交**

Run: `pytest tests/test_audit.py tests/test_task.py tests/test_step.py -q`
Expected: PASS。

```bash
git add src/forgeagent/audit.py src/forgeagent/secret_policy.py tests/test_audit.py
git commit -m "feat: add masked JSONL audit sink"
```

### Task 3: 有界 TaskService、结果投影和资源生命周期

**Files:**
- Create: `src/forgeagent/http_task_service.py`
- Modify: `src/forgeagent/task.py`
- Test: `tests/test_http_task_service.py`

**Interfaces:**
- `TaskFactory = Callable[[TaskRecord], Task]`；服务端工厂负责注入 tier/backend/root/identity/confirmer/client。
- `TaskService.submit(goal: str, options: Mapping[str, object]) -> TaskRecord`、`query(task_id: str) -> dict`、`cancel(task_id: str) -> dict`、`shutdown(timeout: float) -> None`。
- `TaskRecord.public_view() -> dict` 仅返回 `task_id`, `status`, `reason`, `detail`, `round_count`, `usage`, `audit_degraded`。

- [ ] **Step 1: 写状态、容量、TTL 和取消竞态测试**

```python
def test_service_rejects_capacity_without_creating_record():
    service = TaskService(factory=_slow_factory, config=replace(CONFIG, max_queue=0))
    with pytest.raises(ServiceCapacityError):
        service.submit("goal", {})
    assert service.records == {}

def test_running_cancel_is_cooperative_and_terminal_is_not_overwritten():
    record = service.submit("goal", {})
    assert service.cancel(record.task_id)["status"] in {"queued", "running", "cancelled"}
    service.wait(record.task_id)
    assert service.query(record.task_id)["status"] == "cancelled"
```

- [ ] **Step 2: 实现 TaskRecord 和有界注册表**

```python
@dataclass
class TaskRecord:
    task_id: str
    goal: str
    status: str = "queued"
    reason: str | None = None
    outcome: TaskOutcome | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    audit_degraded: bool = False
    future: Future | None = None
    created_at: float = field(default_factory=time.monotonic)
    ended_at: float | None = None

    def public_view(self) -> dict[str, object]:
        status = self.outcome.status if self.outcome else None
        return {
            "task_id": self.task_id, "status": self.status,
            "reason": self.reason or (status.reason if status else None),
            "detail": _safe_detail(status.detail if status else None),
            "round_count": len(self.outcome.rounds) if self.outcome else 0,
            "usage": _usage_summary(self.outcome),
            "audit_degraded": self.audit_degraded,
        }
```

- [ ] **Step 3: 实现 worker、CAS 终态和资源关闭顺序**

worker 在 `try/finally` 中执行 `Task.run(..., cancel_event=record.cancel_event)`，先调用 `task.close()`，再关闭 client/backend 资源；完成、失败、取消全部经 `_publish_terminal()` 的锁保护，已发布终态不可覆盖。队列任务取消不创建 client/Task。

- [ ] **Step 4: 实现队列满、过期/淘汰和 shutdown**

队列或保留记录上限触发 `ServiceCapacityError`；仅淘汰 TTL 已过期的终态记录，运行中记录永不淘汰；过期 id 统一抛出 `TaskNotFound(expired=True)`。shutdown 停止接收、取消 queued、bounded join running，再关闭共享 MCP manager。

- [ ] **Step 5: 运行服务测试并提交**

Run: `pytest tests/test_http_task_service.py -q`
Expected: PASS。

```bash
git add src/forgeagent/http_task_service.py src/forgeagent/task.py tests/test_http_task_service.py
git commit -m "feat: add bounded task service registry"
```

### Task 4: Headless allowlist 与工具确认边界

**Files:**
- Create: `src/forgeagent/headless.py`
- Modify: `src/forgeagent/tools.py`
- Modify: `src/forgeagent/mcp_manager.py`
- Test: `tests/test_headless.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- `normalize_allowlist(entries: Iterable[str]) -> frozenset[str]` 只接受精确 MCP `server/tool`、项目相对 FileWrite 路径和 `scheme/host/port/path` WebFetch key。
- `HeadlessConfirmer(allowlist, audit) : Confirmer`；命中返回 `True` 并写 `preapproved`，未命中返回 `False` 并写 denial。
- `ToolContext.allow_auto_approve: bool = True`；HTTP context 设为 `False`，CLI 默认保持 `True`。

- [ ] **Step 1: 写精确匹配和 autoApprove 隔离测试**

```python
def test_http_allowlist_does_not_accept_glob_or_mcp_autoapprove():
    confirmer = HeadlessConfirmer({"files/out.txt", "example.com:443/a"}, audit=MemoryAudit())
    assert confirmer(FileWriteArgs(path="files/out.txt", content="x")) is True
    assert confirmer(FileWriteArgs(path="files/other.txt", content="x")) is False
    ctx = ToolContext(..., confirmer=confirmer, allow_auto_approve=False)
    assert MCPTool().run(MCPArgs(server="s", tool="t"), ctx).success is False
```

- [ ] **Step 2: 实现规范化键和 headless confirmer**

```python
def operation_key(args: BaseModel, root: Path) -> str:
    if isinstance(args, MCPArgs): return f"{args.server}/{args.tool}"
    if isinstance(args, FileWriteArgs): return root.joinpath(args.path).resolve().relative_to(root).as_posix()
    if isinstance(args, WebFetchArgs):
        parts = urlsplit(args.url)
        return f"{parts.scheme.lower()}/{parts.hostname}:{parts.port or 443}{parts.path or '/'}"
    return type(args).__name__

class HeadlessConfirmer:
    def __call__(self, args: BaseModel) -> bool:
        key = operation_key(args, self._root)
        allowed = key in self._allowlist
        self._audit.emit(AuditEvent(event_type="confirmation", parameters={"operation": key},
                                    result_status="preapproved" if allowed else "denied"))
        return allowed
```

- [ ] **Step 3: 修改 MCP/WebFetch/FileWrite 调用路径**

仅当 `ctx.allow_auto_approve` 为 `True` 时调用 `mcp.is_auto_approved()`；HTTP 使用 headless confirmer 且永不读取 MCP server 的 `autoApprove`。CLI/REPL 默认值不变。所有确认决定经 audit sink 埋点。

- [ ] **Step 4: 运行工具测试并提交**

Run: `pytest tests/test_headless.py tests/test_tools.py tests/test_mcp_manager.py -q`
Expected: PASS。

```bash
git add src/forgeagent/headless.py src/forgeagent/tools.py src/forgeagent/mcp_manager.py tests/test_headless.py tests/test_tools.py
git commit -m "feat: isolate HTTP allowlist from MCP auto approval"
```

### Task 5: ThreadingHTTPServer、鉴权、路由和错误 envelope

**Files:**
- Create: `src/forgeagent/http_server.py`
- Test: `tests/test_http_server.py`

**Interfaces:**
- `create_http_server(config: HttpServiceConfig, service: TaskService) -> ThreadingHTTPServer`。
- `ForgeRequestHandler` 实现 `POST /tasks`、`GET /tasks/<id>`、`POST /tasks/<id>/cancel`；无 health/shutdown/upload/stream 路由。
- 成功和错误均为 JSON；错误固定为 `{"error":{"kind":...,"detail":...}}`。

- [ ] **Step 1: 写 loopback 集成测试 fixture 和请求矩阵**

```python
def test_submit_query_cancel_and_auth(server_url):
    response = request("POST", "/tasks", {"goal": "go"}, token="test-token")
    assert response.status == 202
    task_id = response.json["task_id"]
    assert request("GET", f"/tasks/{task_id}", token="test-token").status == 200
    assert request("POST", f"/tasks/{task_id}/cancel", {}, token="test-token").status in {200, 202}
    assert request("GET", f"/tasks/{task_id}", token="wrong").json["error"]["kind"] == "unauthorized"
```

- [ ] **Step 2: 实现严格 Authorization、body 和 path 解析**

```python
def _authorized(headers, expected: str) -> bool:
    raw = headers.get("Authorization", "")
    scheme, _, token = raw.partition(" ")
    return scheme == "Bearer" and bool(token) and hmac.compare_digest(token, expected)

def _read_json(handler, limit: int) -> dict[str, object]:
    if handler.headers.get_content_type() != "application/json": raise HttpError(415, "invalid_content_type")
    length = int(handler.headers.get("Content-Length", "-1"))
    if length < 0 or length > limit: raise HttpError(413, "body_too_large")
    value = json.loads(handler.rfile.read(length))
    if not isinstance(value, dict): raise HttpError(400, "invalid_json")
    return value
```

- [ ] **Step 3: 实现请求 schema、路由和安全投影**

只接受 `goal` 非空字符串及设计中列出的低风险选项；未知字段和高权限字段返回 `400 invalid_request`。`POST /tasks` 返回 `202`；查询返回 `200`；容量满返回 `429 capacity_exceeded`；未知/过期 id 返回统一 `404 not_found`；cancel 使用有限 acknowledgement 等待并返回当前状态。

- [ ] **Step 4: 接入 HTTP lifecycle 审计和 server shutdown**

在 auth failure、submit、query、cancel、capacity rejection、headless denial 处各写一条 lifecycle event；shutdown 由拥有 `TaskService` 的进程调用 `service.shutdown()` 和 `server.shutdown()`，handler 不提供 shutdown endpoint。

- [ ] **Step 5: 运行 HTTP 测试并提交**

Run: `pytest tests/test_http_server.py -q`
Expected: PASS。

```bash
git add src/forgeagent/http_server.py tests/test_http_server.py
git commit -m "feat: expose bounded loopback HTTP task endpoints"
```

### Task 6: CLI opt-in 装配与资源策略

**Files:**
- Modify: `src/forgeagent/cli.py`
- Modify: `src/forgeagent/__init__.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_packaging.py`

**Interfaces:**
- 新增 `forgeagent serve` 子命令，默认不启动 HTTP；命令装配配置、audit sink、MCP manager、headless confirmer 和服务端 task factory。
- `forgeagent serve --config PATH` 仅读取服务端配置，不接受客户端覆盖的 tier/root/identity/credential 参数。

- [ ] **Step 1: 写 opt-in 和默认 CLI 回归测试**

```python
def test_cli_default_does_not_start_http(monkeypatch):
    monkeypatch.setattr(http_server, "create_http_server", lambda *a: pytest.fail("unexpected"))
    assert main(["--help"]) == 0

def test_serve_builds_loopback_server(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGEAGENT_HTTP_TOKEN", "test-token")
    assert main(["serve", "--config", str(tmp_path / "config.yaml"), "--once"]) == 0
```

- [ ] **Step 2: 实现 serve 装配和 bounded shutdown**

服务启动前验证 `HttpServiceConfig` 和 audit path；创建共享 MCP manager（若配置启用），每个 worker 创建 client/Task/headless confirmer；捕获 SIGINT/SIGTERM 后执行 service shutdown、MCP close、HTTP server close。既有 `run`/REPL 参数和输出不改。

- [ ] **Step 3: 运行 CLI/packaging 测试并提交**

Run: `pytest tests/test_cli.py tests/test_packaging.py -q`
Expected: PASS。

```bash
git add src/forgeagent/cli.py src/forgeagent/__init__.py tests/test_cli.py tests/test_packaging.py
git commit -m "feat: add opt-in HTTP serve command"
```

### Task 7: 文档、golden 回放与安全验收

**Files:**
- Modify: `README.md`
- Modify: `docs/threat-model.md`
- Create: `docs/http-task-service.md`
- Test: `tests/test_http_server.py`
- Test: `tests/test_mock_replay_e2e.py`

- [ ] **Step 1: 增加配置/生命周期/安全文档**

文档明确 `serve` 启动方式、`FORGEAGENT_HTTP_TOKEN` 优先级、loopback-only/no TLS、三条路由、请求 schema、结果投影、取消竞态、allowlist 精确键、HTTP 不继承 `autoApprove`、审计 fail-open/degraded、容量/TTL 和 shutdown 所有权。

- [ ] **Step 2: 增加并发和资源泄漏验收**

```python
def test_http_concurrent_tasks_are_isolated(server_url):
    ids = submit_many(server_url, count=8)
    assert len(set(ids)) == 8
    assert all(wait_terminal(server_url, task_id)["task_id"] == task_id for task_id in ids)

def test_shutdown_leaves_no_worker_or_mcp_threads(service):
    service.shutdown(timeout=2.0)
    assert not service.active_worker_threads()
```

- [ ] **Step 3: HTTP golden 子集回放并比较 CLI/mock 结果**

选择 `tests/golden/cases.py` 中不依赖真实网络/交互的代表性案例，通过同一 MockClient 运行 CLI 和 HTTP 路径，逐项比较 `status.reason`、安全 detail 和 tool outcome 数量；审计断言只检查掩码后的字段，不固定时间戳。

- [ ] **Step 4: 运行全量验证并记录证据**

Run: `ruff check src tests && pytest -q && git diff --check`
Expected: Ruff 无错误、全量 pytest PASS、diff check 无输出。再运行项目已有 golden runner，并把命令和结果写入 `docs/superpowers/reports/2026-07-21-http-task-service-verify.md`。

```bash
git add README.md docs/threat-model.md docs/http-task-service.md tests/test_http_server.py tests/test_mock_replay_e2e.py docs/superpowers/reports/2026-07-21-http-task-service-verify.md
git commit -m "docs: document and verify HTTP task service"
```

## 自审结果

- 设计 §1-§2 的配置、容量、取消、资源所有权分别覆盖 Task 1 和 Task 3。
- 设计 §2.4 的三条路由、错误 envelope、body/response 上限和无 shutdown endpoint 覆盖 Task 5。
- 设计 §2.5 与原有 `autoApprove` 冲突已通过 `allow_auto_approve` 明确隔离，覆盖 Task 4。
- 设计 §3 的字段、attempt/operation id、掩码、轮转、fail-open 和 HTTP lifecycle 事件覆盖 Task 2、Task 5。
- 设计 §6 的单元、并发集成、golden parity、线程泄漏和静态检查覆盖 Task 1-7。
- 计划中没有保留 TBD/TODO 或“稍后决定”占位；所有新接口在相邻任务的 Interfaces 中给出。

计划完成并保存于 `docs/superpowers/plans/2026-07-21-http-task-service.md`。执行时可选择：

1. **Subagent-Driven（推荐）**：每个任务使用独立 agent，任务间进行两阶段 review。
2. **Inline Execution**：在当前会话按任务批次执行，并在检查点暂停 review。
