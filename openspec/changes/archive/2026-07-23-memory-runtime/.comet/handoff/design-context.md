# Comet Design Handoff

- Change: memory-runtime
- Phase: design
- Mode: compact
- Context hash: 06db89ffb504b8f314fc609c33b27ec135570a648c49c4ddef9db0599110389e

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/memory-runtime/proposal.md

- Source: openspec/changes/memory-runtime/proposal.md
- Lines: 1-29
- SHA256: fbeadd91bc9c448416bafbb23c1fcecfc1c52f999045eaa1e81f5b9c5abf84aa

```md
## Why

M15 只让 ForgeAgent 加载和手工编辑项目级 `MEMORY.md`，尚未提供从任务经验到可复用记忆的受控生命周期。M18 需要在不引入检索系统或额外模型调用的前提下，让已确认的用户偏好、项目约定和决策跨任务可靠复用，同时阻止程序性方法和不可信任务内容污染后续提示词。

## What Changes

- 增加显式记忆候选协议：模型可在任务收尾声明候选，用户可通过 `/remember` 直接提交纠正或事实。
- 增加确定性准入、规范化去重和冲突替换；只允许陈述性事实，程序性方法拒绝并提示应沉淀为后续 Skill。
- 增加会话级与项目级两种作用域：会话级只在当前 REPL 进程跨任务生效，项目级原子写入 `.forgeagent/MEMORY.md`。
- 增加 `/memory` 查看与管理入口、`--no-memory` 临时停用开关，并让 reload 保持事务化。
- 记录不含候选原文的记忆准入、拒绝和替换审计事件，补充记忆投毒威胁模型。
- 增加表驱动准入测试、跨任务 mock replay 和离线 golden 覆盖。

## Capabilities

### New Capabilities

- `runtime-memory`: 记忆候选、准入、两级作用域、冲突替换、用户控制和安全边界。

### Modified Capabilities

无。M18 的新增记忆生命周期契约独立于 M15 身份加载和 M16 审计字段的既有要求；归档时由 `runtime-memory` 规定其新增行为。

## Impact

- 主要影响 `protocol.py`、`identity.py`、`task.py`、`cli.py` 和新增的轻量 memory 核心模块。
- 更新系统协议提示词、配置/CLI 文档、威胁模型和相关测试；不增加第三方依赖。
- 不改变 HTTP endpoint 或响应 schema；HTTP 任务默认只消费项目级记忆，不共享进程级会话记忆。
- 不实现向量检索、RAG、语义摘要、置信度、时间衰减、团队作用域或程序性 Skill 写入。

```

## openspec/changes/memory-runtime/design.md

- Source: openspec/changes/memory-runtime/design.md
- Lines: 1-54
- SHA256: 4ff43326940c983f99bc8c531e721bee302b5509e8b694e2ca1c5d2922165a6b

