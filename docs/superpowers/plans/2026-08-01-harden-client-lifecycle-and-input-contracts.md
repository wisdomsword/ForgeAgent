---
change: harden-client-lifecycle-and-input-contracts
design-doc: docs/superpowers/specs/2026-08-01-harden-client-lifecycle-and-input-contracts-design.md
base-ref: 599909d2849eb611f5310f78e5dadfb3fa4e4365
archived-with: 2026-08-03-harden-client-lifecycle-and-input-contracts
---

# Harden Client Lifecycle and Input Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 收敛 ForgeAgent 的模型 client 生命周期、入口资源所有权、数值输入校验和跨 Python verifier 契约，同时保持既有 CLI/HTTP 行为。

**Architecture:** provider client 懒创建并拥有一个 SDK client，`ModelClient.close()` 幂等；创建 client 的入口负责关闭，`Task.close()` 只关闭 Task 自有 backend。模型边界用 Pydantic 有限正数约束，生命周期 verifier 仍用 AST 定位但摘要规范化源码片段。

**Tech Stack:** Python 3.11+、Pydantic v2、OpenAI SDK、Anthropic SDK、pytest、Ruff、uv、OpenSpec/Comet。

## Global Constraints

- 保持 Python `>=3.11` 支持，不增加 runtime/test dependency。
- 保持现有 provider 请求形状、错误分类、CLI 输出、HTTP schema、Task 终态和审计公开投影。
- `Task.close()` 不得关闭外部注入或共享的 `ModelClient`。
- SDK close 失败只记录固定类型安全日志，不覆盖主流程结果，不输出 raw exception、secret、prompt、API key 或路径。
- 不新增温度范围、厂商特定能力关系或新的配置面。
- 不做 Rust/FFI 重写，不拆分 Memory、MCP、Collaboration 或 CLI 大模块。
- 每个生产修改必须先有一个能正确失败的回归测试，并在实现后运行对应 focused tests。

---

### Task 1: Lock lifecycle ownership and provider reuse behavior

**Files:**
- Modify: `src/forgeagent/client.py:36-80`
- Modify: `src/forgeagent/openai_compatible_client.py:1-335`
- Modify: `src/forgeagent/anthropic_client.py:1-352`
- Test: `tests/test_openai_compatible_client.py`
- Test: `tests/test_anthropic_client.py`
- Test: `tests/test_task.py`

**Interfaces:**
- `ModelClient.close(self) -> None` is a concrete, idempotent base method so existing test doubles remain valid.
- Provider subclasses own only SDK objects created by their default transports; injected transports remain external.

- [x] **Step 1: Write failing provider lifecycle tests**

  Add fake SDK classes that count constructor, request, and close calls. Assert one OpenAI/Anthropic SDK instance serves both complete and stream, repeated provider close calls close once, and injected transports receive no close call. Add a Task test asserting `Task.close()` closes its backend but leaves an injected client open.

- [x] **Step 2: Run the focused tests and verify the intended failures**

  Run:

  ```bash
  uv run pytest tests/test_openai_compatible_client.py tests/test_anthropic_client.py tests/test_task.py -q
  ```

  Expected: the new reuse/close assertions fail because each transport currently constructs a new SDK client and `ModelClient` has no lifecycle implementation.

- [x] **Step 3: Implement the minimal lifecycle contract**

  Add a concrete no-op `ModelClient.close()`. In each provider client, add a private lazy SDK slot and closed flag; make complete and stream transport accessors share that slot. Close only the owned SDK slot once. Do not add a close call to injected transports or `Task.close()`.

- [x] **Step 4: Run focused tests and existing provider tests**

  Run:

  ```bash
  uv run pytest tests/test_openai_compatible_client.py tests/test_anthropic_client.py tests/test_task.py -q
  ```

  Expected: all focused tests pass with no raw close exception in output.

- [x] **Step 5: Commit the provider lifecycle unit**

  ```bash
  git add src/forgeagent/client.py src/forgeagent/openai_compatible_client.py src/forgeagent/anthropic_client.py tests/test_openai_compatible_client.py tests/test_anthropic_client.py tests/test_task.py
  git commit -m "fix: reuse and close provider clients deterministically"
  ```

### Task 2: Make CLI and evaluation ownership deterministic

**Files:**
- Modify: `src/forgeagent/cli.py:544-581,1314-1338`
- Modify: `src/forgeagent/_cli_parser.py:259-306`
- Modify: `src/forgeagent/_cli_http.py` only where request-scoped client/task cleanup is missing
- Test: `tests/test_cli.py`
- Test: `tests/test_http_server.py`
- Test: `tests/test_http_task_service.py`

