# runtime-memory Specification

## Purpose
TBD - created by archiving change memory-runtime. Update Purpose after archive.
## Requirements
### Requirement: 记忆候选提取协议
系统 SHALL 支持从模型响应中的 `<!-- Memory: {...} -->` 标记提取结构化候选，并 SHALL 支持 CLI `/remember` 将用户输入转换为同一候选类型。候选 MUST 包含非空 `content`、稳定 `key`、`scope`（`session` 或 `project`）和 `kind`（`fact`、`preference`、`decision` 或 `procedure`）；标记 SHALL 从展示给用户的正文中移除，格式错误 SHALL 生成可回馈的解析错误而不是写盘。

#### Scenario: 提取合法模型候选
- **WHEN** 模型响应包含合法的 Memory JSON 标记
- **THEN** 解析结果包含一个候选，且正文不再包含该标记

#### Scenario: 用户显式提交候选
- **WHEN** 用户在 REPL 输入 `/remember project preferred-editor=vim`
- **THEN** 运行时创建项目级事实候选并执行与模型候选相同的准入和冲突流程

#### Scenario: 非法标记不写入
- **WHEN** Memory 标记 JSON 缺少 key、scope 或 content，或字段类型不正确
- **THEN** 解析结果包含结构化错误，MEMORY.md 与会话状态均不发生变化

### Requirement: 确定性准入与程序性分流
系统 SHALL 只准入陈述性事实、用户偏好和已确认决策；`kind=procedure` 的候选 MUST 被拒绝并反馈“请沉淀为 Skill”。候选内容 MUST 经过长度、控制字符、敏感环境值和明显提示注入指令检查；任一检查失败 MUST 拒绝候选。系统 MUST NOT 使用向量相似度、置信度模型或额外 LLM 调用决定准入。Task MUST 暴露每个模型候选的结构化准入结果，CLI SHALL 在任务输出中展示该权威结果且不得回显候选原文。

#### Scenario: 陈述性事实准入
- **WHEN** 候选 kind 为 fact、内容通过边界检查且 key 有效
- **THEN** 候选进入目标作用域并生成 accepted 审计事件

#### Scenario: 程序性记忆拒绝
- **WHEN** 候选描述“每次先运行某命令再修改文件”等做事步骤且 kind 为 procedure
- **THEN** 候选不进入任何作用域，并返回应沉淀为 Skill 的结构化拒绝原因

#### Scenario: 提示注入候选拒绝
- **WHEN** 候选内容包含要求忽略系统协议、泄露 secret 或执行越权动作的指令
- **THEN** 候选被拒绝且拒绝反馈不回显敏感原文

#### Scenario: 禁用记忆时纠正模型声明
- **WHEN** `--no-memory` 模式下模型响应包含合法 Memory 候选并声称已记住
- **THEN** Task 返回 disabled 结果，CLI 展示 `memory disabled`，且 session 与 project 存储不变

### Requirement: 会话与项目两级作用域
系统 SHALL 维护两个互不混淆的作用域：session 记忆仅在当前 REPL 进程内跨 Task 生效且不得落盘，project 记忆写入当前 `allowed_root/.forgeagent/MEMORY.md` 并在后续任务的身份组合中整体注入。HTTP/headless 每个任务只加载项目级记忆，不得共享其他任务的会话级状态。`--no-memory` MUST 同时阻止两级记忆的加载、注入和候选写入。

#### Scenario: 会话记忆跨任务可见
- **WHEN** 一个 REPL Task 接受 session 候选，随后启动第二个 Task
- **THEN** 第二个 Task 的 system prompt 包含该候选，且磁盘 MEMORY.md 不增加内容

#### Scenario: 项目记忆跨进程可见
- **WHEN** 一个 Task 接受 project 候选并结束，新的进程在同一 allowed_root 启动
- **THEN** 新进程加载 MEMORY.md 中的候选并将其注入 system prompt

#### Scenario: HTTP 不共享会话记忆
- **WHEN** 两个 HTTP 任务先后运行且第一个任务产生 session 候选
- **THEN** 第二个任务看不到该 session 候选，只能看到已存在的 project 记忆