```md
## Context

M15 已有 `IdentitySnapshot`、项目级 `.forgeagent/MEMORY.md`、信任确认和组合式 system prompt；M17 在每次 provider 调用前提供非破坏的有界 request view。当前缺口是：任务输出没有受控的记忆候选通道，REPL 也没有跨 Task 的会话状态。M18 必须在现有文本协议、Task/Step 核心层、CLI 与审计层之间补齐生命周期，不增加外部依赖或检索服务。

## Goals / Non-Goals

**Goals:**

- 用显式 `Memory` 标记和 `/remember` 统一产生候选。
- 以纯 Python 确定性规则完成分类、边界检查、去重、冲突替换和安全拒绝。
- 将 session/project 两级记忆合成到已有 identity snapshot；支持查看、停用、reload 和跨任务 replay。
- 复用既有掩码、原子文件写入和 JSONL audit sink。

**Non-Goals:**

- 向量检索、RAG、query 激活、摘要、时间衰减、置信度或团队/用户级作用域。
- 额外的 LLM 提取调用、数据库、后台线程、HTTP schema 变化或 Skill 文件写入。

## Decisions

### 1. 显式候选协议，解析阶段提取

在 `protocol.py` 增加 `MemoryCandidate` Pydantic 模型和 `<!-- Memory: {...} -->` 标记。解析器将标记从 body 移除并把坏标记转为 `ParseError`；Step/Task 只消费结构化结果。CLI `/remember <scope> <key>=<content>` 直接构造同一模型，避免为显式用户纠正另建路径。候选声明不改变完成状态，也不触发第二次模型请求。

### 2. 单一 MemoryManager，存储和策略分开但不引入层级工厂

新增 `memory.py`，包含条目规范化、确定性准入、Markdown 编解码、session 字典和 project 原子写入。`MemoryManager` 接受 `allowed_root`、可选 audit sink 与 `enabled`，以显式方法 `load()`、`apply()`、`render()` 和 `disable()` 提供最小 API。project 文件使用稳定的 `- key: value` 格式并以同目录临时文件 + `os.replace` 更新；相同 key 后写入者胜。

### 3. 安全准入采用可审计规则表

只接受 `fact`、`preference`、`decision`；`procedure` 永久拒绝并给出 Skill 分流提示。所有内容先做 UTF-8/控制字符/长度/既有 secret mask 检查，再拒绝有限的注入指令模式（忽略协议、泄露 secret、越权执行）。不做语义相似度或模型置信度，避免不可重复和隐式信任。

### 4. 记忆注入复用 IdentitySnapshot，作用域由入口持有

`Task` 接收可选的已经渲染的 memory text 或 memory manager snapshot；显式 `system_prompt` 仍完全优先。CLI 创建一个 REPL 级 `MemoryManager`，每次任务前把 session 与 project 的安全渲染结果合并进 identity；Task 结束后将各 round 的候选交给 manager。HTTP 每个任务创建 project-only manager，不共享进程 session。`--no-memory` 在入口关闭 manager，不改变 `--no-identity` 的既有语义。

### 5. 审计在核心层记录摘要

MemoryManager 用既有 `AuditEvent`/`AuditSink` 写 `memory.accepted`、`memory.rejected`、`memory.replaced`、`memory.persistence_error` 和 `memory.disabled`。参数只含 scope/kind/key/reason 的掩码摘要；正文、完整 MEMORY.md 和绝对路径永不写入。审计失败沿用现有降级，不阻断记忆或任务本身。

## Risks / Trade-offs

- [候选内容仍可能是错误事实] -> 后写入者胜、`/memory` 可见、文件可编辑、`--no-memory` 可停用；不引入无法解释的置信度模型。
- [规则式注入检测有漏报/误报] -> 只把它作为准入门，不把 MEMORY 当安全边界；协议/工具确认和 sandbox 继续负责执行安全。
- [Markdown 手工编辑可能出现未知格式] -> 解析只接受受控条目，畸形条目跳过并给出脱敏诊断。
- [session 状态跨任务带来长会话增长] -> 条目和渲染总量有硬上限，并复用 M17 的 context budget；HTTP 不共享 session。

## Migration Plan

无需迁移脚本。现有缺失或普通 Markdown 的 MEMORY.md 按“无合法条目”加载，旧身份段仍可通过 `--no-identity` 诊断。首次接受 project 记忆时才按受控格式原子创建/替换文件；失败保留原文件。回滚代码后，旧 M15 loader 仍可读取该文件中的可读文本。

## Open Questions

无。触发方式、作用域、程序性分流、冲突语义和停用语义已按本设计固定，后续实现不得扩大到 M19/M20 能力。

```

## openspec/changes/memory-runtime/tasks.md

- Source: openspec/changes/memory-runtime/tasks.md
- Lines: 1-30
- SHA256: 08f19ecddd6a5230d05c45f6f4302537f84803cac2e52f0a641e381ff423e62e

