---
comet_change: loop-handoff-contract
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-31-loop-handoff-contract
status: final
---

# M40 Loop Handoff Contract 设计

## 目标与边界

M40 只收敛 Loop checkpoint 的 handoff 所有权和提交恢复边界。Loop 的目标、预算、权限、协作模式/计划摘要、attention、终态和收据恢复语义均由宿主冻结；模型只能提交经过校验的进度候选。旧 checkpoint 必须可加载，但不主动批量重写。M40 不修改 LoopReport 公共字段、不引入新依赖、不改变外部动作收据协议，也不执行 PyPI、tag、push 或发布自动化。

## 数据模型

`LoopHandoff` 使用 Pydantic frozen/extra-forbid 模型，字段为：

- `completed_items: tuple[str, ...]`：去重、有界、只增进度。
- `open_questions: tuple[str, ...]`：去重、有界，可由当前候选替换。
- `summary: str`：有界安全摘要，不作为指令执行。

`LoopCheckpoint.handoff` 是唯一持久化 handoff 事实源。旧 checkpoint 的顶层 `completed_items`、`open_questions` 和字符串 `handoff` 在 `mode="before"` validator 中合并为新结构；若新结构与旧顶层字段同时存在且冲突，拒绝加载而不是猜测。`LoopCheckpoint.completed_items` 和 `.open_questions` 提供只读属性，减少对现有 Runner/Report 代码的行为扰动。新 JSON 只写嵌套 handoff，公开 `schema` 别名继续使用 `schema`。

`CheckpointArgs` 是独立的候选模型，仅有 `completed_items`、`open_questions`、`summary`。为读取历史调用方，输入 validator 接受 `handoff` 作为 `summary` 的 deprecated validation alias，但 JSON schema 与模型提示只暴露 `summary`。任何额外控制面字段都因 `extra="forbid"` 被拒绝。

## 提交与 CAS

`CheckpointTool.run()` 重新校验候选，检查既有完成项是候选的子集，再构造新的 `LoopHandoff` 并通过现有 `LoopCheckpointStore.save(expected_revision=...)` 原子提交。工具成功消息只返回 revision 和计数，不回显 handoff 文本。保存失败保持既有结构化失败，不改变内存快照。

## Resume 投影

`LoopRunner._render_suffix()` 序列化 `checkpoint.handoff.model_dump(mode="json")`，与 `last_failure`、只读属性计数一起注入，并明确写入 `UNTRUSTED LOOP STATE`。该 JSON 是给模型参考的事实候选，不得被解释为 goal、权限、预算、恢复命令或 ToolCall；目标仍由 `task.run(self._checkpoint.goal)` 单独传入。

## 有界提交恢复

Step 将 required completion 的恢复状态从集合改为每个工具的计数。普通 `Task`/Collaboration 保持既有一次恢复的兼容默认值；Loop 创建的宿主任务显式使用最多两次恢复。缺失或无效提交时：计数未达到该任务上限则只追加一次固定纠正提示；达到上限则设置 `Termination.FAILED`。恢复期间不调用历史 `ToolCall`，不复制 native/text dispatch，不触碰 receipt store；Loop 发现 pending/unknown receipt 仍沿用 `external_action_pending` 停止门禁。

## 测试矩阵

1. 新结构序列化使用 `handoff.completed_items/open_questions/summary`，schema 键保持稳定。
2. 旧顶层字段 + 字符串 handoff 成功迁移，迁移文本只出现在摘要，不改变 goal/budgets/终态。
3. 新旧属性读取一致；冲突迁移、危险 Unicode、超限候选、控制面额外字段均拒绝。
4. CheckpointTool 保留完成项、拒绝删除、CAS 失败不改盘。
5. Runner suffix 只包含结构化 handoff 和不可信标记，不泄漏公开报告正文。
6. Loop 的 required submission 可恢复两次，第三次失败；普通 Task/Collaboration 仍一次恢复后失败；恢复过程中工具调用计数保持不变。

## 两轮设计自评结论

- 自评一：没有把 Collaboration `HandoffPacket`、调度器或动态摘要器引入 Loop；单一结构化事实源覆盖用户指定字段。
- 自评二：旧调用输入仍可读但新 schema 不继续宣传自由字符串；恢复增加诊断机会但不会把“再试一次”误实现为副作用重放。
