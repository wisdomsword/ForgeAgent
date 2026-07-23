## Context

MemoryManager 已返回完整 `MemoryResult`，但 Task 仅调用 `apply()` 而不保存结果；CLI
因此无法纠正模型的口头声明。REPL 输入循环只捕获 EOFError，提示符处的
KeyboardInterrupt 直接冒泡到入口并打印 traceback。

## Goals / Non-Goals

**Goals:**

- 让调用者和 CLI 看见每个模型候选的真实 accepted/rejected/disabled 结果。
- 保持候选在 Task 完成后应用，不增加模型 round，不改变 solved/completed 判定。
- 让提示符处 Ctrl-C 与 EOF/quit 一样完成 MCP 清理后退出。

**Non-Goals:**

- 不要求模型在同一响应中预知准入结果。
- 不改变 HTTP 响应、准入规则、持久化格式或 audit schema。
- 不吞掉模型调用、工具调用或 MCP 清理期间的 KeyboardInterrupt。

## Decisions

1. 在 `TaskOutcome` 增加默认空列表 `memory_results`。这是对既有处理结果的向后兼容
   暴露；HTTP 继续使用自己的投影，不序列化该字段。
2. `Task.run()` 仅在 solved outcome 后收集 `apply()` 返回值，与当前写入时机一致。
3. `render_outcome()` 在模型正文和工具结果之后显示固定、无候选原文的 memory 状态行，
   使模型声明与运行时事实同时可见。
4. 只在 `read_line()` 边界捕获 KeyboardInterrupt；任务执行中的中断继续按既有控制流传播。

## Risks / Trade-offs

- [模型仍可能先口头声称已记住] → CLI 紧接着展示权威 runtime 结果，不增加第二次 LLM 调用。
- [TaskOutcome 字段增加] → 提供默认空列表，现有构造和调用保持兼容；HTTP schema 不变。
