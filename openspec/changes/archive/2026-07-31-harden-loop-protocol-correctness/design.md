## Context

本 change 收紧现有 loop、protocol、step、工具反馈和协作审计路径，不新增运行时依赖。当前实现已经具备有界 checkpoint/report、严格完成门禁以及文本/native 两套工具调用解析器，但部分边界依赖隐式行为。实现必须保留 M27 的旧 collaboration-source 迁移契约，并继续遵守 M38 的发布暂停。

## Goals / Non-Goals

**Goals：**

- 保持公开 JSON 的 `schema` 键，同时使用 Pydantic 正式 alias 机制。
- 让双通道工具调用身份确定、幂等；冲突时 fail-closed。
- 空 prose 不能完成，并有明确回归测试。
- 建立单一、有界的 `_safe_text` 实现和 English-first continuation 反馈。
- 明确私有 helper 的所有权，并让 capability/receipt projection 失败可观测但不泄漏。

**Non-Goals：**

- 不改变旧 Duo/Triad source 的迁移推断；缺失 source 继续遵循 M27。
- 不重设计 Loop handoff 结构；该内容留给后续独立 change。
- 不引入 LLM 自动拆解器、新依赖、发布自动化、tag、push 或 PyPI 工作。

## Decisions

1. **使用 Pydantic alias，移除告警压制。** 将两个 loop 模型的内部字段改为 `schema_`，设置 alias、按 alias 序列化和严格校验，以兼容旧 JSON。手工 serializer 或 warning filter 会产生版本敏感且可能静默漂移的行为，因此不采用。

2. **在 parser 层合并调用，冲突时拒绝。** 在 `Step` 分发前按显式稳定 ID 合并 text/native 调用。等价重复只保留首次确定顺序的一份；同一 ID 的工具名或规范化参数不同，则生成有界 parse error，并从可分发集合中移除该 ID。仅在 dispatch 层去重会让其他调用者看到不一致的 parsed state，因此不采用。

3. **共享安全 helper，显式传递空值策略。** 提取一个很小的内部模块，调用方传入已有的空值/default 语义，避免机械合并造成 checkpoint 或审计行为变化。

4. **English-first 反馈作为常量文本。** 将模型可见 continuation 常量改为简短英文并保持有界；不引入翻译框架，因为这会扩大范围且没有当前需求。

5. **projection 失败记录固定类型。** capability/receipt projection 失败只记录稳定事件名和异常类型，返回现有安全 fallback；不记录异常正文、工具参数、路径、secret 或 goal 正文。

## Risks / Trade-offs

- [风险] 历史测试从 `step` 导入 `_apply_edit`。→ 更新测试从 `tools` 导入，不保留运行时兼容别名。
- [风险] 模型可能省略稳定调用 ID。→ 只对显式相同 ID 去重，不做启发式参数匹配。
- [风险] 错误顺序影响快照。→ 保持首次出现顺序，并使用确定性的有界冲突消息。
- [风险] 既有测试依赖中文 continuation。→ 更新精确断言，保持反馈含义等价，不改变公开 API。

## Migration Plan

读取旧 checkpoint/report 时使用 `schema` alias，写出仍使用同一键；先运行兼容性 focused tests，再运行更大范围测试。不需要数据迁移或发布动作。遇到 parser 冲突时沿用 parse-error 反馈环，不执行有歧义的调用。

## Open Questions

无。本 change 明确把 Loop handoff 结构化和 Collaboration stop-reason projection 放到后续顺序 change。
