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
