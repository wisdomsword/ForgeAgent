## Why

ForgeAgent 当前在所有 REPL 启动路径无条件打印交互 banner、提示符和逐项 MCP 状态，MCP SDK 又因未传 `errlog` 而把每个 stdio 子进程的 stderr 直接写入主进程终端。这使 Docker daemon 错误、server chatter 和 `ExceptionGroup` 等内部信息看起来像 ForgeAgent 自身的默认依赖或故障，并污染管道输出。

本变更要让交互式启动具有清晰的产品身份与就绪反馈，同时让非交互输出保持安静、可组合，并在不削弱现有 MCP required/optional、secret masking、确认门或 sandbox 语义的前提下提供可操作的诊断。

## What Changes

- 为真实交互式 REPL 增加纯 ASCII ForgeAgent Logo：初始化期间使用 Rich 做低频七色动画，就绪后定格；确认提示期间暂停；窄终端、`NO_COLOR` 和无颜色终端确定性降级。
- 用一条紧凑状态区替代当前 banner、帮助和逐项 MCP 启动输出，展示模型、实际 sandbox、项目路径，以及按启动快照计算的 MCP `available/enabled` 摘要。
- 新增 per-server、有界、内存内的 MCP stdio `errlog` 接管。成功服务的 chatter 不再进入宿主 stderr；失败服务只暴露经过 secret masking 和有限分类的友好诊断，未知原因不得猜测。
- 增强现有 `/mcp` 状态输出，按服务展示状态、工具数，以及失败时的 Reason / Impact / Action；Docker 只在相应配置服务的诊断中出现，并明确不是默认 sandbox。
- 修复既有非 TTY 行为：当 stdin 或 stdout 不是 TTY 时，不打印 Logo、启动 banner、交互提示符或可选 MCP 状态；管道任务仍可使用已连接的 MCP，但输出只保留既有任务结果；仅输入 `quit` 时 stdout/stderr 均为空且退出码为 0。
- required MCP 失败继续在任务执行前整体阻断并完成有界清理；错误写入 stderr、退出非零，且不得泄漏原始子进程 stderr 或内部异常文本。
- 不新增 `/doctor`、`--no-banner`、第三方动画依赖、持久 stderr 日志、MCP 权限能力或 sandbox 配置。

## Capabilities

### New Capabilities

- `repl-startup-information`: 交互式 Logo、启动状态摘要、终端能力降级和安静的非交互启动输出。

### Modified Capabilities

- `repl-interactive-input`: 将“非 TTY 保持原有输出”改为明确的无 banner、无 prompt、结果导向输出契约，同时保留 EOF、`KeyboardInterrupt`、空行、确认与 Survey 语义。
- `mcp-resilience`: 增加全新的 per-server `errlog` 接管、有界诊断、摘要计数和友好 `/mcp` 展示要求，同时保持 optional 降级与 required 阻断语义。

## Impact

- 主要代码：`src/forgeagent/cli.py`、`src/forgeagent/mcp_manager.py`。
- 主要测试：`tests/test_cli.py`、`tests/test_mcp_manager.py`，以及必要的 CLI 黑盒/管道回归。
- 文档：README、MCP/CLI 使用说明和必要的安全边界说明。
- 依赖：复用现有 Rich、prompt-toolkit 和 MCP SDK，不新增运行时依赖。
- 兼容性：交互式 REPL 启动呈现会改变；`run`、`serve`、MCP 工具调用、确认门和任务结果结构不变。非 TTY REPL 从带交互噪声改为安静输出，是有意修复而非兼容承诺。
- 工作区隔离：以下既存未提交路径不属于本变更，后续实现、diff review 和提交必须排除：`ACTION_PLAN.md`、`scripts/m16-filewrite-allowlist-blackbox.sh`、`.agent/`、`.agents/`、`.claude/commands/`、`.claude/rules/`、`.claude/skills/`、`.codex/`、`.superpowers/brainstorm/`、`skills-lock.json`、`work/`、`何为Harness.html`。
