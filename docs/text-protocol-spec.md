# 文本协议 Spec（M1 设计文档）

> 借鉴来源：agent `agent/response.py`（正则解析）+ `agent/blocks.py`（CodeBlock/CodeBlocks）+ `agent/toolcalls.py`（ToolCall/ToolCallProcessor）。核心机制原样借鉴（判定见 ACTION_PLAN.md §二），命名与工具集按 ForgeAgent 范围重新设计。
> 目的：让 ForgeAgent 对接任意模型（claude-sonnet-5 / gpt-5.5 / GLM-5.2 / DeepSeek v4 flash）时不依赖厂商 function-calling API——协议是纯文本 Markdown + HTML 注释标记，任何能输出 Markdown 的模型都能用。

## 设计原则

1. **模型无关**：协议标记是 HTML 注释包裹的 JSON，不是厂商 tool_call 字段。即使模型支持原生 function-calling，也不强制依赖它（M2 范围内不做原生 tool-use 对接，纯文本协议是唯一路径，简化实现）。
2. **人类可读**：Markdown 正文本身就是可读的解释，代码块是普通 fenced code block，标记是不显眼的注释——终端渲染时几乎不打扰阅读。
3. **可恢复的畸形输入**：JSON 解析失败、字段缺失等要产生结构化错误反馈给模型，而不是崩溃或静默丢弹。M2 单测明确要求覆盖畸形输入用例（ACTION_PLAN.md M2 验证项）。
4. **最小工具集**：v1 只定义 `Exec` / `Edit` 两个工具。不做 agent 的 `SubTask`（运行时子任务委托，15 个 golden task 无一需要，按最小范围裁掉；注意运行时 `SubTask` 与开发期的 `subagent-task-template.md` 是两回事，后者属开发 harness，不进运行时协议）、`MCP`（依赖 mcp 库）与 `Survey`（依赖第三方 promptabs 库）——**MCP/Survey 排在 M7 引入**（届时才加对应第三方依赖）。工具集是协议的一部分，但具体工具的增减不影响标记语法本身。

## 标记语法

### 代码块标记

```
<!-- CodeBlockStart: {"name": "<block_name>", "path": "<optional_path>"} -->
```<language>
<code>
```
<!-- CodeBlockEnd: {"name": "<block_name>"} -->
```

