# M17 Runtime Context Engineering Verification

Date: 2026-07-23
Branch: `codex/m17-runtime-context-engineering`
Change: `runtime-context-engineering`

## Result

M17 passed the build verification matrix. The implementation provides one shared,
server-owned context policy path for CLI, REPL, and HTTP; bounded and truthful tool
feedback; provider-normalized prompt denominators; CLI/session cache rates; and the
corresponding audit and documentation contracts.

## Verification Matrix

| Check | Command | Result |
| --- | --- | --- |
| Full test suite | `uv run pytest -q` | `1346 passed, 11 skipped` |
| Lint | `uv run ruff check .` | passed |
| Offline golden | `.venv/bin/python -m tests.golden.runner --output-dir /tmp/forgeagent-m17-golden-final` | `20/20 passed` |
| OpenSpec | `openspec validate runtime-context-engineering --strict` | valid |
| Whitespace | `git diff --check` | passed, no output |

The first full-suite run inside the managed sandbox produced 11 M16 loopback failures,
one packaging-build failure, and five stale `Step.run([])` policy-wiring fixture failures.
The fixture tests were corrected to supply the required system + initial-goal prefix.
The same full suite was then rerun outside the managed sandbox so loopback allocation and
`uv build` could execute; that fresh run produced the result above.

## Focused Evidence

- Provider denominator paths: Anthropic and OpenAI-compatible streaming/non-streaming,
  missing usage, and legal zero usage are covered.
- Context policy and feedback: prefix/latest-round fail-fast, complete-pair sliding,
  retained-message immutability, water filling, head/tail truncation, truthful
  continuation, and metadata overflow are covered.
- CLI and audit: ratio-of-sums, permanent unknown denominator, invalid usage, REPL
  session accumulation, transactional registry/context reload, injected factories, and
  numeric/null audit rates are covered.
- HTTP/M16 regression: bearer auth, strict request schema, cancellation, bounded safe
  projection, audit degradation/correlation, exact allowlist behavior, and MCP
  auto-approve isolation passed the combined regression suite.
- Long replay: a deterministic small-window task slides complete rounds, preserves the
  stable prefix and retained pair values, exposes the truncation protocol, preserves the
  original `ToolOutcome`, and still completes.

## Residual Limits

- Token estimation is intentionally local and approximate; provider tokenizers can
  still reject an edge request through the existing structured client-error path.
- No live provider API was called. Provider adapter tests use representative injected
  SDK response shapes.
- M17 provides sliding-window retention, not semantic summarization; summarization is
  outside this milestone.
