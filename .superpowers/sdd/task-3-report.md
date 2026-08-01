# M47 Task 3 Report: finite positive model input contracts

## Status

DONE. Implemented the requested validation and explicit provider fallback in the
M47 shared worktree.

## TDD Evidence

RED:

```text
uv run pytest tests/test_models.py tests/test_model_registry.py \
  tests/test_openai_compatible_client.py tests/test_anthropic_client.py -q
15 failed, 94 passed in 0.33s
```

The new zero/negative limit and zero/negative/non-finite timeout cases failed
because the original models accepted those values.

GREEN:

```text
uv run pytest tests/test_models.py tests/test_model_registry.py \
  tests/test_openai_compatible_client.py tests/test_anthropic_client.py -q
109 passed in 0.30s
```

The existing request-builder tests also verify that `None` selects the model
ceiling and a positive override is preserved exactly.

## Changed Files

- `src/forgeagent/models.py`: shared positive integer and finite-positive float
  Pydantic annotations; applied to generation and capability limits.
- `src/forgeagent/model_registry.py`: applied the same positive limit contract to
  `ModelEntry`.
- `src/forgeagent/openai_compatible_client.py` and
  `src/forgeagent/anthropic_client.py`: replaced truthiness fallback with an
  explicit `is not None` branch.
- `tests/test_models.py` and `tests/test_model_registry.py`: invalid-value
  regression coverage.

## Quality Evidence

- Ruff check: passed.
- Ruff format check: passed.
- No dependencies, configuration, provider request shape, or public error
  projection changed.

## Risks / Concerns

- The new aliases are internal Pydantic annotations and keep the existing field
  names and defaults intact.
- Full-suite verification belongs to the M47 closeout task.
