---
change: runtime-context-engineering
design-doc: docs/superpowers/specs/2026-07-22-runtime-context-engineering-design.md
base-ref: b7ba133ad4def9c10d0352b6bc3b8a1e95b84ef2
---

# M17 Runtime Context Engineering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为所有 Task 入口加入模型能力驱动的 sliding-window request view、统一且诚实的工具反馈限额，以及跨 provider 一致的 cache hit rate，同时保持 M16 HTTP 契约。

**Architecture:** `src/forgeagent/context.py` 提供 frozen 配置、零依赖估算器、无状态 sliding policy 和纯函数 feedback limiter；`Task` 构造 policy，`Step` 继续唯一拥有完整 conversation/rounds，并只在 provider 请求边界取得有界视图。Provider adapter 填充内部 normalized denominator，CLI/audit 消费它，HTTP projection 保持原样。

**Tech Stack:** Python 3.11+、Pydantic、现有 ForgeAgent ModelClient/Task/Step/Tool API、pytest、Ruff；不新增运行时依赖或在线 tokenizer。

## Global Constraints

- OpenSpec delta specs 是行为事实源，Design Doc 是技术事实源；不得改变已确认的预算公式和错误优先级。
- M17 只实现 sliding window；不增加 importance/summary/hybrid、manager、factory、plugin、strategy registry 或新依赖。
- `input_budget = floor(context_window * utilization_ratio) - effective_max_output_tokens`；默认 ratio 为 `0.8`。
- feedback 默认上限为 input budget 的 10%，单结果为 round limit 的 25%；固定 8192/2048 不是默认值。
- system 与 initial goal 不截断；历史只按完整 assistant-feedback round 淘汰；所有本地 context failure 在 `llm.attempt started` 前发生。
- 完整 `ToolOutcome` 保存在 `RoundResult.outcomes`；进入 conversation 的只有 limiter 生成的有界 feedback。
- HTTP submit body、usage response 和 M16 鉴权/取消/安全投影/审计/allowlist 契约不变。
- 每个实现任务执行 TDD RED-GREEN-REFACTOR；任务完成后只提交该任务相关文件。

## 文件与接口边界

- Create `src/forgeagent/context.py`：`ContextConfig`、`load_context_config`、估算器、`ContextPolicy`、`SlidingWindowContextPolicy`、`render_bounded_feedback`。
- Modify `src/forgeagent/models.py`：内部 `TokenUsage.total_prompt_tokens`。
- Modify `src/forgeagent/tools.py`：`ToolOutcome.continuation` / `truncation_mode` 及各工具真实元数据。
- Modify `src/forgeagent/task.py`、`src/forgeagent/step.py`：policy 构造/注入、request view、本地失败、统一 feedback。
- Modify provider adapters：normalized denominator。
- Modify `src/forgeagent/cli.py`：config/reload 装配与 cache rate 展示。
- Modify `src/forgeagent/audit.py`/Step audit payload：cache rate，保持 fail-open。
- Modify `src/forgeagent/http_config.py`、`src/forgeagent/http_task_service.py`：server-owned context 与 schema 回归。

---

### Task 1: ContextConfig 与确定性 token 估算器

- [x] **Task 1 complete: ContextConfig 与确定性 token 估算器已交付**

**Files:**
- Create: `src/forgeagent/context.py`
- Create: `tests/test_context.py`

**Interfaces:**
- Produces `ContextConfig(BaseModel)` with the four approved fields.
- Produces `load_context_config(path: Path | None = None, *, data: Mapping[str, object] | None = None) -> ContextConfig`.
- Produces `estimate_text_tokens(text: str) -> int`, `estimate_message_tokens(message: Message, config: ContextConfig) -> int`, and `estimate_request_tokens(messages: Sequence[Message], config: ContextConfig) -> int`.

- [x] **Step 1: 写配置与 estimator 的失败测试**

