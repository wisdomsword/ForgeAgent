---
comet_change: harden-client-lifecycle-and-input-contracts
role: technical-design
canonical_spec: openspec
---

# Client Lifecycle and Input Contracts Design

## 1. Context and Current Failure Modes

ForgeAgent 的 `ModelClient` 是 provider 请求、Task、CLI、HTTP 和协作层之间的资源边界。目前有四个相互关联的问题：

1. OpenAI-compatible 与 Anthropic client 在每次普通请求和流式请求中分别实例化 SDK client，连接池无法跨请求复用，且 SDK 的关闭方法没有确定性调用。
2. `Task.close()` 只关闭 backend；部分 CLI/evaluate/smoke 入口创建 client 后没有统一的 `finally` 清理。HTTP 与协作路径已有部分关闭逻辑，但所有权规则不够集中，容易在提前返回或异常路径发生漂移。
3. `GenerationParams`、`ModelCapability` 和 `ModelEntry` 接受零值、负值以及非有限超时。provider request builder 的 truthiness 回退又把“未提供”和“非法值”混为一谈。
4. repository lifecycle verifier 用 `ast.dump(node, include_attributes=False)` 作为固定摘要。Python 3.11 没有 `FunctionDef.type_params`，Python 3.12+ 有该字段，Python 3.14 对空字段的 dump 表示又有变化，因此同一源码在支持的解释器上产生不同摘要。

本 change 只修正上述契约，不引入 Rust/FFI、不增加依赖、不拆分大型业务模块、不改变 provider 请求形状、CLI/HTTP 公开输出或已有 sandbox/权限边界。

## 2. Goals and Non-Goals

### Goals

- 为 `ModelClient.close()`、provider SDK client、Task 与入口层建立清晰、可测试的所有权规则。
- 在每个 provider client 实例内懒创建并复用一个 SDK client；普通与流式请求共享该实例；关闭幂等且最多执行一次。
- 所有创建 client/Task 的入口在成功、预检失败、提前返回、取消和异常时完成有界清理。
- 在 Pydantic/registry 边界拒绝明确非法的零、负、NaN 和无穷数值。
- 让 lifecycle verifier 摘要在 Python 3.11、3.12、3.14 上稳定，同时仍能检测受保护源码变化。

### Non-Goals

- `Task.close()` 不关闭调用方注入或共享的 `ModelClient`。
- 不改变 provider 参数翻译、重试/错误分类、CLI 文本、HTTP schema、Task 终态或审计公开投影。
- 不新增温度范围、厂商特定能力关系或新的配置面。
- 不引入新依赖，不做 Rust 重写，不借本 change 拆分 Memory/MCP/Collaboration/CLI。
- 不把 SDK close 失败升级为主流程失败；只记录固定类型安全日志并继续其他清理。

## 3. Ownership Model

### 3.1 Layers and responsibilities

```text
CLI / HTTP / evaluation entry
    owns ModelClient created by factory
    owns Task created for one execution
    finally: Task.close() -> ModelClient.close()

Task
    owns backend, runtime-local state, and task resources
    MUST NOT close caller-supplied ModelClient

Provider ModelClient
    owns lazily-created SDK client only when using default transport
    injected transport remains caller-owned
    close(): idempotent, bounded, safe-log-only on SDK close failure
```

The existing call sites that already close a Task and then its client remain authoritative. New or corrected call sites must follow the same order: first Task-owned resources, then the ModelClient owned by that entry point. A shared REPL client remains open for the session and closes only when the session ends.

### 3.2 `ModelClient.close()` contract

Add a concrete no-op `close()` method to the abstract base rather than making every test double implement a new abstract method. This preserves compatibility for injected `MockClient` implementations. Provider subclasses override it to close their own SDK object.

The provider lifecycle state has three relevant facts:

- SDK object reference is initially absent (lazy construction).
- `close()` has been requested; after this point the provider client cannot silently reopen.
- close has already been attempted; repeated calls return without invoking SDK close again.

The implementation must not close an injected transport. The existing transport injection seam remains used by unit tests and custom callers.

### 3.3 Close error policy

The owner invokes cleanup in `finally`. Cleanup catches SDK close failures at the boundary, emits a fixed event/type-safe message without exception text, and continues later cleanup sites. The original task result, provider error, cancellation, or process-control signal remains authoritative. This avoids turning a secondary cleanup failure into a misleading success/failure projection while still leaving an auditable signal.

## 4. Provider Client Design

### 4.1 OpenAI-compatible client

