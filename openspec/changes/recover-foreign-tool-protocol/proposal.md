## Why

真实 REPL 中，部分模型会把执行意图输出为其他 coding agent 的文本工具格式，例如独立的 `{"cmd":"..."}` 或 `todo_write` + `Params:`。ForgeAgent 当前既不会执行这些内容，也不会把它们识别为协议错误，而是立即以 `answered_in_prose` 软完成，导致用户明确要求的编程和执行任务没有真正发生。

## What Changes

- 识别已观察到的外部 agent 工具文本形态，并将其作为可恢复的协议错误反馈给模型。
- 明确要求模型改用 ForgeAgent 的 `CodeBlockStart`/`CodeBlockEnd` + `Exec` ToolCall 协议继续同一 Task。
- 保持普通非空知识型 prose 的单轮 `answered_in_prose` 行为。
- 不执行未经过 ForgeAgent schema、sandbox、确认门和审计链校验的裸命令文本。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `completion-integrity`: 外部 agent 工具文本不属于可接受的直接 prose，必须进入有界协议恢复；普通 prose 仍直接软完成。

## Impact

- 影响 `src/forgeagent/protocol.py` 的文本解析与对应 parser/Step/Task 回归测试。
- 不改变 CLI 参数、公开数据 schema、工具注册表、sandbox 权限、确认策略、依赖或厂商接口。