```python
def test_context_config_missing_mapping_uses_bounded_defaults():
    cfg = load_context_config(data={"groups": []})
    assert cfg.utilization_ratio == 0.8
    assert cfg.image_token_reserve == 4096
    assert cfg.tool_result_max_tokens is None
    assert cfg.round_feedback_max_tokens is None

def test_estimator_uses_ceil_and_image_reserve():
    cfg = ContextConfig(image_token_reserve=100)
    message = Message(role=Role.USER, content=[TextItem(text="abcde"), _image()])
    assert estimate_text_tokens("abcde") == 2
    assert estimate_message_tokens(message, cfg) == 2 + 100 + 4
```

- [x] **Step 2: 运行 RED**

Run: `.venv/bin/pytest -q tests/test_context.py`

Expected: FAIL with `ModuleNotFoundError: forgeagent.context`.

- [x] **Step 3: 实现 frozen 配置、load-time 校验和估算公式**

```python
class ContextConfig(BaseModel):
    utilization_ratio: float = Field(default=0.8, gt=0, le=1)
    image_token_reserve: int = Field(default=4096, gt=0)
    tool_result_max_tokens: int | None = Field(default=None, gt=0)
    round_feedback_max_tokens: int | None = Field(default=None, gt=0)
    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def validate_explicit_limits(self) -> Self:
        if (
            self.tool_result_max_tokens is not None
            and self.round_feedback_max_tokens is not None
            and self.round_feedback_max_tokens < self.tool_result_max_tokens
        ):
            raise ValueError("round feedback limit must be >= tool result limit")
        return self
```

`load_context_config` 只读取顶层 `context` mapping；缺失时用 `{}`，存在但不是 mapping 时抛 Pydantic/ValueError。文本 estimator 精确实现 Design Doc 的三类 ceil 公式、4/message 和 2/request framing；图片只计 reserve。

- [x] **Step 4: 跑配置、英文/中文/代码/JSON/emoji、多模态测试**

Run: `.venv/bin/pytest -q tests/test_context.py`

Expected: PASS.

- [x] **Step 5: 提交**

```bash
git add src/forgeagent/context.py tests/test_context.py
git commit -m "feat: add context configuration and token estimator"
```

### Task 2: SlidingWindowContextPolicy 与预算边界

- [ ] **Task 2 complete: SlidingWindowContextPolicy 与预算边界已交付**

**Files:**
- Modify: `src/forgeagent/context.py`
- Modify: `tests/test_context.py`

**Interfaces:**
- Produces `ContextBudgetExceeded(ValueError)` with bounded `detail`.
- Produces `ContextPolicy(Protocol).request_view(messages: Sequence[Message]) -> list[Message]`.
- Produces `SlidingWindowContextPolicy(capability: ModelCapability, params: GenerationParams | None, config: ContextConfig)` and read-only resolved `input_budget`, `tool_result_limit`, `round_feedback_limit`.

- [ ] **Step 1: 写预算、完整 round 和不变性的失败测试**

```python
def test_policy_reserves_effective_output_and_resolves_adaptive_limits():
    policy = SlidingWindowContextPolicy(_capability(1000, 200), GenerationParams(max_output_tokens=100), ContextConfig())
    assert policy.input_budget == 700
    assert policy.round_feedback_limit == 70
    assert policy.tool_result_limit == 17

def test_policy_drops_oldest_complete_round_without_mutating_input():
    convo = _conversation_with_three_rounds()
    snapshot = [m.model_copy(deep=True) for m in convo]
    view = _small_policy_that_fits_two_rounds().request_view(convo)
    assert view == [convo[0], convo[1], *convo[-4:]]
    assert convo == snapshot
```

另加 prefix 超预算、prefix+latest round 超预算、混合 override、adaptive floor 为 0、阈值以下逐字一致和 ToolCall/feedback 不拆分测试。

- [ ] **Step 2: 运行 RED**

Run: `.venv/bin/pytest -q tests/test_context.py -k 'policy or budget or round'`

