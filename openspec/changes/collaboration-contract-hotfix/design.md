## Context

`SubmitPlanTool` 当前只匹配 `AcceptanceItem.acceptance` 的 HOW 前缀。`CollaborationRunner._run_role()` 只在角色正常返回后发出一个字段不完整的 `collaboration.role` 事件；`resolve_collaboration_mode()` 的各入口没有发出 route audit。

## Goals / Non-Goals

**Goals:**

- 在计划冻结前对两个自然语言字段使用同一 WHAT-only 边界。
- 让路由和所有角色尝试在既有 audit sink 中可归因、可计费且最小披露。
- 保持异常类型、协作状态机和公共报告不变。

**Non-Goals:**

- 不新增分类模型、审计后端、公开 API 或持久化字段。
- 不记录 goal、计划/反馈正文、prompt、工具参数、文件内容、credential 或绝对路径。
- 不重构协作入口或模型 client。

## Decisions

1. HOW 检查复用现有 `_HOW_ONLY_RE`，同时检查 `behavior` 与 `acceptance`；拒绝消息保持通用，不回显原文。
2. 增加一个小型 route audit helper，由 CLI/REPL/HTTP 在最终模式确定后调用；Loop 在创建或恢复时直接发出同构事件，覆盖 single/Duo/Triad。事件只含 mode、reason、requested mode、override 布尔值与可用的 Loop 关联。
3. 角色事件拆为 `collaboration.role.start` 和 `collaboration.role.outcome`。model/tier 从冻结 state 读取；Planner/Generator tier 使用 `execution_tier` 参数，Evaluator 使用 state 中的 evaluator tier。
4. outcome 在 `finally` 语义下发出：成功时记录 rounds、normalized usage 和 `usage_available`；异常时记录稳定 `configuration_error` 或 `role_error`，usage 为零且 unavailable，不记录异常文本。

## Risks / Trade-offs

- [入口可能漏发 route] → CLI、REPL、HTTP 与 Loop create/resume 均以测试锁定，Loop 的 single/Duo/Triad 全部记录。
- [审计字段扩大泄漏面] → 只使用枚举、模型标识、tier、计数和 token 数；继续经过现有 audit sink 掩码/序列化边界。
