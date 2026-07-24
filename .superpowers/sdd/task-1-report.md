# Task 1 Report: M21 durable Loop checkpoints

## Status

`DONE_WITH_CONCERNS`

## RED

模型测试先于 `src/forgeagent/loop.py` 创建并执行：

```text
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_loop_checkpoint.py -k 'model or budget or report'
ERROR tests/test_loop_checkpoint.py
ModuleNotFoundError: No module named 'forgeagent.loop'
1 error in 0.12s
```

严格模型实现后的额外边界 RED：

```text
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_loop_checkpoint.py -k 'report'
FAILED test_report_model_rejects_coerced_counters_and_nonfinite_elapsed_time
Failed: DID NOT RAISE ValidationError
1 failed, 1 passed, 29 deselected in 0.09s
```

该失败证明 `LoopReport` 初始版本会接受 `bool` 计数；随后增加严格计数与有限数校验。

## GREEN

```text
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_loop_checkpoint.py -k 'model or budget or report'
21 passed, 10 deselected in 0.09s

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_loop_checkpoint.py -k 'store or atomic or symlink or checkpoint_tool or registry'
10 passed, 21 deselected in 0.09s

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_loop_checkpoint.py tests/test_tools.py tests/test_evaluator.py
112 passed in 0.17s

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run ruff check src/forgeagent/loop.py tests/test_loop_checkpoint.py
All checks passed!

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run ruff format --check src/forgeagent/loop.py tests/test_loop_checkpoint.py
2 files already formatted
```

## Files

- `src/forgeagent/loop.py`
- `tests/test_loop_checkpoint.py`

## Risk Signals

- Checkpoint 保存依赖 POSIX `os.replace` 和 best-effort 目录 fsync；在异常替换路径中已验证旧字节不变与临时文件清理，但真实文件系统的断电语义仍依赖底层平台。
- Store 在单进程内使用一把锁和 revision 防止丢失更新；多进程并发写入不在 Task 1 范围内，后续 runner/CLI 装配不得绕过 store。
- Checkpoint 文本限制了长度、控制字符和项目根目录边界，但耐久文本仍应按不可信任务数据处理，不能作为权限或执行配置来源。

## Independent review fix

### Verified findings

- Token usage may overshoot its configured budget in one completed provider call. Rejecting that snapshot would lose the evidence needed for the runner to stop at the next safe boundary, so checkpoint validation now permits the known cumulative value.
- The previous `lstat()` followed by `Path.open()` left a symlink swap window. Loading now uses `os.open(..., O_NOFOLLOW)`, validates the opened descriptor with `fstat()`, and fails closed when `O_NOFOLLOW` is unavailable.
- Persisted prompt-facing text previously rejected only ASCII controls. It now rejects Unicode categories `Cc`, `Cf`, `Cs`, `Zl`, and `Zp`, covering C0/C1 controls, bidirectional format characters, surrogates, and line/paragraph separators.
- Public reports previously omitted the fixed schema and accepted arbitrary stop-reason text. Checkpoint and report stop reasons now use the planned stable enumeration with status-specific invariants.

### RED

```text
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_loop_checkpoint.py -k 'overshoot or dangerous_unicode or status_inconsistent or swapped_after_lstat or report_is_safe_projection'
34 failed, 30 deselected in 0.73s
```

Failures included `tokens_used exceeds token_budget`, dangerous Unicode being accepted, the missing report schema, inconsistent/unknown stop reasons being accepted, and a swapped symlink loading the outside goal.

### GREEN

```text
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_loop_checkpoint.py -k 'overshoot or dangerous_unicode or status_inconsistent or swapped_after_lstat or report_is_safe_projection'
34 passed, 30 deselected in 0.10s

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_loop_checkpoint.py tests/test_tools.py tests/test_evaluator.py
151 passed in 0.18s

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run ruff check src/forgeagent/loop.py tests/test_loop_checkpoint.py
All checks passed!

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run ruff format --check src/forgeagent/loop.py tests/test_loop_checkpoint.py
2 files already formatted
```

### Remaining risk

- Cross-process resume locking remains explicitly deferred; revision checks prevent silent overwrite but cannot make external side effects exactly once.
- The descriptor-based no-follow guarantee depends on platform support; unsupported platforms reject checkpoint loads rather than following a potentially unsafe path.
