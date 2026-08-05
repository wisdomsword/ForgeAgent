## ADDED Requirements

### Requirement: REPL 模型会话在进程内连续

ForgeAgent SHALL 在同一 REPL 进程内保留任务型输入及其安全可见结果，并将该 transcript 作为后续任务型输入的模型上下文。历史 SHALL 保持结构化消息与工具调用配对，MUST NOT 跨进程持久化。每条顶层输入 MUST 继续创建新的 Task；管理类 slash command MUST NOT 写入模型 transcript。

#### Scenario: 澄清答案继续原任务
- **WHEN** 首条输入提出任务，模型通过 Survey 或 prose 请求必要信息，用户在下一条 `forge>` 输入中提供答案
- **THEN** 下一 Task 的模型请求同时包含原任务、澄清请求和用户答案，而不是把答案作为无上下文的新目标

#### Scenario: 普通任务连续引用
- **WHEN** 用户完成一项普通或显式 Single 任务后提交依赖上一结果的新输入
- **THEN** 后续模型请求包含上一任务的用户输入、模型回复、工具调用与有界反馈

#### Scenario: 协作任务只保留公开结果
- **WHEN** Duo 或 Triad 任务完成并返回用户可见结果
- **THEN** REPL 将原始 goal 与最终安全可见投影加入会话，但不加入 planner、evaluator 或未公开候选的内部内容

#### Scenario: 管理命令不污染会话
- **WHEN** 用户在两个任务型输入之间执行 `/help`、`/model`、`/reload` 或其他管理命令
- **THEN** 命令执行其既有功能，但命令文本与管理输出不进入后续模型请求

### Requirement: 用户可显式重置模型会话

REPL command table SHALL 提供 `/new` 与 `/reset`。任一命令 SHALL 清空进程内模型 transcript 与暂存图片，同时 MUST 保留当前模型、sandbox tier、Memory、MCP、输入行历史和进程累计 usage。清空操作 MUST NOT 启动 Task 或调用 provider。

#### Scenario: new 清空历史
- **WHEN** 用户在已有模型会话后提交 `/new`
- **THEN** 下一任务只使用新的 system prompt 和新输入，不包含重置前的 transcript

#### Scenario: reset 清空暂存图片
- **WHEN** 用户暂存图片并提交 `/reset`
- **THEN** transcript 与暂存图片均被清空，当前模型、sandbox、Memory、MCP 和累计 usage 保持不变

#### Scenario: 重置不调用模型
- **WHEN** 用户提交 `/new` 或 `/reset`
- **THEN** REPL 输出有界确认并返回提示符，不创建 Task、不调用 provider
