# Task 3 Critical Review Fix Report

## Status

Fixed the confirmation and outcome disclosure findings on top of `a370811`.
Changes remain limited to the Task 3 allowlist.

## RED Evidence

### Review regressions against `a370811`

Tests were added before production changes and run with:

```text
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_cli.py tests/test_web_file_tools.py tests/test_tools.py -q
```

Result:

```text
9 failed, 99 passed in 0.27s
```

Expected failures:

```text
test_confirmation_summary_redacts_url_fragment
test_confirmation_summary_never_echoes_malformed_url_material[https:///sensitive/path#fragment-secret-value]
test_confirmation_summary_never_echoes_malformed_url_material[sensitive/path?token=query-secret#fragment-secret-value]
test_confirmation_summary_preserves_normalized_project_relative_filewrite_path
test_confirmation_summary_shows_cwd_contained_absolute_filewrite_path_as_relative
test_confirmation_summary_limits_external_filewrite_path_to_basename
test_webfetch_restricted_tier_confirmer_denial_blocks_fetch
test_file_write_escaping_root_is_blocked
test_file_write_restricted_tier_confirmer_denial_blocks_write
```

The malformed IPv6 case already returned the fixed malformed-URL summary and therefore
passed in RED, while the two parseable missing-host forms exposed the reconstruction bug.

### Independent original Task 3 TDD baseline

A disposable source tree was created from `git archive 797a3e7`; the three Task 3 test
files were overlaid exactly from `a370811`. The archived source was selected through
`PYTHONPATH` without changing branch history:

```text
PYTHONPATH=/tmp/forgeagent-task3-red-797a3e7.7pgjJs/source/src UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest /tmp/forgeagent-task3-red-797a3e7.7pgjJs/source/tests/test_cli.py /tmp/forgeagent-task3-red-797a3e7.7pgjJs/source/tests/test_web_file_tools.py /tmp/forgeagent-task3-red-797a3e7.7pgjJs/source/tests/test_tools.py -q
```

Result:

```text
10 failed, 92 passed in 0.28s
```

Failures covered the four absent confirmation formatters, terminal/non-terminal and
REPL confirmer wiring, and the WebFetch/FileWrite/MCP missing-channel distinctions.

## Fixes

- WebFetch explicit rejection now returns a fixed detail without the requested URL.
- URL summaries require an HTTP(S) scheme and hostname, use `urllib.parse` components,
  redact userinfo and sensitive query values, mask known secret values in paths, and
  replace every non-empty fragment with `REDACTED`.
- Missing-host and malformed URLs return only `<redacted malformed URL>`.
- FileWrite confirmation preserves normalized relative paths and cwd-contained absolute
  paths as project-relative; external absolute paths display only `.../<basename>`.
- FileWrite explicit rejection and project-root validation failures return fixed details
  without raw paths or content.
- Non-terminal Rich consoles in tests now set `force_terminal=False` explicitly.

## GREEN Evidence

```text
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_cli.py tests/test_web_file_tools.py tests/test_tools.py -q
108 passed in 0.20s

UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run ruff check .
All checks passed!

UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest -q
479 passed, 13 skipped in 12.68s

git diff --check
exit 0
```

## Files

- `src/forgeagent/cli.py`
- `src/forgeagent/tools.py`
- `tests/test_cli.py`
- `tests/test_web_file_tools.py`
- `.superpowers/sdd/task-3-fix-report.md`

`tests/test_tools.py` required no review-fix edit; its existing MCP ordering and
missing-channel checks remain green.

## Risk Signals And Accepted Minor

- Well-formed URL paths remain visible so users can identify the request; known
  environment-secret values are masked and fragments are never shown.
- FileWrite filesystem write errors after successful path validation retain the existing
  operating-system error detail; the reviewed rejection and root-validation paths are
  fixed and covered.
- MCP `autoApprove` ordering, the public `Confirmer` type, and Survey `--interactive`
  semantics were not changed.
- Minor 6 accepted without change: the one-shot wiring tests retain their local spies
  because parameterizing them would hide distinct terminal, stdin, asker, and MCP setup
  without a meaningful reduction in code.
- No dependency, framework, global environment mutation, branch rewrite, or unrelated
  file edit was introduced.
