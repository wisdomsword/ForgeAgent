## MODIFIED Requirements

### Requirement: 非交互与测试输入保持兼容

系统必须（SHALL）只在默认 reader 且 stdin/stdout 均为交互式终端时启用增强输入和交互式启动呈现。显式注入的 `read_line` 和非 TTY 输入必须（MUST）保持原有 EOF、KeyboardInterrupt、空行、确认与 Survey 行为；同时不得输出 Logo、启动 banner、MCP 可选状态或交互式 goal prompt。管道任务仍可使用已经连接的 MCP 和既有任务结果渲染。

#### Scenario: 注入 reader 不创建终端会话
- **WHEN** 测试或嵌入方显式传入 `read_line`
- **THEN** REPL 只调用该 reader，且不访问增强终端输入对象或启动 Logo renderer

#### Scenario: 非 TTY 使用普通输入
- **WHEN** REPL 默认启动但 stdin 或输出不是 TTY
- **THEN** 系统使用普通输入路径，保持现有 EOF、KeyboardInterrupt、空行、确认与 Survey 语义，并不打印交互式启动或 goal prompt

#### Scenario: 管道只输入退出命令
- **WHEN** 用户执行 `printf 'quit\\n' | forgeagent ...` 且没有任务输入
- **THEN** 进程以 0 退出，stdout 和 stderr 均为空

#### Scenario: 管道提交任务
- **WHEN** 用户通过非 TTY 输入提交一个 goal
- **THEN** MCP 可继续为任务提供能力，但启动 banner、Logo、MCP optional 状态和交互 prompt 不出现在输出中，既有任务结果仍被输出
