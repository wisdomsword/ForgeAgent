# Task 2 Report: Interactive Feedback-Limit Display

Status: DONE

Implemented the interactive REPL feedback-limit boundary:

- Startup, successful `/model`, and successful `/reload` render effective round/tool limits.
- Explicit values below adaptive limits produce one bounded `feedback limit warning` line.
- Registry snapshots resolve from the selected capability; injected clients use a display-only probe with `close()` in `finally`.
- Noninteractive REPL paths never construct a display probe or emit a limit banner.
- Candidate model/reload limits are resolved before publishing state; failures retain the previous model, registry, context, and rendered limits.

Verification:

- `rtk uv --cache-dir /tmp/forgeagent-task2-uv-cache run pytest -q tests/test_cli.py tests/test_context.py` -> 399 passed.
- Focused REPL selection/startup tests -> 40 passed.
- `rtk uv --cache-dir /tmp/forgeagent-task2-uv-cache run ruff check src/forgeagent/_cli_repl.py src/forgeagent/cli.py tests/test_cli.py` -> passed.
- `rtk git diff --check` -> passed.