Expected: FAIL because policy symbols do not exist.

- [ ] **Step 3: 实现最小无状态 policy**

```python
effective_output = (
    params.max_output_tokens
    if params is not None and params.max_output_tokens is not None
    else capability.max_output_tokens
)
input_budget = floor(capability.context_window * config.utilization_ratio) - effective_output
round_limit = config.round_feedback_max_tokens or floor(input_budget * 0.10)
result_limit = config.tool_result_max_tokens or floor(round_limit * 0.25)
```

初始化统一拒绝非正 budget/limit 和 `round_limit < result_limit`。`request_view` 固定前两条消息，从最新完整两消息 round 向前装入并恢复原顺序；只创建新 list，不改 Message。

- [ ] **Step 4: 运行 policy 测试与 Ruff**

Run: `.venv/bin/pytest -q tests/test_context.py && .venv/bin/ruff check src/forgeagent/context.py tests/test_context.py`

Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add src/forgeagent/context.py tests/test_context.py
git commit -m "feat: add sliding window context policy"
```

### Task 3: Task/Step policy 装配与本地失败时序

- [ ] **Task 3 complete: Task/Step policy 装配与本地失败时序已交付**

**Files:**
- Modify: `src/forgeagent/task.py`
- Modify: `src/forgeagent/step.py`
- Modify: `tests/test_task.py`
- Modify: `tests/test_step.py`

**Interfaces:**
- `Task(..., context_config: ContextConfig | None = None, context_policy: ContextPolicy | None = None)` constructs once and forwards.
- `Step(..., context_policy: ContextPolicy | None = None, context_config: ContextConfig | None = None)` eagerly constructs fallback in `__init__`.
- Every `_stream_or_complete` call consumes `context_policy.request_view(convo)`.

- [ ] **Step 1: 写 RecordingClient 与失败优先级测试**

```python
def test_step_applies_policy_before_every_provider_call():
    client = RecordingClient([_tool_reply(), _done_reply()])
    policy = RecordingPolicy()
    Step(client, TrustedBackend(), Runtime(), context_policy=policy).run(_initial_messages())
    assert policy.calls == 2
    assert client.requests == policy.returned_views

def test_oversized_prefix_fails_before_llm_attempt_audit():
    sink = RecordingAuditSink()
    client = RecordingClient([_done_reply()])
    rounds = Step(client, TrustedBackend(), Runtime(), context_policy=_always_over_budget(), audit_sink=sink).run(_initial_messages())
    assert rounds[-1].stopped_reason == Termination.FAILED
    assert client.requests == []
    assert not any(event.action == "llm.attempt" for event in sink.events)
```

另测 cancel 已置位时优先返回 CANCELLED、stream/complete 共用 view、latest-round 超预算 detail 有界。

- [ ] **Step 2: 运行 RED**

Run: `.venv/bin/pytest -q tests/test_task.py tests/test_step.py -k 'context or policy or oversized'`

Expected: FAIL because Task/Step do not accept policy arguments.

- [ ] **Step 3: 在请求边界接入 policy**

`Step.__init__` 立即解析 fallback policy；`_run_rounds` 先检查 cancellation，再调用 `request_view`，成功后才创建 operation id/发 `llm.attempt started`。捕获 `ContextBudgetExceeded` 时追加现有形状的 `RoundResult(text="", stopped_reason=Termination.FAILED, stopped_detail=exc.detail)`，不制造 `ClientError`。

- [ ] **Step 4: 运行 Task/Step 全文件测试**

Run: `.venv/bin/pytest -q tests/test_task.py tests/test_step.py tests/test_streaming.py`

Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add src/forgeagent/task.py src/forgeagent/step.py tests/test_task.py tests/test_step.py
git commit -m "feat: apply context policy at model request boundaries"
```

### Task 4: ToolOutcome 截断语义与真实 continuation

- [ ] **Task 4 complete: ToolOutcome 截断语义与真实 continuation 已交付**