**Interfaces:**
- Each owner path closes `Task` before its owned `ModelClient`.
- Session-shared REPL and service-shared HTTP clients remain open until their existing session/service shutdown boundary.

- [x] **Step 1: Add failing early-return and exception cleanup tests**

  Extend existing close-tracking fakes to cover `run_once` client-factory/context-preflight failure, `run_smoke` model-to-model cleanup, evaluate manifest/persistence failure, and HTTP request cancellation/terminal cleanup. Assert the existing return code and response projection remain unchanged.

- [x] **Step 2: Run the new lifecycle tests before implementation**

  Run:

  ```bash
  uv run pytest tests/test_cli.py tests/test_http_server.py tests/test_http_task_service.py -q
  ```

  Expected: new assertions identify at least the currently unclosed `run_once`/smoke/evaluate paths without changing unrelated baseline tests.

- [x] **Step 3: Implement `finally`-based cleanup at each owning entry point**

  Wrap client creation through terminal return in one cleanup boundary. For smoke, create and close one Task per goal or one explicitly owned model session according to existing behavior, ensuring a failed goal does not skip the model client close. For evaluate, close after preflight failure, persistence failure, evaluation result, and unexpected exception. Preserve existing HTTP service shared-resource ordering and patch only uncovered request-scoped paths.

- [x] **Step 4: Run focused CLI/HTTP/collaboration lifecycle tests**

  Run:

  ```bash
  uv run pytest tests/test_cli.py tests/test_http_server.py tests/test_http_task_service.py tests/test_collaboration_integrations.py -q
  ```

  Expected: all tests pass and no output/status/HTTP shape changes are reported.

- [x] **Step 5: Commit the entry-point ownership unit**

  ```bash
  git add src/forgeagent/cli.py src/forgeagent/_cli_parser.py src/forgeagent/_cli_http.py tests/test_cli.py tests/test_http_server.py tests/test_http_task_service.py
  git commit -m "fix: close owned CLI and evaluation resources"
  ```

### Task 3: Enforce finite positive model input contracts

**Files:**
- Modify: `src/forgeagent/models.py:60-72,165-184`
- Modify: `src/forgeagent/model_registry.py:61-72`
- Modify: `src/forgeagent/openai_compatible_client.py:117-124`
- Modify: `src/forgeagent/anthropic_client.py:137-143`
- Test: `tests/test_models.py`
- Test: `tests/test_model_registry.py`
- Test: `tests/test_openai_compatible_client.py`
- Test: `tests/test_anthropic_client.py`

**Interfaces:**
- `GenerationParams.max_output_tokens` remains optional but is strictly positive when supplied.
- `GenerationParams.timeout_seconds` is finite and strictly positive.
- Model capability and registry window/output limits are strictly positive integers.

- [x] **Step 1: Add failing invalid-value tests**

  Add parametrized cases for zero and negative token/context limits, timeout zero/negative/NaN/infinity, plus positive/default compatibility. Add request-builder assertions that `None` uses the capability ceiling and a positive override is preserved exactly.

- [x] **Step 2: Run model and request tests to verify RED**

  Run:

  ```bash
  uv run pytest tests/test_models.py tests/test_model_registry.py tests/test_openai_compatible_client.py tests/test_anthropic_client.py -q
  ```

  Expected: invalid values currently construct successfully or use truthiness fallback, so the new cases fail.

- [x] **Step 3: Add Pydantic constraints and explicit fallback**

  Use existing Pydantic `Field` constraints and finite float validation. Replace `params.max_output_tokens or capability.max_output_tokens` with an explicit `is not None` branch in both provider builders. Keep registry error wrapping and positive existing entries unchanged.

- [x] **Step 4: Run focused model tests and inspect error projection**

  Run:

  ```bash
  uv run pytest tests/test_models.py tests/test_model_registry.py tests/test_openai_compatible_client.py tests/test_anthropic_client.py -q
  ```

  Expected: all invalid values fail before request construction, all defaults/positive overrides pass, and registry failures retain the existing structured exception path.

- [x] **Step 5: Commit the input-contract unit**

  ```bash
  git add src/forgeagent/models.py src/forgeagent/model_registry.py src/forgeagent/openai_compatible_client.py src/forgeagent/anthropic_client.py tests/test_models.py tests/test_model_registry.py tests/test_openai_compatible_client.py tests/test_anthropic_client.py
  git commit -m "fix: reject invalid model input limits"
  ```

### Task 4: Stabilize repository lifecycle verifier across Python versions

**Files:**
- Modify: `tests/test_repository_lifecycle.py:69-94`
- Test: `tests/test_repository_lifecycle.py`

