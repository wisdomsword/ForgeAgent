# M47 Verification: client lifecycle and input contracts

- Status: verified pending Comet guard
- Date: 2026-08-02 (Asia/Shanghai)
- Change: `harden-client-lifecycle-and-input-contracts`
- Base: `599909d2849eb611f5310f78e5dadfb3fa4e4365`

## Gates

- `uv run pytest` -> `2781 passed, 11 skipped` (Python 3.14.3).
- `uv run ruff check .` -> `All checks passed!`.
- `uv run ruff format --check .` -> `147 files already formatted`.
- `uv build` -> source distribution and wheel built successfully.
- `openspec validate --all --strict` -> `37 passed, 0 failed`.
- Focused model/CLI/HTTP/collaboration/lifecycle tests under Python 3.11.15 -> `511 passed, 1 skipped`.
- The same focused suite under Python 3.12.12 -> `511 passed, 1 skipped`.
- The same focused suite under Python 3.14.3 -> `511 passed, 1 skipped`.
- Cross-version lifecycle digest probe with all supported interpreters visible -> `1 passed`; the subprocess is stdlib-only and does not require pytest in child interpreters.

## Two-pass review

### Pass 1: behavior and ownership

- Provider SDK clients are lazy, shared by complete/stream, and idempotently closed by the owning provider.
- Injected transports remain caller-owned; `Task.close()` does not close injected model clients.
- CLI, smoke, evaluate, HTTP construction-failure, and role paths close request-owned clients on normal, early-return, and exception paths while preserving Task-before-client ordering.
- Model generation parameters, capability declarations, and registry entries reject non-positive/non-finite values; provider fallback uses explicit `None` semantics.
- Lifecycle verifier hashes normalized selected source slices, preserving mutation detection without Python AST dump instability.

### Pass 2: leakage, scope, and attribution

- No new runtime dependencies, Rust rewrite, PyPI, tag, push, or release automation was introduced.
- Provider cleanup logs emit fixed provider labels only; raw SDK close errors are not projected.
- Existing evaluation/public error strings and request projections remain covered by the full suite.
- `git diff --check` is clean; the only post-task implementation adjustment was a minimal M41 line-budget correction and a self-contained verifier probe, both within approved lifecycle/verifier scope.

## Known skips and risks

- The 11 full-suite skips are existing environment-dependent tests (primarily container/runtime availability); no new skip was added by M47.
- Targeted suites report one existing repository-lifecycle environment skip in each interpreter run; the cross-version digest assertion itself runs and passes when all three interpreters are available.
- The build output in `dist/` is a local verification artifact and is not a publication action.

## Comet evidence

- OpenSpec strict validation passed before closeout.
- Verification report is registered in `.comet.yaml`; `branch_status: handled`.
- The verify phase guard remains the final state transition for this change.