#### Scenario: no-memory 禁用
- **WHEN** CLI 以 `--no-memory` 启动或 REPL reload 后记忆被禁用
- **THEN** 两级记忆均不进入 prompt，且任何候选都不会改变会话或项目存储

### Requirement: 项目记忆原子持久化与冲突替换
项目级记忆 MUST 以稳定的 Markdown 条目格式写入 MEMORY.md，并 MUST 通过同目录临时文件加 `os.replace` 原子替换；写入失败 MUST 保留旧文件并返回结构化错误。相同 key 的新候选 SHALL 替换旧条目（后写入者胜），不同 key SHALL 追加；替换和拒绝都 MUST 可由审计记录追踪。加载时畸形条目 MUST 被忽略并输出脱敏诊断，不得执行其内容。

#### Scenario: 相同 key 冲突替换
- **WHEN** 已有 `preferred-editor=vim` 且新候选写入同一 key 为 `nvim`
- **THEN** MEMORY.md 只保留 nvim 条目，并记录 replaced 事件

#### Scenario: 原子写入失败
- **WHEN** 临时文件创建或替换失败
- **THEN** 旧 MEMORY.md 保持字节不变，任务继续运行并返回 persistence_error

#### Scenario: 畸形条目隔离
- **WHEN** MEMORY.md 包含不符合受控条目格式的 Markdown 或注入文本
- **THEN** 该条目不注入模型上下文，其余合法条目仍可加载

### Requirement: 用户可见的查看与纠正
REPL SHALL 提供 `/memory` 查看当前有效 session/project 条目（内容经过既有 secret 掩码且限制总量），并 SHALL 允许用户通过直接编辑项目 MEMORY.md 纠正事实；下一次任务或 `/reload` 必须读取纠正后的文件。查看输出 MUST 标明作用域和 key，但不得展示内部审计路径或 secret。

#### Scenario: 查看记忆
- **WHEN** 用户输入 `/memory`
- **THEN** CLI 分别列出 session 与 project 条目，并对敏感值显示掩码

#### Scenario: 手工纠正后 reload
- **WHEN** 用户编辑 MEMORY.md 的条目并输入 `/reload`
- **THEN** 后续任务使用纠正后的内容，旧 session 状态不被静默转换为 project 条目

### Requirement: 记忆生命周期审计与最小披露
系统 SHALL 在核心层为 accepted、rejected、replaced、persistence_error 和 disabled 记忆操作写入既有 JSONL 审计 sink；事件 MUST 包含 task correlation、scope、kind、key 的脱敏摘要和结果状态，但 MUST NOT 包含候选原文、完整 MEMORY.md、token、secret 或宿主绝对路径。审计 sink 不可用时 SHALL 遵循既有 audit-degraded 语义，不得阻止无关任务完成。

#### Scenario: 准入审计
- **WHEN** 项目候选成功写入
- **THEN** 产生一个 memory.accepted 事件，包含 scope、kind、key 和 task id，不包含 content

#### Scenario: 拒绝审计
- **WHEN** 程序性或注入候选被拒绝
- **THEN** 产生一个 memory.rejected 事件，reason 可诊断但不泄露原文

#### Scenario: 审计降级
- **WHEN** 记忆审计写入失败
- **THEN** 任务仍按既有 fail-open 规则继续，且系统标记 audit_degraded 而不虚报已持久化

### Requirement: 可执行回归验证
系统 MUST 提供准入规则表驱动测试、协议解析测试、跨 Task mock replay、project 持久化重启测试、`/memory`/`--no-memory` CLI 测试和记忆投毒回归。新增 golden 候选 SHALL 维持既有类别配比，且离线 runner MUST 能在无 API key 环境验证记忆命中与拒绝场景。

#### Scenario: 跨任务记忆回放
- **WHEN** mock replay 的第一个 Task 写入事实，第二个 Task 请求该事实并仅提供含记忆即可完成的响应
- **THEN** 第二个 Task 的请求消息包含第一任务写入的记忆且 runner 断言通过

#### Scenario: 投毒回归
- **WHEN** mock replay 试图写入忽略协议或泄露环境值的候选
- **THEN** 候选被拒绝、后续 Task 的 prompt 不包含该内容且测试退出码为零

