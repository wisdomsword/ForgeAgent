# repl-interactive-input Specification

## Purpose
TBD - created by archiving change skills-runtime. Update Purpose after archive.
## Requirements
### Requirement: 交互式 REPL 动态展示斜杠指令
系统必须（SHALL）在真实交互式终端的 REPL 中，于用户输入 `/` 后立即展示可用斜杠指令，并在每输入或删除一个字符后按当前命令前缀更新候选。候选名称和说明必须（MUST）来自与 `/help` 相同的命令表。

#### Scenario: 裸斜杠显示全部指令
- **WHEN** 用户在空提示符输入 `/` 且尚未提交
- **THEN** 输入界面显示全部可用斜杠指令候选及其简要用途

#### Scenario: 前缀逐字符过滤
- **WHEN** 用户依次输入 `/m`、`/mo`、`/mod`
- **THEN** 候选集合在每次编辑后立即缩小为匹配当前前缀的指令

### Requirement: 用户可从候选中选择指令
系统必须（SHALL）允许用户用终端键盘在当前候选中移动并接受一个指令，接受后命令文本进入同一输入行，用户可继续补充参数或提交。

#### Scenario: 选择命令后继续输入参数
- **WHEN** 用户从 `/model` 候选中选择该命令
- **THEN** 输入行包含 `/model`，且用户仍可输入模型参数后提交

### Requirement: 上下方向键回放当前会话历史
系统必须（SHALL）记录当前 REPL 会话已提交的输入，并在没有活动候选选择时用上、下方向键向后或向前回放。历史默认不得（MUST NOT）跨进程持久化，以避免把任务文本或敏感参数写入额外文件。

#### Scenario: 回放上一条输入
- **WHEN** 用户已提交至少一条输入并在新提示符按上方向键
- **THEN** 输入行恢复上一条已提交文本供编辑或再次提交

#### Scenario: 下方向键返回较新输入
- **WHEN** 用户已向上回放历史后按下方向键
- **THEN** 输入行移动到较新的历史项或回到空输入

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
