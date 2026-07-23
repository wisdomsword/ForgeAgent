---
change: memory-result-feedback
status: passed
---

# Memory Result Feedback Hotfix 验证报告

## 根因与修复

- `Task.run()` 调用 `MemoryManager.apply()` 后丢弃返回值，导致 CLI 无法展示模型候选的
  disabled/rejected 等权威结果；现由 `TaskOutcome.memory_results` 返回并安全渲染。
- REPL 输入循环只捕获 EOFError；现仅在提示符 `read_line()` 边界捕获 KeyboardInterrupt，
  保持任务执行和资源清理期间的控制异常语义不变。

## 证据

- TDD RED：缺少 `memory_results`、CLI 缺少 `memory disabled`、KeyboardInterrupt 冒泡。
- 定向 GREEN：`3 passed`；相关 Task/CLI/HTTP 回归：`67 passed`。
- 全量：`1378 passed, 11 skipped in 99.90s`。
- `ruff check .`、`openspec validate memory-result-feedback --strict`、`git diff --check` 通过。
- `uv build` 成功生成 sdist 与 wheel。

## 评审

- 结果输出仅包含 status/scope/key/reason，不包含候选 content。
- HTTP 继续使用既有 TaskRecord 投影，响应 schema 不变。
- 不增加 LLM round，不改变 Task completed/solved 语义。
