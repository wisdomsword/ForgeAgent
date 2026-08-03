# Comet Design Handoff

- Change: harden-client-lifecycle-and-input-contracts
- Phase: design
- Mode: compact
- Context hash: 96eb8b4b437832b62de0430cad64da6112c03b5c760b6c4d4004802fd492e9dc

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/harden-client-lifecycle-and-input-contracts/proposal.md

- Source: openspec/changes/harden-client-lifecycle-and-input-contracts/proposal.md
- Lines: 1-31
- SHA256: 281336d1f5ac2618a4d6667c686ecd5db5ab615423f50df4d1cb14e87a3099e7

```md
## Why

ForgeAgent 当前在每次请求中重复创建 provider SDK client，CLI 各入口的资源所有权和关闭责任不一致，模型数值参数允许非法值继续传播，且生命周期 verifier 使用依赖解释器版本的 AST 摘要。结果可能是连接池无法复用、资源泄漏、供应商收到非法请求，以及同一源码在 Python 3.11+ 矩阵中得到不同的 verifier 结果。

## What Changes

- 定义 `ModelClient`、provider SDK client、`Task` 与 CLI/evaluate/smoke 入口的明确所有权。
- 在一个 provider client 实例内复用普通请求和流式请求的 SDK client，并提供幂等关闭。
- 确保 CLI、evaluate、smoke、HTTP 和协作路径在成功、预检失败、提前返回、取消和异常时释放自己创建的资源；不关闭外部注入的 client。
- 在模型与 registry 边界拒绝零值、负值、非有限超时和非法能力上限。
- 将 verifier 摘要改为跨 Python 稳定的表示，同时继续检测受保护 verifier 源码变化。
- 增加生命周期、输入校验和 Python 版本回归测试，不新增运行时依赖。

## Capabilities

### New Capabilities

- `model-client-lifecycle`：provider client 复用、所有权、幂等关闭和入口清理契约。
- `model-input-contracts`：生成参数与模型能力的有限正数校验契约。

### Modified Capabilities

- `repository-lifecycle-integrity`：要求 verifier 摘要在支持的 Python 解释器之间稳定。
- `cli-boundary-maintainability`：在保持 CLI 行为的同时，使 client/Task 清理确定且可验证。

## Impact

- 影响代码：`client.py`、两个 provider client、`task.py`、`cli.py`、`_cli_parser.py`、`_cli_http.py`、`models.py`、`model_registry.py`。
- 影响测试：模型 client、模型 registry、CLI 生命周期和 repository lifecycle 测试，以及跨版本 verifier 探针。
- 对外行为：合法请求和现有 CLI 输出保持不变；非法数值更早以结构化校验错误失败。
- 依赖：不新增运行时或测试依赖，继续支持 Python `>=3.11`。

```

## openspec/changes/harden-client-lifecycle-and-input-contracts/design.md

- Source: openspec/changes/harden-client-lifecycle-and-input-contracts/design.md
- Lines: 1-69
- SHA256: 5533cb94f1f9104cb91fe96a895007e259340a26c633ea392194ad9a73257da5