**Files:**
- Modify: `src/forgeagent/tools.py`
- Modify: `tests/test_tools.py`
- Modify: `tests/test_web_file_tools.py`

**Interfaces:**
- `ToolOutcome.continuation: str | None = None`.
- `ToolOutcome.truncation_mode: Literal["head", "tail"] = "tail"`.
- Exec stays tail; FileRead/FileList/WebFetch/Survey/MCP return head and truthful continuation.

- [ ] **Step 1: 写每个工具 outcome 元数据的失败测试**

```python
def test_exec_uses_tail_and_mcp_uses_honest_head_continuation():
    assert ExecTool().run(_exec_call(), _ctx()).truncation_mode == "tail"
    outcome = MCPTool().run(_mcp_call(), _ctx_with_mcp())
    assert outcome.truncation_mode == "head"
    assert outcome.continuation == "此工具不保留游标；如需更多结果，请缩小查询参数后重新调用"
```

File/WebFetch 测试只断言真实现有能力；不得断言新 cursor/offset。

- [ ] **Step 2: 运行 RED**

Run: `.venv/bin/pytest -q tests/test_tools.py tests/test_web_file_tools.py -k 'continuation or truncation_mode'`

Expected: FAIL because ToolOutcome fields are missing.

- [ ] **Step 3: 添加两个字段并在工具执行结果处设置**

```python
class ToolOutcome(BaseModel):
    # existing fields unchanged
    continuation: str | None = None
    truncation_mode: Literal["head", "tail"] = "tail"
```

字段由工具构造 outcome 时设置，executor/Step 不按工具名分支。WebFetch 只有在已有完整落盘文件时才引用真实相对路径。

- [ ] **Step 4: 运行工具回归**

Run: `.venv/bin/pytest -q tests/test_tools.py tests/test_web_file_tools.py tests/test_mcp_manager.py`

Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add src/forgeagent/tools.py tests/test_tools.py tests/test_web_file_tools.py
git commit -m "feat: describe truthful tool feedback truncation"
```

### Task 5: 水位 feedback limiter 与 Step 统一渲染

- [ ] **Task 5 complete: 水位 feedback limiter 与 Step 统一渲染已交付**

**Files:**
- Modify: `src/forgeagent/context.py`
- Modify: `src/forgeagent/step.py`
- Modify: `tests/test_context.py`
- Modify: `tests/test_step.py`

**Interfaces:**
- Produces `render_bounded_feedback(round_result: RoundResult, *, config/policy limits, mask: Callable[[str], str]) -> str` or an equivalent pure function consuming parse errors/outcomes and resolved limits.
- Raises `ContextBudgetExceeded("feedback metadata exceeds context budget")` only when fixed metadata cannot fit.

- [ ] **Step 1: 写水位、公平、head/tail 和 metadata overflow 失败测试**

```python
def test_waterfill_reassigns_short_outcome_budget_and_preserves_headers():
    outcomes = [_outcome("Edit", "ok"), _outcome("Exec", "x" * 5000), _outcome("FileRead", "y" * 5000, mode="head")]
    rendered = render_bounded_feedback(outcomes, result_limit=200, round_limit=500)
    assert rendered.index("[Edit") < rendered.index("[Exec") < rendered.index("[FileRead")
    file_line = next(line for line in rendered.splitlines() if line.startswith("[FileRead"))
    assert "y" * 32 in file_line
    assert "y" * 5000 not in file_line
    assert estimate_text_tokens(rendered) <= 500

def test_metadata_overflow_keeps_outcomes_and_skips_next_provider_call():
    # one round executes many outcomes whose headers/continuations exceed the cap
    assert result.rounds[-1].outcomes == original_outcomes
    assert result.status.reason == Termination.FAILED
    assert result.status.detail == "feedback metadata exceeds context budget"