- `name`：块的唯一标识，用于后续 `Exec`/`Edit` 引用。必填。
- `path`：落盘路径，可选；未提供时默认写入约定目录（如 `.forgeagent/blocks/<name>.<ext>`）。
- Start 与 End 的 `name` 必须一致，不一致视为解析错误。
- `language`（fenced code block 的语言标注）决定执行器分发（v1 仅 `python`）。
- **变长 fence（Y3，必须实现）**：代码本身可能含三反引号（如生成 Markdown 的 Python 代码）。解析器不能写死 ` ``` `，须用变长反引号 + 反向引用匹配——直接借鉴 agent `response.py:24` 的 `(?P<ticks>`{3,})...(?P=ticks)`，用不少于三个的反引号开栏、结尾用同样数量闭栏。M2 单测须含"代码块内嵌三反引号"用例。

命名沿用 agent 的 `Block-Start`/`Block-End` 语义，但改为 `CodeBlockStart`/`CodeBlockEnd`——避免和厂商已有的 "Block" 术语混淆，同时更明确这是"代码块"而非通用块。

### 工具调用标记

```
<!-- ToolCall: {"id": "<uuid>", "name": "<ToolName>", "arguments": {...}} -->
```

- `id`：本次调用的唯一 ID。若模型未提供，解析器自动生成（借鉴 agent `uuid4().hex` 兜底）。
- `name`：`Exec` / `Edit` 二者之一。未识别的名称不静默丢弹，直接产生解析错误反馈（v1 不做 agent 的"未知工具名 fallback 成 MCP"逻辑，因为 v1 没有 MCP 兜底通道）。
- `arguments`：按 `name` 对应的参数 schema 校验（下节）。

### 任务状态 Front Matter（可选）

延续 agent 的 YAML front matter 机制，允许模型在响应开头声明任务完成状态：

```yaml
---
task_status:
  completed: true
  confidence: 0.9
---
```

或未完成时：

```yaml
---
task_status:
  completed: false
  status: need_info
  reason: "..."
  suggestion: "..."
---
```

`status` 取值：`refused` / `need_info` / `failed`。这一段不是必填——省略时协议按"任务继续"处理。

## 工具参数 Schema

### `Exec`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | str | 否 | 引用已存在的代码块；省略且提供 `code` 时自动生成临时名 |
| `code` | str | 否（二者至少一个） | 直接提供代码，会创建/更新同名代码块 |
| `language` | enum | 否，默认 `python` | v1 仅 `python`。所有 golden task 都是 Python，bash/js 执行器属最小范围外的 scope 扩张，按需再加——但语言字段本身保留为 enum，加语言只扩枚举、不改协议 |

`name` 与 `code` 至少提供一个——都不提供是解析错误。v1 只做 Python，故不涉及"非 python 必填 path"的分支（该分支留待引入其它语言时再定义）。

### `Edit`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | str | 是 | 目标代码块，必须已存在 |
| `old` | str | 是 | 精确匹配的原字符串（含空白） |
| `new` | str | 是 | 替换后的字符串（可为空表示删除） |
| `replace_all` | bool | 否，默认 false | 匹配到多处时是否全部替换 |

行为借鉴 agent `_call_edit`：`old` 未匹配到 → 错误；匹配多处且 `replace_all=false` → 错误并提示加 `replace_all` 或提供更精确上下文；成功则生成新版本代码块（版本号 +1），不覆盖旧版本历史。

> **无 `SubTask`（v1）**：运行时子任务委托已从 v1 协议裁掉（B1 裁决）。不要把它和开发期的 `subagent-task-template.md` 混淆——后者是 Claude Code 派发编码任务的开发 harness 契约，与运行时协议无关。将来若运行时确需子任务委托，应为它单独定义返回语义（一个纯文本 `result` 字段即可），而不是复用开发期的五字段模板。

## 解析流程（供 M2 实现参照）

1. 提取并解析 YAML front matter（若存在），得到任务状态；解析失败记为错误但不中断后续解析。
2. 在去除 front matter 后的正文上，用正则依次提取所有 `CodeBlockStart`/`CodeBlockEnd` 配对块。
3. 提取所有 `ToolCall` 标记。
4. 每个 JSON 字段解析失败、字段缺失、名称不匹配等，都生成结构化 `ParseError`（`error_type` + `message` + 原始片段），汇总后一次性反馈给模型，而不是逐条中断。
5. 解析结果是否需要继续下一轮，由"是否存在错误"或"是否存在待执行的工具调用"决定——错误本身也要驱动下一轮（模型据此修正）。

## 与 agent 的差异（明确记录，避免后续误"借鉴过头"）

| 项                      | agent                                           | ForgeAgent v1                                                | 后续安排 |
| ---------------------- | ------------------------------------------------- | ------------------------------------------------------------ | --- |
| 标记名                    | `Block-Start`/`Block-End`/`ToolCall`              | `CodeBlockStart`/`CodeBlockEnd`/`ToolCall`（更明确）              | 稳定，不变 |
| 工具集                    | Exec/Edit/MCP/SubTask/Survey                      | Exec/Edit（SubTask 运行时委托 v1 裁掉；MCP、Survey 依赖的第三方库不在 v1 依赖清单内） | **M7 加 MCP/Survey**（随 MCP/Survey 里程碑引入对应第三方依赖）；SubTask 运行时委托暂无排期，需要时单独定义纯文本 result 语义 |
| 原生 function-calling 兼容 | 同时支持 OpenAI 原生 tool_calls 解析（`ToolSource.OPENAI`） | v1 不做，纯文本协议单通道，简化实现                            | **M6 支持**（随 OpenAI-compatible client）：加 `ToolSource.OPENAI` 双通道解析，参照 agent 设计；文本协议单通道仍保留（与 `model-client-contract.md` 差异表 tool_calls 行对齐） |
| 未知工具名                  | 静默 fallback 成 `MCP`                               | 直接报解析错误（没有 MCP 兜底通道）                                         | M7 有 MCP 后可选择恢复 fallback 或保持显式报错（届时定） |

## 待 M2 落地的单测清单（来自本 spec 的可测性要求）

- 正常 Exec/Edit 各一个用例（happy path）。
- 代码块内嵌三反引号 → 变长 fence 正确匹配，不提前闭栏（Y3）。
- 畸形 JSON（截断、多一个逗号）→ 产生 `JSONDecodeError` 类型的 `ParseError`，不崩溃。
- `CodeBlockStart`/`CodeBlockEnd` 的 `name` 不一致 → 报错并跳过该块，不影响其余块解析。
- `Edit` 的 `old` 未匹配 / 匹配多处未加 `replace_all` → 报错，不生成新版本。
- 未知 `ToolCall.name` → 报错，不静默兜底。
- Front matter 缺失 / 存在但格式错误两种场景均可正常解析正文。