```md
## Context

当前 provider client 在每次 `complete()` 或 `stream()` 调用中创建 SDK client；入口层对 `Task` 与 `ModelClient` 的关闭责任也不完全一致。模型参数的 Pydantic 模型允许零值、负值和非有限值继续传播到请求构造层。仓库声明支持 Python 3.11 及以上，但生命周期 verifier 使用带解释器实现差异的 `ast.dump()` 固定摘要，导致同一源码在 3.11、3.12 和 3.14 得到不同结果。

本变更必须保持现有 provider 请求形状、CLI 输出、HTTP 行为、注入 transport 的测试替身和八个运行时依赖不变；不新增依赖，不做 Rust 或大模块重写。

## Goals / Non-Goals

**Goals:**

- 为 client、SDK transport、Task 和创建它们的入口建立可执行且可测试的所有权边界。
- 在一个 provider client 实例内复用 SDK client，普通请求与流式请求共享同一连接池，并提供幂等关闭。
- 确保 CLI、evaluate、smoke、HTTP 和已有协作路径在成功、失败、提前返回和异常时释放其拥有的资源。
- 在模型边界拒绝零、负数、非有限超时和非法能力上限。
- 使用跨 Python 3.11+ 稳定的 verifier 摘要输入，保留对受保护测试源码变化的检测能力。

**Non-Goals:**

- 不由 `Task` 关闭外部注入的 client，不改变调用方可复用 client 的语义。
- 不改变供应商 API 参数翻译、重试策略、错误公开文本或 HTTP schema。
- 不增加温度范围、上下文与输出上限的厂商特定关系，除非已有契约明确要求。
- 不添加运行时依赖，不拆分 Memory、MCP、Collaboration 或 CLI 大文件，不进行 Rust/FFI 试验。

## Decisions

### 1. Client ownership is explicit and local

`ModelClient` 提供幂等 `close()` 的统一生命周期面；基础实现默认为无操作，注入 transport 仍由外部拥有。Anthropic/OpenAI client 实例拥有各自创建的 SDK client，并在普通与流式 transport 中复用它。创建 client 的 CLI/HTTP/evaluation 入口负责在 `finally` 中关闭自己创建的 client；`Task.close()` 继续只关闭 backend 及 Task 自有资源。

替代方案：让 `Task.close()` 总是关闭 client。放弃该方案，因为 HTTP、REPL、协作和测试中存在共享或外部注入 client，隐式关闭会破坏复用和调用方所有权。

### 2. Provider SDK clients are lazy, shared, and idempotently closed

provider client 首次真正发送请求时才创建一个 SDK client；complete 与 stream 共用该实例。SDK 创建失败保持现有错误分类。`close()` 在已创建时调用 SDK 的关闭方法，重复调用不重建、不重复关闭；关闭后的再次请求按现有 client 错误语义失败。

替代方案：每次请求创建后立即关闭。放弃该方案，因为它无法复用连接池，且流式迭代的生命周期不能由请求函数安全包围。

### 3. Validate numeric contracts at the Pydantic boundary

`GenerationParams.timeout_seconds`、可选 `max_output_tokens`、`ModelCapability` 和 `ModelEntry` 的窗口/输出上限使用正数约束；浮点超时拒绝 NaN 和无穷。请求构造使用显式 `is not None` 判断，避免把合法边界判断与默认回退混在 `or` 表达式中。

替代方案：只在 provider 请求前检查。放弃该方案，因为 registry、context policy 和非 provider 调用会继续接受同一非法对象，错误发现太晚且语义不一致。

### 4. Verifier digest hashes canonical source slices

生命周期 verifier 仍通过 AST 定位顶层目标函数和赋值，但摘要 payload 改为这些节点在原文件中的规范化源码片段：统一换行并以 UTF-8 编码。这样保留源码变化检测，同时不把 Python AST 新增的空字段或 dump 格式绑定到解释器版本。

替代方案：继续使用 `ast.dump()` 并针对每个 Python 版本更新常量。放弃该方案，因为它会把兼容矩阵变成版本分支，且不能证明源码没有变化。

## Risks / Trade-offs

- [风险] provider SDK 的关闭方法在异常路径中再次抛错 → [缓解] close 采用幂等状态保护，并沿用固定的关闭错误投影；请求结果不被二次异常覆盖。
- [风险] 流式响应仍在迭代时提前关闭 SDK client → [缓解] client 只由拥有它的外层生命周期关闭；provider client 的 `stream()` 在迭代完成或调用方关闭时保持现有边界。
- [风险] 更早拒绝非法数值可能暴露此前被隐式接受的调用 → [缓解] 仅拒绝明确无效值，增加单测并保持所有正值和默认值行为不变。
- [风险] 源码片段摘要对格式调整敏感 → [缓解] 这是治理 verifier 的有意取舍：格式或正文变化都要求重新确认摘要，且摘要跨 Python 稳定。
- [风险] 入口清理改动触及多个控制流 → [缓解] 先补生命周期回归测试，再按入口小步实施；任一行为或输出回归即回滚该入口。

## Migration Plan

1. 先增加 client 复用/关闭、入口清理、参数拒绝和跨 Python digest 的失败测试。
2. 实现 provider client 生命周期与 `ModelClient.close()`，再接入 `run_once`、smoke、evaluate、HTTP 的拥有者清理。
3. 更新模型边界校验和请求构造的显式回退逻辑。
4. 替换 verifier digest，运行 Python 3.11、3.12、3.14 的 focused lifecycle 测试。
5. 运行全量 pytest、Ruff、format、构建和 OpenSpec strict；任一公开行为变化则只回滚本 change 的改动。

## Open Questions

- SDK close 失败是否只进入固定日志，还是需要加入现有公开错误投影？本 change 采用不改变公开错误投影的方案。
- 是否需要在后续 change 为 `ModelClient` 增加上下文管理器语法？当前不增加，以免扩大 public API。

```