Keep lazy SDK import. Add one private SDK-client slot on the provider object and a small accessor used by both `_make_sdk_transport()` and `_make_sdk_stream_transport()`. The accessor constructs `openai.OpenAI(api_key=..., base_url=...)` only on first request. Both transport closures call the same `chat.completions.create` object.

`close()` checks the slot; if absent it only records the closed state. If present and not previously closed, it calls the SDK's public `close()` once. A request after close returns the existing structured client error path rather than creating a replacement SDK object.

### 4.2 Anthropic client

Use the same lifecycle shape, while retaining the existing lazy model-id resolution cache. The resolved model id remains independent from SDK client creation: resolving the effective model id must not create a second Anthropic SDK client. Both `messages.create` paths share one `anthropic.Anthropic` instance.

### 4.3 Streaming boundary

The provider object remains open while a stream is being iterated. The owner closes it after the Task/stream lifecycle has completed. No generator-level `finally` closes the provider object, because that could invalidate a caller-owned session or a concurrent operation. Existing mid-stream error classification remains unchanged.

## 5. Entry-Point Cleanup

Audit and correct these owner paths:

- `run_once`: close the client if context validation or Task construction fails; otherwise close Task and client in one outer `finally`.
- `run_smoke`: each model gets an isolated Task and client lifecycle; close before proceeding to the next model, including when a goal fails.
- `run_evaluate_command`: close after client preflight failure, manifest validation failure, persistence failure, evaluator result, and unexpected exceptions while preserving return codes.
- REPL and collaboration paths: preserve session-level sharing and existing task/client close order; only patch uncovered early returns.
- HTTP/client assembly: preserve service-owned shared resources and existing manager ordering; ensure request-scoped clients/tasks close on all terminal states.

Do not replace the existing HTTP service resource model with a global registry or `atexit` hook. Do not make Task responsible for a shared service client.

## 6. Input Contract Design

Use Pydantic field constraints already present in the project:

- `GenerationParams.max_output_tokens`: optional integer strictly greater than zero when provided.
- `GenerationParams.timeout_seconds`: finite float strictly greater than zero.
- `ModelCapability.context_window` and `.max_output_tokens`: integers strictly greater than zero.
- `ModelEntry.context_window` and `.max_output_tokens`: same positive integer constraints before registry projection.

The provider request builders use:

```python
output_limit = (
    params.max_output_tokens
    if params.max_output_tokens is not None
    else capability.max_output_tokens
)
```

This is intentionally not a provider-specific range validator. It only prevents an invalid model object from reaching request construction and preserves all existing positive/default behavior.

## 7. Cross-Version Verifier Design

Continue using AST parsing to locate the exact top-level functions and assignments required by the lifecycle contract. Instead of hashing `ast.dump`, use `ast.get_source_segment(source, node)` for each selected node, normalize line endings to `\n`, and join the segments with a fixed separator before UTF-8 SHA-256 hashing.

This representation is stable because it depends on the source text and selected node boundaries, not on interpreter-specific AST fields. It remains sensitive to any function or assignment source change, including formatting changes, so a governed change still requires digest reconfirmation. Missing functions or assignments continue to fail before hashing.

## 8. Test Strategy

### Unit tests

- Fake OpenAI/Anthropic SDK classes count constructions, request calls, and close calls; assert complete + stream share one SDK instance and repeated close is a no-op.
- Injected transports expose a `close_calls` counter; assert provider close does not touch them.
- Task tests assert backend closes while injected clients remain open.
- `run_once`, smoke, evaluate, HTTP, and collaboration tests cover success, preflight/manifest early return, cancellation, persistence error, provider error, and cleanup exception.
- Model tests cover zero, negative, NaN, infinity, defaults, and positive overrides.

### Cross-version tests

Run the focused lifecycle verifier under Python 3.11, 3.12, and 3.14. Assert unchanged source hashes identically and a temporary source mutation changes the digest. Do not write a new runtime dependency or rely on platform-specific tooling.

### Regression gates

Run targeted tests first, then full `pytest`, `ruff check`, `ruff format --check`, `uv build`, and OpenSpec strict. The public baseline must not gain skips. Existing M43 `keep_python` evidence remains unchanged and no rewrite trial is introduced.

## 9. Rollback and Failure Handling

Each provider/entry-point change is independently revertible. If a targeted test changes CLI bytes, HTTP responses, error codes, close ordering required by an existing contract, or stream behavior, revert only the affected patch before proceeding. If cross-version digest stability cannot be achieved without version branches or new dependencies, retain the current verifier and mark the compatibility task blocked rather than weakening the lifecycle gate.

No raw provider exception, secret, prompt, API key, path, or SDK close error text may enter public output or audit projections.