```

另测 static feedback、dropped_state_keys、secret masking、marker 仅在截断时出现和迭代集合收敛。

- [ ] **Step 2: 运行 RED**

Run: `.venv/bin/pytest -q tests/test_context.py tests/test_step.py -k 'feedback or waterfill or metadata'`

Expected: FAIL because the unified limiter is absent.

- [ ] **Step 3: 实现确定性 limiter 并替换 `_truncate_tail` 分支**

固定成本使用同一 estimator；剩余 detail budget 在未满足 outcome 间均分，短项余量继续分配。每个 detail 受 result cap；head/tail 最大片段用字符长度二分。marker 集合变化后重算，最多 `len(outcomes)+1` 次。Step 只把成功渲染出的 bounded feedback append 到 convo。

- [ ] **Step 4: 运行 context/Step/工具全回归**

Run: `.venv/bin/pytest -q tests/test_context.py tests/test_step.py tests/test_tools.py tests/test_web_file_tools.py`

Expected: PASS and no legacy 4096-only branch remains in `_render_feedback`.

- [ ] **Step 5: 提交**

```bash
git add src/forgeagent/context.py src/forgeagent/step.py tests/test_context.py tests/test_step.py
git commit -m "feat: bound all tool feedback with water filling"
```

### Task 6: Provider-normalized prompt denominator

- [ ] **Task 6 complete: Provider-normalized prompt denominator 已交付**

**Files:**
- Modify: `src/forgeagent/models.py`
- Modify: `src/forgeagent/anthropic_client.py`
- Modify: `src/forgeagent/openai_compatible_client.py`
- Modify: `tests/test_anthropic_client.py`
- Modify: `tests/test_openai_compatible_client.py`
- Modify: `tests/test_streaming.py`

**Interfaces:**
- `TokenUsage.total_prompt_tokens: int | None = Field(default=None, exclude=True, repr=False)`.
- Anthropic writes `input_tokens + cached_tokens`; OpenAI-compatible writes total `input_tokens`.

- [ ] **Step 1: 写 streaming/non-streaming denominator 和序列化失败测试**

```python
def test_anthropic_usage_normalizes_prompt_total_without_serializing_helper():
    usage = _complete_with_usage(input_tokens=10, cache_creation=3, cache_read=2).usage
    assert usage.total_prompt_tokens == 15
    assert "total_prompt_tokens" not in usage.model_dump()

def test_openai_usage_uses_prompt_total_that_already_contains_cache():
    usage = _openai_complete(prompt_tokens=20, cached_tokens=5).usage
    assert usage.total_prompt_tokens == 20
```

- [ ] **Step 2: 运行 RED**

Run: `.venv/bin/pytest -q tests/test_anthropic_client.py tests/test_openai_compatible_client.py tests/test_streaming.py -k 'prompt_total or total_prompt'`

Expected: FAIL because internal field is missing.

- [ ] **Step 3: 在 adapter 构造 TokenUsage 的全部成功路径赋值**

正常 usage 响应必须非 None；provider 确实未返回 usage 时保留 None。不得在 Step 根据 `client_kind` 补算。

- [ ] **Step 4: 运行 provider 全回归**

Run: `.venv/bin/pytest -q tests/test_anthropic_client.py tests/test_openai_compatible_client.py tests/test_streaming.py tests/test_client.py`

Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add src/forgeagent/models.py src/forgeagent/anthropic_client.py src/forgeagent/openai_compatible_client.py tests/test_anthropic_client.py tests/test_openai_compatible_client.py tests/test_streaming.py
git commit -m "feat: normalize provider prompt token totals"
```

### Task 7: CLI/session cache rate、audit 与事务化 reload

- [ ] **Task 7 complete: CLI/session cache rate、audit 与事务化 reload 已交付**

**Files:**
- Modify: `src/forgeagent/cli.py`
- Modify: `src/forgeagent/step.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_audit.py`

**Interfaces:**
- Existing `TokenUsage` accumulator tracks denominator availability; once unknown, session rate stays unavailable.
- Existing usage line appends `cache_hit=<percent>` or `cache_hit=n/a`.
- Successful `llm.outcome.parameters` adds sibling `cache_hit_rate: float | None`.
- `/reload` validates registry + context before swapping either.

