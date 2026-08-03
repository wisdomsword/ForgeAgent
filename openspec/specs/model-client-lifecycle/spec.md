# model-client-lifecycle Specification

## Purpose
Define deterministic ownership, reuse, and bounded cleanup for model clients across Task, CLI, batch, HTTP, collaboration, and REPL boundaries without changing public results.

## Requirements
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
