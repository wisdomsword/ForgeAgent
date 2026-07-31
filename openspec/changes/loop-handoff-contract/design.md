## Context

`LoopCheckpoint` 已经是冻结目标、预算、协作路由和累计计数的宿主快照，但 `handoff: str` 与 `CheckpointArgs.handoff: str` 仍由模型自由填写。`LoopRunner._render_suffix()` 会把这些字段送入下一轮提示，故 handoff 必须被视为不可信候选，而不是控制面输入。当前仓库还要求旧 checkpoint 使用 `schema` 键可加载，并且外部动作收据在未知状态时禁止静默重放。

## Goals / Non-Goals

**Goals:**

- 使用冻结的 `LoopHandoff` 结构保存有界完成项、未解问题和摘要。
- 使用独立的候选模型承接模型输出，只允许更新 handoff 内容字段；宿主保留目标、预算、权限、协作冻结状态、终态和恢复策略。
- 在加载时兼容旧字符串 handoff；新保存内容不再依赖自由字符串。
- 为缺失/失败提交提供有限恢复提示，且恢复只重新请求提交，不重放工具或外部动作。

**Non-Goals:**

- 不引入通用状态机、事件溯源、调度器或新的持久化后端。
- 不改变 LoopStopReason、Task/Collaboration 终态分类、公开 LoopReport 字段或外部收据协议。
- 不把 Loop handoff 与 Collaboration `HandoffPacket` 合并；不引入 LLM 自动摘要或拆解器。

## Decisions

1. **双模型边界。** `LoopHandoff` 是宿主持久化模型，使用冻结、禁止额外字段的 `completed_items`、`open_questions`、`summary` 字段；`LoopHandoffCandidate`/`CheckpointArgs` 只表达模型可提交的三项内容。CheckpointTool 从候选更新 handoff，其他 checkpoint 字段直接沿用当前快照。相比让模型提交完整 checkpoint，这能在 Pydantic 校验前后都阻断越权字段。
2. **兼容迁移。** `LoopCheckpoint` 的 before validator 接受旧字符串 `handoff`，转换为 `LoopHandoff(summary=<旧字符串>)`；缺失 handoff 使用空结构。读取旧文件不会原地改写，下一次正常保存才以结构化对象序列化。这样旧文件可恢复，且迁移不扩大读取权限。
3. **恢复边界。** required completion submission 的恢复提示由宿主计数并设置固定上限；达到上限后失败。恢复消息只要求模型重新提交当前状态，不调用历史 ToolCall、不复制外部动作、不改变 receipt 状态。若已有未知/待处理收据，Loop 在现有 `external_action_pending` 门禁处停止。
4. **不可回退的进度。** `completed_items` 仍只能追加；`open_questions` 与 `summary` 可替换但受相同安全文本和大小限制。模型不能清除已完成项，也不能通过 handoff 候选改变 goal、budgets、permissions、collaboration_mode、plan_digest、status、stop_reason 或 attention。
5. **提示投影。** `_render_suffix()` 只注入结构化 handoff 的 JSON 投影，并显式标记为不可信 Loop 状态；公开报告继续只输出计数，不泄漏 handoff 正文。

## Risks / Trade-offs

- [旧 handoff 摘要可能包含历史模型文本] → 迁移复用既有 `safe_text`/secret masking 边界并限制长度；不把它当作指令执行。
- [一次恢复不足以纠正暂时性提交格式错误] → 允许有限次数的同一提交恢复提示，但明确禁止动作重放；超过上限转为失败，避免无限循环。
- [结构化 handoff 改变 checkpoint JSON 形状] → 仅对新保存文件改变 handoff 值形状，保留 `schema`、其他键和旧字符串读取兼容；增加 round-trip 与 legacy fixture 测试。

## Migration Plan

1. 先添加失败测试和 delta spec，覆盖结构、兼容加载、越权字段和恢复边界。
2. 实现模型与 CheckpointTool，再接入 Runner 注入和 Step 有界恢复。
3. 运行 focused/full pytest、Ruff、format、OpenSpec strict 和 `uv build`。
4. 不执行发布、tag 或 push；旧 checkpoint 不主动批量改写。

## Open Questions

- 无。字段范围、兼容方式和恢复上限均在本 change 中固定，并由测试锁定。