- [ ] **Step 1: 写累计比例、missing/invalid denominator、audit null 和 reload rollback 失败测试**

```python
def test_usage_line_uses_ratio_of_sums_and_any_missing_is_na():
    total = TokenUsage(total_prompt_tokens=0)
    _accumulate_usage(total, [RoundResult(text="", usage=TokenUsage(cached_tokens=10, total_prompt_tokens=40))])
    console = Console(record=True)
    _print_usage(total, console)
    assert "cache_hit=25.0%" in console.export_text()

    _accumulate_usage(total, [RoundResult(text="", usage=TokenUsage(total_prompt_tokens=None))])
    console = Console(record=True)
    _print_usage(total, console)
    assert "cache_hit=n/a" in console.export_text()

def test_repl_reload_invalid_context_never_reports_partial_success(monkeypatch):
    inputs = iter(["/reload", "quit"])
    monkeypatch.setattr(
        cli_module,
        "load_context_config",
        lambda: (_ for _ in ()).throw(ValueError("invalid context")),
    )
    console = _console()
    cli_module.repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),
        console=console,
        read_line=lambda prompt: next(inputs),
    )
    assert "reload failed" in console.export_text()
    assert "reloaded:" not in console.export_text()
```

Audit 测试断言 raw usage 不变、rate 在 0..1 或 null、写入失败仍 `audit_degraded`。

- [ ] **Step 2: 运行 RED**

Run: `.venv/bin/pytest -q tests/test_cli.py tests/test_audit.py -k 'cache_hit or context_reload'`

Expected: FAIL because rate/reload behavior is absent.

- [ ] **Step 3: 实现统一聚合 helper 并接入 CLI/REPL/audit**

只在 `total > 0` 且 `0 <= cached <= total` 时返回比例；不钳制异常数据。REPL 累计 usage 但每个 goal 的 Task/messages 仍独立。reload 使用临时候选对象验证后一次替换。

- [ ] **Step 4: 运行 CLI/audit 回归**

Run: `.venv/bin/pytest -q tests/test_cli.py tests/test_audit.py`

Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add src/forgeagent/cli.py src/forgeagent/step.py tests/test_cli.py tests/test_audit.py
git commit -m "feat: report normalized prompt cache rates"
```

### Task 8: HTTP server-owned context 装配与 M16 契约回归

- [ ] **Task 8 complete: HTTP server-owned context 装配与 M16 契约回归已交付**

**Files:**
- Modify: `src/forgeagent/http_config.py`
- Modify: `src/forgeagent/http_task_service.py`
- Modify: `src/forgeagent/cli.py`
- Modify: `tests/test_http_config.py`
- Modify: `tests/test_http_task_service.py`
- Modify: `tests/test_http_server.py`

**Interfaces:**
- `HttpServiceConfig` owns a validated `ContextConfig` from serve config.
- HTTP Task factory passes only server context to `Task`.
- `_usage_summary` remains exactly `input_tokens`, `output_tokens`, `cached_tokens`, `reasoning_tokens`.

- [ ] **Step 1: 写启动失败、override 拒绝和 usage snapshot 失败测试**

```python
def test_http_invalid_context_fails_before_listener_bind():
    with pytest.raises(HttpStartupError, match="context"):
        _serve_with_config({"context": {"utilization_ratio": 8}})

def test_http_usage_projection_excludes_internal_prompt_metrics():
    assert set(_usage_summary(_outcome_with_normalized_usage())) == {
        "input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens"
    }
