## Why

当前 REPL 将每条 `forge>` 输入作为完全独立的 Task，后续输入只收到 system prompt 和当前文本。用户对上一轮澄清问题作答时，原始目标已经丢失，导致 Agent 重复询问、降级执行或把补充参数当成新任务。

## What Changes

- REPL 在进程内保留任务型输入、模型回复、工具调用和有界工具反馈，并把它们作为后续任务的会话上下文。
- 新增 `/new` 与 `/reset` 命令，清空模型会话历史和暂存图片，同时保留模型、sandbox、Memory、MCP 与进程级 usage 统计。
- 调整 sliding-window 的轮次校验和淘汰规则，使跨顶层输入的会话仍按完整交互单元保留或移除。
- 每条顶层输入仍创建新的 Task、backend、Runtime、task ID 和文件系统授权状态；历史文本不继承执行权限。
- 普通任务及显式 Single/Duo/Triad 任务的安全可见结果进入历史；管理类 slash command 不进入模型上下文。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `repl-interactive-input`: REPL 从输入行回放扩展为进程内模型会话连续性，并增加显式重置命令。
- `runtime-context-management`: 请求视图支持跨顶层输入的完整会话轮次，替换“REPL goal 消息历史互不继承”的旧要求。
- `task-filesystem-authority`: 明确会话历史不得继承上一 Task 的文件系统授权或执行状态。

## Impact

- 主要影响 `src/forgeagent/_cli_repl.py`、`src/forgeagent/cli.py`、`src/forgeagent/task.py`、`src/forgeagent/step.py`、`src/forgeagent/context.py` 及对应 CLI/Task/context 测试。
- 不新增依赖、不持久化会话、不改变单次 `run`、HTTP、Loop 的公开契约，也不放宽 sandbox 或工具审批边界。
