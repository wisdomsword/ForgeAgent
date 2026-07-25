# P2/P3 Runtime Resilience and Evidence Verification

## Outcome

P2/P3 are handled in one Comet change. The implementation adds host-frozen Evaluator
checks, an executable MCP hung-call regression, and bounded search fallback. Native
tool-call streaming assembly remains covered. No claim is made for unexecuted external
model calls or unavailable container platforms.

## Implemented Contracts

- `RunCheck` accepts only a registered check ID. A trusted host owns argv, environment,
  timeout and injection; standard CLI/HTTP schemas do not expose this authority.
- Checks reject all symlinks and special files, copy the project into a temporary tree,
  and run only current-Python invocations through a restricted audit-hook worker. Reads
  and writes stay in the copy; network, spawn, fork, exec and process-signal control are denied. Output is drained
  with a fixed head/tail memory cap. Timeout or cancellation terminates the POSIX group.
- Cancellation after Planner/Generator/Evaluator boundaries does not construct the next
  role or rejection attempt. Provider calls remain cooperatively cancellable only.
- The formerly skipped MCP hung-call test now launches a real local stdio server whose
  tool never returns, verifies the fixed deadline, invalidation and bounded close.
- Search tries the preferred built-in engine and then the other engine at most once.
  Each request independently uses the existing SSRF and redirect policy. Result/error
  precedence is: any results, blocked, unavailable, then two zero-result successes.

## Evidence Matrix

| Evidence | Result |
| --- | --- |
| Final full pytest after review fixes | `2125 passed, 10 skipped` with a fresh temporary uv cache |
| Latest sandbox full pytest | `2101 passed, 12 failed, 22 skipped`; 11 loopback and 1 package-build environment failures |
| Check/collaboration/MCP focused suite | post-hardening security and contract suite `329 passed` |
| Search focused suite | `27 passed` |
| Search + SSRF + CLI adjacent suite | `108 passed, 2 skipped` |
| Native tool-call silent aggregation fallback | `1 passed, 25 deselected` |
| Container + MCP matrix | `219 passed, 10 skipped`; all skips are Docker daemon/image availability checks |
| Offline golden | `20/20 passed` |
| Ruff | format check and lint passed |
| Package build | wheel and sdist built; a stale shared uv cache entry first broke dependency installation, while a fresh temporary cache passed the complete packaging test |
| OpenSpec | strict `18/18` passed before archive |
| Host | macOS 26.5.1, Darwin arm64 |
| Docker | CLI 29.2.1 present; daemon unavailable after bounded Docker Desktop startup wait |
| Linux Docker / Podman | not available in this environment; not verified |
| Real-model golden / single-Triad / credentialed Evaluator | credentials detected, but execution was rejected because repository-derived payload/destination external disclosure was not specifically authorized; not verified |

## P3 Disposition

- Native tool-call stream fragment assembly is already implemented and its focused
  fallback regression passes.
- Persistent REPL history remains deferred until users need cross-process/session recall
  and a reviewed storage, redaction, retention and opt-out contract exists.
- Semantic summaries remain deferred until sliding-window eviction demonstrably harms
  real workloads and a deterministic evaluation set can show benefit over extraction.
- Audio/video input remains deferred until at least one configured provider and CLI/HTTP
  transport require it, with size/type/storage and cost limits designed first.
- Response-side multimodal output remains deferred until a consumer needs typed binary
  artifacts and an explicit rendering/storage/safe-projection contract.
- Model routers, schedulers, plugin markets, team memory/approval, MCP Apps UI and memory
  confidence/decay remain outside this change; they require separate user demand and design.

## Residual Risks

- `RunCheck` uses Python audit-hook isolation rather than an OS/container sandbox. Native
  or kernel bypasses and hostile same-host copy/check races remain residual risks.
- Cancellation cannot asynchronously kill an in-flight provider call. MCP relies on its
  SDK deadline and session-generation invalidation.
- Search HTML remains provider-layout dependent even with fallback.
- Docker and real-provider evidence must be rerun in an authorized, available environment
  before claiming those matrices pass.

## Review Closure

The thorough segment review found five Important issues: host-privileged project checks,
unbounded output storage/readback, incomplete descendant termination, stale successful
MCP results, and a cancellation window before Evaluator construction. The fixes add the
restricted Python worker, streaming bounded capture, unconditional POSIX group SIGKILL
attempt after grace, post-await MCP generation/session validation, and role-start guards.
The final focused suite passed `329/329`; final full pytest passed `2125/2125` with
10 Docker environment skips. A second self-review also added process-signal denial and
removed stale fake-session wording from the design/spec/plan evidence chain.