## openspec/changes/harden-client-lifecycle-and-input-contracts/tasks.md

- Source: openspec/changes/harden-client-lifecycle-and-input-contracts/tasks.md
- Lines: 1-34
- SHA256: 42be5db591fcf47ef95884e9498e8bd35c7942066cecc6e48892eca09a5ef314

```md
## 1. 建立生命周期契约和回归覆盖

- [ ] 1.1 增加 `ModelClient.close()`、Task 不拥有注入 client、provider SDK 复用、重复关闭和注入 transport 所有权的专项测试。
- [ ] 1.2 增加 CLI、smoke、evaluate、HTTP 和异常路径测试，断言本调用创建的 Task/client 恰好关闭一次，并保持既有输出和状态投影。

## 2. 实现 provider client 生命周期

- [ ] 2.1 增加幂等的 `ModelClient.close()` 契约和共享 provider 生命周期状态，不改变注入 transport 行为。
- [ ] 2.2 重构 OpenAI-compatible 普通/流式 transport，懒创建并共享一个 SDK client，且只关闭一次。
- [ ] 2.3 重构 Anthropic 普通/流式 transport，懒创建并共享一个 SDK client，保留 model-id 解析和错误分类。
- [ ] 2.4 验证 provider 请求、流式请求、失败路径和关闭后行为。

## 3. 在所有权入口清理资源

- [ ] 3.1 更新 `run_once`、smoke、evaluate、REPL、协作和 HTTP 路径，确保成功、提前返回、取消和异常时关闭本路径创建的 client 与 Task。
- [ ] 3.2 保持 `Task.close()` 只负责 Task 自有 backend 资源，并审计已有关闭顺序的回归。
- [ ] 3.3 运行 CLI、HTTP、协作和资源生命周期专项测试，保留受支持的 monkeypatch 接缝。

## 4. 加固模型输入契约

- [ ] 4.1 为生成参数、模型能力和 registry entry 增加有限正数约束。
- [ ] 4.2 将两个 provider request builder 的输出上限回退从 truthiness 改为显式 `None` 判断。
- [ ] 4.3 增加零值、负值、NaN、无穷、默认值、正值覆盖和 registry 错误投影测试。

## 5. 稳定生命周期 verifier 兼容性

- [ ] 5.1 将解释器相关的 AST dump 摘要替换为跨 Python 3.11+ 稳定的规范化源码片段摘要。
- [ ] 5.2 增加跨版本专项 verifier 测试/探针，并保留对受保护 verifier 源码缺失或修改的检测。

## 6. 全量验证和收尾

- [ ] 6.1 在 Python 3.11、3.12、3.14 下运行模型、CLI、HTTP、协作和 lifecycle 专项测试。
- [ ] 6.2 运行全量 pytest、Ruff check、Ruff format check、`uv build` 和 OpenSpec strict，且不增加 skip。
- [ ] 6.3 做最终两轮评审，检查所有权泄漏、公开行为漂移、非法值遗漏、secret/raw exception 泄漏和未列出的依赖，并记录 Comet verify 结果。

```

## openspec/changes/harden-client-lifecycle-and-input-contracts/specs/cli-boundary-maintainability/spec.md

- Source: openspec/changes/harden-client-lifecycle-and-input-contracts/specs/cli-boundary-maintainability/spec.md
- Lines: 1-21
- SHA256: 4741c1cd59e9d14e0ae7f8753ad1242211e41e5a81b0672d6738f76b5586e76b

