## Context

Duo 没有 Planner，必须由宿主生成冻结计划。当前实现保留一个 `goal` 计划项，但 behavior/acceptance 是不可观察的同义反复。大量持久化、恢复和评估测试依赖稳定 item ID，因此本 change 应改进内容契约而非扩大计划形状。

## Goals / Non-Goals

**Goals：**

- 使用纯确定性、无依赖逻辑把 goal 归入产物、验证或文本结果三类。
- 每类返回一个稳定 `goal` item，验收文本明确 Evaluator 可观察的证据类型。
- 计划正文经过既有 AcceptanceItem 安全校验，不复制原始 goal、绝对路径或 secret。

**Non-Goals：**

- 不使用 LLM 自动拆解 goal。
- 不把一个 goal 拆为多个动态计划项。
- 不改变 Triad Planner、Evaluator 工具权限或 EvaluationItem 结构。

## Decisions

1. **保留单计划项和 `goal` ID。** 这维持旧 snapshot、plan digest/恢复不变量和既有 SubmitEvaluation 兼容。改成三个固定项会让旧 Evaluator 结果缺项，并制造不必要迁移。
2. **使用有限关键词分类而非通用自然语言解析。** 文件/产物信号优先，其次验证/命令信号，最后回退文本/分析结果。规则小、可测试、失败时仍返回可观察的文本结果契约。
3. **模板不嵌入 goal 正文。** Goal 只决定模板类别；behavior/acceptance 使用固定 English-first 文本，避免路径、secret 和 prompt 正文进入计划或报告。
4. **验收要求证据而非主观判断。** 产物类要求相对位置与内容可检查，验证类要求注册检查或有界命令结果，文本类要求可引用的响应片段与支撑证据。

## Risks / Trade-offs

- [风险] 关键词不能覆盖所有自然语言表达。→ 未命中时回退到文本/分析模板，仍比循环论证可观察；不升级为 LLM 拆解。
- [风险] 同时包含文件和测试的 goal 只选一类。→ 产物优先，Evaluator 仍可观察最终交付物；复杂多条件任务应使用 Triad Planner。
- [风险] 计划文本变化会改变新 Duo 状态的 plan digest。→ 旧 snapshot 按持久化计划继续加载；只有新建 Duo 使用新 digest。

## Migration Plan

旧 snapshot 不重算 plan。新建 Duo 使用新模板；回滚只需恢复旧 `_duo_plan` 文本，无磁盘迁移。

## Open Questions

无。M39 已限定不新增依赖和 LLM 拆解器。
