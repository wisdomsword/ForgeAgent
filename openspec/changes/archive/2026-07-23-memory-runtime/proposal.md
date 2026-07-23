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