**Interfaces:**
- `_verifier_bundle_digest(path, required_functions, required_assignments) -> tuple[str, list[str]]` keeps its existing signature and missing-symbol behavior.

- [x] **Step 1: Add a failing cross-version digest assertion**

  Add a focused assertion or subprocess probe that computes the unchanged M34 Skill bundle digest under Python 3.11, 3.12, and 3.14 and expects one value; retain a mutation case that changes a selected source segment and expects a different digest.

- [x] **Step 2: Run the verifier tests before implementation**

  Run:

  ```bash
  uv run --isolated --python 3.11 pytest tests/test_repository_lifecycle.py::test_m34_runtime_skill_contract_keeps_executable_verifiers -q
  uv run --isolated --python 3.12 pytest tests/test_repository_lifecycle.py::test_m34_runtime_skill_contract_keeps_executable_verifiers -q
  ```

  Expected: 3.11 and 3.12 fail with different hashes while 3.14 is the current expected value.

- [x] **Step 3: Hash normalized source slices selected by AST**

  Preserve AST lookup and missing-name checks. Use `ast.get_source_segment` for each selected top-level node, normalize CRLF/CR to LF, join with a fixed separator, and hash UTF-8 bytes. Update the stored digest only after the same source produces one stable value on all supported interpreters.

- [x] **Step 4: Run all three interpreter-focused verifier checks**

  Run:

  ```bash
  uv run --isolated --python 3.11 pytest tests/test_repository_lifecycle.py::test_m34_runtime_skill_contract_keeps_executable_verifiers -q
  uv run --isolated --python 3.12 pytest tests/test_repository_lifecycle.py::test_m34_runtime_skill_contract_keeps_executable_verifiers -q
  uv run --isolated --python 3.14 pytest tests/test_repository_lifecycle.py::test_m34_runtime_skill_contract_keeps_executable_verifiers -q
  ```

  Expected: all three pass with the same digest and source mutation detection intact.

- [x] **Step 5: Commit the compatibility verifier unit**

  ```bash
  git add tests/test_repository_lifecycle.py
  git commit -m "test: make lifecycle verifier digest cross-version stable"
  ```

### Task 5: Full regression and closeout evidence

**Files:**
- Modify: `openspec/changes/harden-client-lifecycle-and-input-contracts/tasks.md` to mark completed tasks only after verification
- Create: `docs/superpowers/reports/2026-08-01-harden-client-lifecycle-and-input-contracts-verify.md`
- Modify: `milestones/milestone_047.md`
- Modify: `milestones/latest`

**Interfaces:**
- No runtime interface changes beyond the approved lifecycle and validation contracts.

- [x] **Step 1: Run full test and quality gates**

  Run:

  ```bash
  uv run pytest
  uv run ruff check .
  uv run ruff format --check .
  uv build
  openspec validate --all --strict
  ```

  Expected: all tests pass with no additional skips, Ruff and format are clean, build succeeds, and OpenSpec strict validation passes.

- [x] **Step 2: Run final two-pass review**

  First pass checks ownership/close order, stream reuse, public behavior, invalid-value coverage, and verifier stability. Second pass checks raw exception/secret/path leakage, dependency diff, accidental docs/runtime scope expansion, and clean worktree attribution.

- [x] **Step 3: Record evidence and milestone state**

  Write exact commands and outputs to the verification report, update milestone 047 and `milestones/latest`, mark OpenSpec tasks, and run Comet verify guard. Do not run PyPI, tag, release automation, or force push.

- [x] **Step 4: Commit the verified change**

  ```bash
  git add src tests openspec/changes/harden-client-lifecycle-and-input-contracts docs/superpowers/specs docs/superpowers/plans docs/superpowers/reports milestones/latest milestones/milestone_047.md
  git commit -m "fix: harden client lifecycle and input contracts"
  ```

## Execution Order

Task 1 establishes the client lifecycle interface. Task 2 consumes it at owning entry points. Task 3 is independent of Task 2 but follows it to keep provider files in one review unit. Task 4 is independent and can be executed after Task 1. Task 5 requires all previous tasks and is the only point that updates milestone evidence.

## Plan Self-Review

- Spec coverage: lifecycle requirements map to Tasks 1-2; input requirements map to Task 3; verifier requirements map to Task 4; no-public-regression and closeout requirements map to Tasks 2 and 5.
- Placeholder scan: no `TBD`, `TODO`, or vague “handle edge cases” instructions remain.
- Type consistency: `ModelClient.close()`, `_verifier_bundle_digest(...)`, and all file paths are consistent across tasks.
- Scope check: no dependency, Rust, publication, tag, or large-module extraction task is present.
