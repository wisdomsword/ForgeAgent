# Task 3 Report: Protocol Execution Guidance

Status: DONE

Implemented the fixed protocol routing guidance:

- Pure knowledge questions may be answered directly.
- Missing essential information uses Survey, then continues the same Task with the answer as feedback.
- Built-in tools are selected directly only when one tool can finish the whole goal.
- Recursive traversal, hashing, aggregation/transformation, cross-file comparison, and many-result output use Python through Exec.
- Large results are written completely to an approved path, with the final response limited to count, summary, and path.
- Shallow or truncated samples cannot be reported as complete.

The protocol's existing ToolCall examples, argument schemas, utils API, identity section order, sandbox/confirmation/terminal semantics, and prose completion behavior were preserved.

Added a mock replay regression covering Survey -> Exec writing a complete file -> done. It asserts the same Task retains the Survey answer and feedback context between model requests and executes the expected tools in order.

Verification:

- `rtk uv --cache-dir /tmp/forgeagent-task3-green-cache run pytest tests/test_identity.py tests/test_task.py -q` -> 148 passed.
- `rtk uv --cache-dir /tmp/forgeagent-task3-ruff-cache run ruff format --check tests/test_identity.py tests/test_task.py` -> passed.
- `rtk uv --cache-dir /tmp/forgeagent-task3-ruff-cache run ruff check tests/test_identity.py tests/test_task.py` -> passed.
- `rtk git diff --check` -> passed.

Review revision: two passes checked the six requested routing rules against the prompt and verified that the replay test asserts both feedback retention and Survey/Exec ordering. No further issues found.