```md
## 1. 协议与确定性核心

- [ ] 1.1 在 `src/forgeagent/protocol.py` 增加 `MemoryCandidate`、Memory 标记解析、正文剥离和结构化解析错误。
- [ ] 1.2 新增 `src/forgeagent/memory.py`，实现有界候选校验、程序性/注入拒绝、稳定 Markdown 编解码、会话状态、项目原子替换和掩码渲染。
- [ ] 1.3 增加候选 schema、准入矩阵、畸形条目、secret/注入拒绝、去重、冲突替换和写入失败保留的单元测试。

## 2. Task、身份与审计集成

- [ ] 2.1 将 memory snapshot 注入 Task system prompt 组合，但不削弱显式 `system_prompt` 或 M15 身份信任边界。
- [ ] 2.2 收集已完成 round 的候选并经配置的 MemoryManager 应用；暴露处理结果但不改变 Task 完成语义。
- [ ] 2.3 通过现有核心 audit sink 写入最小披露的记忆生命周期事件，并补充审计断言。
- [ ] 2.4 增加跨任务 mock replay 与项目重启测试，证明已接受记忆只在目标作用域可见，拒绝的投毒内容不会出现在后续 prompt。

## 3. CLI 与 headless 控制

- [ ] 3.1 接入由 REPL 持有的 session/project MemoryManager，实现 `/memory` 查看、`/remember` 提交和 `/reload` 刷新。
- [ ] 3.2 将 `--no-memory` 接入单次运行与 REPL 参数/配置链路，确保停用 manager 既不注入也不持久化候选。
- [ ] 3.3 保持 HTTP/headless 仅项目级语义，并增加无会话泄漏与停用记忆的请求路径回归测试。

## 4. 文档与验证资产

- [ ] 4.1 更新协议、CLI/配置、身份和威胁模型文档，记录记忆投毒边界与 Skill 分流。
- [ ] 4.2 增加记忆命中/未命中/拒绝 golden 候选并维持既有类别比例；在 runner 断言完成前保持候选与已验证 manifest 分离。
- [ ] 4.3 执行定向测试、全量 pytest、ruff、golden runner、OpenSpec strict 校验和 diff 检查；在 verify 前修复所有失败。

## 5. 评审与发布

- [ ] 5.1 评审范围、prompt 顺序、原子性、掩码和多入口一致性；修复发现并重跑受影响测试。
- [ ] 5.2 以精确命令证据和残余风险产出 M18 验证报告与里程碑记录。
- [ ] 5.3 执行 Comet verify，将 change 归档并同步主规格，合并分支到 `main`，保留无关用户工作区改动。

```

## openspec/changes/memory-runtime/specs/runtime-memory/spec.md

- Source: openspec/changes/memory-runtime/specs/runtime-memory/spec.md
- Lines: 1-102
- SHA256: a4704df978aa73ebdfd62edcf610ca6a9e6a1844d1f839327aa1954787bb143b

[TRUNCATED]

```md
## ADDED Requirements

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
系统 SHALL 只准入陈述性事实、用户偏好和已确认决策；`kind=procedure` 的候选 MUST 被拒绝并反馈“请沉淀为 Skill”。候选内容 MUST 经过长度、控制字符、敏感环境值和明显提示注入指令检查；任一检查失败 MUST 拒绝候选。系统 MUST NOT 使用向量相似度、置信度模型或额外 LLM 调用决定准入。

#### Scenario: 陈述性事实准入
- **WHEN** 候选 kind 为 fact、内容通过边界检查且 key 有效
- **THEN** 候选进入目标作用域并生成 accepted 审计事件

#### Scenario: 程序性记忆拒绝
- **WHEN** 候选描述“每次先运行某命令再修改文件”等做事步骤且 kind 为 procedure
- **THEN** 候选不进入任何作用域，并返回应沉淀为 Skill 的结构化拒绝原因

#### Scenario: 提示注入候选拒绝
- **WHEN** 候选内容包含要求忽略系统协议、泄露 secret 或执行越权动作的指令
- **THEN** 候选被拒绝且拒绝反馈不回显敏感原文

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


```

Full source: openspec/changes/memory-runtime/specs/runtime-memory/spec.md