```md
## MODIFIED Requirements

### Requirement: Existing CLI and HTTP behavior remains unchanged

The extraction MUST preserve command names, option names, defaults, parser behavior, help bytes, stdout/stderr routing, exit codes, existing `forgeagent.cli` imports, supported monkeypatch locations, HTTP request/response shapes, cancellation semantics, and resource cleanup behavior. It MUST NOT add configuration, persistence, data migration, publication, tag, push, or package-index behavior. The lifecycle hardening MUST make cleanup deterministic without changing any successful or failed public projection.

#### Scenario: Existing help commands run
- **WHEN** the seven recorded top-level and subcommand help invocations are executed after lifecycle hardening
- **THEN** their exit codes and stdout/stderr SHA-256 values match the pre-change baseline byte for byte

#### Scenario: Existing boundary tests run
- **WHEN** CLI, collaboration integration, HTTP, startup, model, and full regression tests execute
- **THEN** all previously passing scenarios still pass and the change introduces no additional skip

#### Scenario: A test replaces a CLI dependency
- **WHEN** an existing test monkeypatches a supported `forgeagent.cli` class, callback, factory, or helper before invoking a façade entry point
- **THEN** the extracted implementation uses that replacement for the current call and still closes only resources owned by that call

#### Scenario: Early failure has no leaked client
- **WHEN** a CLI or evaluation command returns from preflight, persistence failure, cancellation, or exception
- **THEN** every client and Task created by that command has completed its bounded cleanup before the command returns

```

## openspec/changes/harden-client-lifecycle-and-input-contracts/specs/model-client-lifecycle/spec.md

- Source: openspec/changes/harden-client-lifecycle-and-input-contracts/specs/model-client-lifecycle/spec.md
- Lines: 1-45
- SHA256: 55f123bd40e1277f97b97551f75f5c46df0a597287b1f01a9004a7ab99ff1195

```md
## ADDED Requirements

### Requirement: Model clients expose deterministic ownership closure

`ModelClient` MUST expose an idempotent `close()` lifecycle operation. A caller that creates a client MUST close it on normal completion, early return, process-control exit, and exception. `Task.close()` MUST release Task-owned backend resources but MUST NOT close a client supplied by its caller.

#### Scenario: CLI-owned client completes normally
- **WHEN** a CLI entry point creates a `ModelClient` and the task succeeds
- **THEN** the entry point closes the client exactly once after Task-owned resources are released

#### Scenario: Task uses an externally supplied client
- **WHEN** a caller constructs `Task` with a client it owns and then calls `Task.close()`
- **THEN** Task closes its backend resources and leaves the supplied client open

#### Scenario: Entry point returns before Task creation
- **WHEN** client creation succeeds but context or manifest preflight returns an error
- **THEN** the entry point still closes the created client exactly once

### Requirement: Provider SDK clients are reused and closed once

OpenAI-compatible and Anthropic provider clients MUST lazily create at most one SDK client per provider client instance, MUST reuse it for complete and streaming calls, and MUST close it at most once. A close operation MUST NOT recreate an SDK client or silently reopen a closed provider client.

#### Scenario: Complete followed by stream
- **WHEN** one provider client performs a complete request and a stream request
- **THEN** both requests use the same underlying SDK client instance

#### Scenario: Repeated close
- **WHEN** a provider client is closed more than once
- **THEN** the underlying SDK close operation is invoked at most once and subsequent close calls return safely

#### Scenario: Injected transport remains external
- **WHEN** a provider client is constructed with an injected transport instead of its default SDK transport
- **THEN** provider close does not close or mutate the externally supplied transport

### Requirement: HTTP and batch paths preserve resource cleanup

HTTP task services, evaluation commands, smoke commands, collaboration adapters, and REPL-owned clients MUST preserve their existing result, output, cancellation, and error semantics while closing every resource they create on every terminal path.

#### Scenario: Batch smoke continues after one model
- **WHEN** smoke runs multiple models and one model returns a failure result
- **THEN** that model's Task and client are closed before the next model starts, and the remaining models still run

#### Scenario: HTTP task finishes or is cancelled
- **WHEN** an HTTP task reaches success, failure, cancellation, or shutdown
- **THEN** task, client, and manager resources close in the existing safe order without changing the response projection

```

