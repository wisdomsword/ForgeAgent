# Task 1: Shared feedback limit resolution

Status: DONE

## Implementation

- Added frozen `ResolvedFeedbackLimits` and pure `resolve_feedback_limits()` in `src/forgeagent/context.py`.
- Preserved the existing input-budget, adaptive-limit, explicit-limit precedence, positivity, and ordering formulas/error fragments.
- Wired `SlidingWindowContextPolicy` to retain the resolved object through `limits` while keeping its legacy integer properties.
- Updated HTTP registry/client context validators to return the shared result; existing validation-only callers may ignore it.
- Added resolver, policy, and validator regression coverage.

## Verification

- RED: `rtk uv --cache-dir /tmp/forgeagent-task1-uv-cache run pytest -q tests/test_context.py -k 'resolve_feedback_limits or policy_reserves_effective_output'` failed at collection because the new symbols were not yet defined.
- GREEN: `rtk uv --cache-dir /tmp/forgeagent-task1-uv-cache run pytest -q tests/test_context.py tests/test_cli.py -k 'context or policy or model_switch'` -> `80 passed, 316 deselected`.
- Lint: `rtk uv --cache-dir /tmp/forgeagent-task1-uv-cache run ruff check src/forgeagent/context.py src/forgeagent/_cli_http.py tests/test_context.py tests/test_cli.py` -> passed.
- Diff check: `rtk git diff --check` -> passed.

## Self-review

Two review passes confirmed that the resolver delegates the unchanged formulas and error semantics, explicit low values remain effective while only being flagged, and validator return values are backward-compatible for callers that only validate. No secrets, external config, unrelated files, or new dependencies were touched.