```

提交 body 增加 `context`/limit 字段时继续由 extra-forbid schema 拒绝；MCP autoApprove 绕过回归必须保留。

- [ ] **Step 2: 运行 RED/现有 M16 回归基线**

Run: `.venv/bin/pytest -q tests/test_http_config.py tests/test_http_task_service.py tests/test_http_server.py`

Expected: new context wiring tests FAIL; all pre-existing M16 cases remain PASS.

- [ ] **Step 3: 接入 server-owned ContextConfig 并启动前构造 policy limits**

HTTP 配置验证错误包装为现有 `HttpStartupError`；不新增请求/响应字段。Task factory 继续传 `allow_auto_approve=False` 和 exact allowlist confirmer。

- [ ] **Step 4: 运行 HTTP 与 M16 安全回归**

Run: `.venv/bin/pytest -q tests/test_http_config.py tests/test_http_task_service.py tests/test_http_server.py tests/test_headless.py tests/test_mcp_manager.py`

Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add src/forgeagent/http_config.py src/forgeagent/http_task_service.py src/forgeagent/cli.py tests/test_http_config.py tests/test_http_task_service.py tests/test_http_server.py
git commit -m "feat: apply server-owned context policy to HTTP tasks"
```

### Task 9: Prompt-cache/长任务验收、文档与全量验证

- [ ] **Task 9 complete: Prompt-cache/长任务验收、文档与全量验证已交付**

**Files:**
- Modify: `tests/test_mock_replay_e2e.py`
- Modify: `tests/golden/cases.py` if a deterministic replay case belongs in the existing manifest
- Modify: `README.md`
- Modify: `docs/model-client-contract.md`
- Modify: `docs/m10-usage-observability-and-tools.md`
- Modify: `docs/http-task-service.md`
- Modify: `docs/threat-model.md`
- Modify: `openspec/changes/runtime-context-engineering/tasks.md`

**Interfaces:**
- RecordingClient exposes exact request histories for stable-prefix assertions.
- Long replay deterministically crosses the sliding threshold and still reaches `complete()`.

- [ ] **Step 1: 写 prompt stability 与长对话 mock replay**

```python
def test_long_replay_slides_old_rounds_but_preserves_stable_prefix():
    client = RecordingClient(_many_tool_rounds_then_complete(), capability=_small_capability())
    outcome = Task(client, context_config=_small_context()).run("finish the replay")
    assert outcome.status.completed
    assert all(call[0] == client.calls[0][0] for call in client.calls)
    assert any(len(call) < len(client.calls[index - 1]) + 2 for index, call in enumerate(client.calls[1:], 1))
```

另断言阈值以下已有消息逐字稳定、滑动后保留消息未改写、截断 marker 可观察。

- [ ] **Step 2: 运行 replay/golden RED-GREEN**

Run: `.venv/bin/pytest -q tests/test_mock_replay_e2e.py tests/test_golden_runner.py`

Expected: PASS after the M17 implementation; failures must enter systematic-debugging before source edits.

- [ ] **Step 3: 更新配置、CLI、审计、HTTP 和威胁模型文档**

文档必须明确：四字段单位是近似 token、null 自适应公式、估算误差、system/goal fail-fast、continuation 诚实限制、CLI/audit rate 口径、HTTP 无新字段。

- [ ] **Step 4: 运行完整验证矩阵**

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/python -m tests.golden.runner --output-dir /tmp/forgeagent-m17-golden
openspec validate runtime-context-engineering --strict
git diff --check
```

Expected: pytest 全绿（仅既有 documented skips）、Ruff PASS、golden 全绿、OpenSpec valid、diff check 无输出。

- [ ] **Step 5: 勾选 OpenSpec tasks 并提交验收产物**

```bash
git add README.md docs/model-client-contract.md docs/m10-usage-observability-and-tools.md docs/http-task-service.md docs/threat-model.md tests/test_mock_replay_e2e.py tests/golden/cases.py openspec/changes/runtime-context-engineering/tasks.md
git commit -m "docs: complete M17 context engineering acceptance"
```

提交前确认 `openspec/changes/runtime-context-engineering/tasks.md` 的 18 项仅在对应实现和验证已实际通过后勾选，不预先批量勾选。