## openspec/changes/harden-client-lifecycle-and-input-contracts/specs/model-input-contracts/spec.md

- Source: openspec/changes/harden-client-lifecycle-and-input-contracts/specs/model-input-contracts/spec.md
- Lines: 1-41
- SHA256: f3dc0eab5690103397265fb909f825d3c6a59dee1f083fe459ab4e26829be1e8

```md
## ADDED Requirements

### Requirement: Generation parameters reject invalid numeric values

`GenerationParams` MUST reject `max_output_tokens` when it is zero or negative. It MUST reject `timeout_seconds` when it is zero, negative, NaN, or infinite. Existing defaults and all positive finite values MUST remain accepted.

#### Scenario: Invalid generation limit
- **WHEN** a caller constructs `GenerationParams(max_output_tokens=0)` or with a negative value
- **THEN** model validation fails before provider request construction

#### Scenario: Invalid timeout
- **WHEN** a caller constructs `GenerationParams(timeout_seconds=0)`, a negative value, NaN, or infinity
- **THEN** model validation fails before Task execution

#### Scenario: Positive default remains compatible
- **WHEN** a caller constructs `GenerationParams()` or supplies a positive finite timeout and output limit
- **THEN** construction succeeds and existing provider defaults/translation remain unchanged

### Requirement: Registry capability limits are positive

`ModelCapability` and `ModelEntry` MUST reject zero or negative `context_window` and `max_output_tokens` values. Registry loading MUST fail with its existing structured registry error path when an entry violates these bounds.

#### Scenario: Invalid model registry entry
- **WHEN** a model entry declares a zero or negative context window or output ceiling
- **THEN** registry validation rejects the entry before it becomes selectable

#### Scenario: Valid large model entry
- **WHEN** a model entry declares positive integer capability limits within the existing configuration format
- **THEN** registry loading and capability projection remain unchanged

### Requirement: Request fallback distinguishes absence from invalidity

Provider request builders MUST use explicit `None` checks for optional output limits rather than truthiness fallback, so validation and defaulting cannot silently convert zero or other invalid values into a provider default.

#### Scenario: Explicit positive override
- **WHEN** `max_output_tokens` is a positive value
- **THEN** the provider request uses that exact value

#### Scenario: Omitted override
- **WHEN** `max_output_tokens` is `None`
- **THEN** the provider request uses the model capability ceiling as before

```

## openspec/changes/harden-client-lifecycle-and-input-contracts/specs/repository-lifecycle-integrity/spec.md

- Source: openspec/changes/harden-client-lifecycle-and-input-contracts/specs/repository-lifecycle-integrity/spec.md
- Lines: 1-21
- SHA256: d2d0e07f1e80cf2803b273ca4ddfbe453e30b8053090ec695a8b7359960c4db5

```md
## MODIFIED Requirements

### Requirement: Reconciled runtime claims retain executable verifiers

When a completed runtime capability is reconciled into the current baseline, ForgeAgent SHALL retain executable regression tests for its security, compatibility, and trust-boundary claims. Historical milestone text or an archived change alone MUST NOT be treated as current executable proof. Any verifier bundle digest MUST be computed from a representation that is stable across every supported Python interpreter while still changing when a selected verifier function or assignment source changes.

#### Scenario: Runtime Skill exit contract is reconciled
- **WHEN** M45 audits the completed M34 runtime Skill exit contract
- **THEN** the current test suite directly verifies valid version 2 contracts, fail-closed invalid inputs, legacy compatibility, secret masking, immutable exit metadata, and effective trust digest changes

#### Scenario: Supported Python versions inspect the same verifier
- **WHEN** the lifecycle verifier runs under Python 3.11, 3.12, and 3.14 against unchanged source
- **THEN** the bundle digest is identical on all supported interpreters

#### Scenario: A protected verifier source changes
- **WHEN** a selected verifier function or assignment source changes
- **THEN** the digest changes and the lifecycle contract fails until the change is explicitly reconfirmed

#### Scenario: A critical verifier disappears
- **WHEN** the M34 implementation and specifications remain but its executable contract tests are removed
- **THEN** the repository lifecycle verification fails before the baseline is declared complete

```
