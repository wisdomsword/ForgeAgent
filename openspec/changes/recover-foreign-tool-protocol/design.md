## Context

`Step._run_rounds()` 允许没有工具、解析错误或显式状态的非空文本直接以 `answered_in_prose` 结束。这对知识问答是正确的，但 `protocol.parse()` 目前只识别 Forge HTML comment 协议和供应商原生 `AssistantMessage.tool_calls`；模型写入正文的其他 coding-agent 工具格式会被当成普通 prose。真实样本中的 `{"cmd":"pwd && ls -la"}` 与 `todo_write` + `Params:` 因此既未执行也未触发恢复。

## Goals / Non-Goals

**Goals:**

- 对真实观察到的两类外部工具文本产生固定、可恢复的协议错误。
- 让现有 Step 反馈环要求模型改用 Forge CodeBlock + Exec，并保留 sandbox、schema、确认和审计边界。
- 保持普通 prose、代码示例和供应商原生结构化 tool calls 的现有行为。

**Non-Goals:**

- 不直接执行裸 `cmd`、shell 文本或 `todo_write` 参数。
- 不实现其他 agent 的完整工具协议，不新增通用 shell 工具或厂商 tools schema。
- 不按用户目标关键词分类“是否需要执行”，不改变 CLI/public schema。

## Decisions

1. 在 `protocol.parse()` 中识别不受支持的工具文本，而不是在 CLI 或 Task 中特殊判断。解析器是两个受支持工具通道的现有归一化边界；把第三方正文工具形态变成 `ParseError` 后，可直接复用现有有界反馈环。
2. 使用结构化 JSON 解码识别行边界上的独立 `cmd` 对象，只接受已观察到的命令 envelope；使用精确行标记识别 `todo_write` + `Params:`。不通过模糊自然语言关键词判断执行意图。
3. Markdown fenced code 中的示例不触发恢复，避免破坏解释协议或代码的普通问答。
4. 错误反馈使用固定文本，不回显裸命令内容；外部语法永不绕过 Forge 的 tool schema、sandbox、确认和审计。

## Risks / Trade-offs

- [模型继续输出其他未识别的外部协议] → 本 hotfix 只覆盖真实证据；新增形态必须先取得样本和回归测试，避免建立脆弱的通用猜测器。
- [知识回答包含独立 `cmd` JSON] → fenced 示例明确排除；非 fenced 且形同真实工具调用的内容进入一次或多次有界恢复，最终仍受 `max_rounds` 限制。
- [模型反复拒绝 Forge 协议] → 不伪造完成或直接执行，按现有最大轮次终止并保留无执行证据。

## Migration Plan

无需数据迁移。新增解析测试先取得 RED，再实现最小 detector；回滚时删除 detector 和对应 delta spec/测试即可恢复原行为。

## Open Questions

无。真实样本已经界定本次最小覆盖范围。
