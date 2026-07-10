# M6 设计草稿：OpenAI-compatible Client

> 状态：**草稿，待用户评审**（沿用 M1 的"一页设计文档 + 用户评审"节奏，未获批准前不进代码）。
> 范围：ACTION_PLAN.md M6 行——OpenAI-compatible client；golden 任务集扩到 200（本文档不展开任务集内容，扩容是独立的执行任务，待本设计批准后再派发）。
> 契约基准：`docs/model-client-contract.md`（**本次不改契约**，只新增一个实现类，呼应该文档 §覆盖范围"届时新增实现类即可，不改契约"）。
>
> **M6 后续更正（真实冒烟暴露的路由 bug）**：本文档下方提到的 `config.py` provider-profile 机制、`capabilities.py` 静态登记表、`ClientConfig` 均已在真实三厂商冒烟测试后被 `model_registry.py`（YAML 分组注册表，`res/models.yaml` + `res/config.yaml`）取代——原因是固定优先级扫描一旦用户同时设置多个厂商的环境变量（正常用法）就会路由错厂商。本节以下内容按撰写时的设计保留，作为决策过程记录；当前实现以 `docs/model-client-contract.md`"配置契约（M6 修订）"一节和 `model_registry.py` 为准。

## 一、结论先行

M6 的核心工作是给 `ModelClient` 抽象加一个 `OpenAICompatibleClient` 实现，服务 gpt-5.5 / GLM-5.2 / DeepSeek v4 flash 三个厂商——一个类，靠 `base_url` + 能力登记区分厂商，不在调用点判断厂商名。**先只做结构 + 单测（仿 M2 的 MockClient 模式），真实三厂商冒烟留给用户 opt-in**，与 M5 的节奏一致。有两个能力细节（thinking/effort 在 OpenAI 兼容协议下的实际参数名）目前只查到间接证据、没有官方文档实测，标记为**开放问题**，需要在写 capability-gating 代码前用真实 `curl` 或官方文档核实，不能凭猜测写入登记表。

## 二、复用与新增

| 项 | 处理 |
|---|---|
| `ModelClient` 抽象接口、`GenerationParams`/`AssistantMessage`/`ClientError`/`ModelCapability`/`ClientConfig`/`RetryPolicy` | **原样复用，零改动** |
| `system` 消息处理 | 新增：OpenAI 兼容协议把 `role=system` 保留在 `messages` 数组内（`model-client-contract.md` 已预判此差异），不像 Anthropic 抽成顶层参数 |
| 异常分类（`_KIND_BY_EXC_NAME` 的模式） | **建议提取为共享函数**（见五、1） |
| `model_discovery.py` 的"dated snapshot 自动解析" | **不复用**——那是 Anthropic 代理特有的问题（`/v1/models` 返回带日期后缀的 id）。OpenAI 兼容三家（OpenAI 官方 / Z.ai / DeepSeek）的模型 id 是否有同类问题未知，M6 先不做自动发现，模型 id 由用户配置直填；如实测发现类似问题再决定是否扩展该机制到通用形态 |
| `config.py` 的 provider profile 机制 | **原样复用**：现有 `LLM_API_KEY`/`LLM_BASE_URL` 这对通用命名的 profile 本就是给非 Anthropic 后端预留的（`ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL` 专属 Anthropic 原生）——M6 直接用 `LLM_*` 这对，三个厂商各自的 `base_url` 由用户配置区分，无需新增 profile |
| `capabilities.py` 的静态登记表 | 新增三条模型记录（见四） |
| CLI (`cli.py`) 的 `SMOKE_MODELS`/`build_real_client` | 新增按 client 类型分派：`model` 属于 Anthropic 登记表用 `AnthropicClient`，否则用 `OpenAICompatibleClient`（具体判据见五、2） |

## 三、Client 实现设计（仿 `anthropic_client.py` 的既有模式）

```python
class OpenAICompatibleClient(ModelClient):
    """One client class for any OpenAI-compatible endpoint (OpenAI/Z.ai/DeepSeek/...).
    Vendor distinction lives entirely in base_url + the capability registry — this
    class never branches on vendor name.
    """
```

- **懒加载 SDK**：`import openai` 放在 transport 闭包内，不在模块顶层——保持"注入 transport 就能测、不装 SDK 也能测"的既有约定（`anthropic_client.py` 已验证的模式）。
- **可注入 transport**：`Transport = Callable[[dict, float], Any]` 签名不变，默认实现调 `openai.OpenAI(api_key=..., base_url=...).chat.completions.create(timeout=..., **request)`。
- **响应解析走 duck-typing**：`raw.choices[0].message.content` / `raw.choices[0].finish_reason` / `raw.usage.prompt_tokens` / `raw.usage.completion_tokens`——同样不 `isinstance` 绑定 SDK 具体类型，字段名对齐 OpenAI 的返回结构（与 Anthropic 的 `content`/`stop_reason`/`usage.input_tokens` 不同，映射在这个 client 内部完成，不污染通用 `AssistantMessage`）。
- **`finish_reason` 到 `stop_reason` 的映射**：OpenAI 用 `"stop"`/`"length"`/`"content_filter"`/`"tool_calls"`，Anthropic 用 `"end_turn"`/`"max_tokens"`/`"refusal"`。`AssistantMessage.stop_reason` 字段目前是自由字符串（`models.py` 未做枚举约束），**建议原样透传各厂商的原始值，不强行统一措辞**——上层协议层（`text-protocol-spec.md` 的 front-matter `task_status`）已经是模型自己声明完成状态的机制，不依赖 `stop_reason` 的具体取值做判断,所以透传不破坏现有逻辑。但 `"content_filter"` 需要在文档里注明:这是 OpenAI 生态对应 Anthropic `"refusal"` 的近似物,语义不完全一致(refusal 是安全分类器拒答,content_filter 可能是输入侧过滤),接入时留意区分。

## 四、能力登记草案（**需核实,标记为草稿值**)

数据来源:2026-07-08 网络检索(OpenRouter/OpenAI 官方页/Novita/apidog 等二手聚合信息),**非官方一手文档实测**,与现有 `model-capability-matrix.md` 的"缓存快照,上线前用 API 核实一次"要求相同,这里同样只是草案:

| 模型                | Model ID(草案,以用户配置为准) | Context   | Max Output | 价格(输入/输出,每 1M token)                            | Thinking/Effort                                                                                                                                                                                                                                     |
| ----------------- | -------------------- | --------- | ---------- | ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GPT-5.5           | `gpt-5.5`            | 1,050,000 | 128K       | $5.00 / $30.00 (cached $0.50; >272K 输入 2×/1.5×) | reasoning_effort: none/low/medium/high/xhigh                                                                                                                                                                                                        |
| GLM-5.2           | `glm-5.2`            | 1,048,576 | 131,072    | Z.ai $1.40/$4.40；OpenRouter $1.20/$4.10（多平台价差）  | **Z.ai 原生**：`thinking:{"type":"enabled"/"disabled"}`开关 + `reasoning_effort`(max/xhigh/high/medium/low/minimal/none, 默认 max；实际仅 high/max 两档有效, low→high, xhigh→max, none/minimal→跳 thinking)；**百炼封装**用 `enable_thinking:bool`+ 同 `reasoning_effort`​ |
| DeepSeek v4 flash | `deepseek-v4-flash`  | 1,000,000 | 384K       | $0.14 / $0.28 (cache hit $0.0028)               | **双模，thinking 默认**；`extra_body={"thinking":{"type":"disabled"}}`关，`reasoning_effort="high"`开；                                                                                                                                                       |

**这张表在写 `capabilities.py` 代码前必须做的事**(不能跳过):
1. 各厂商官方 API 文档核实 context/max_output 的准确数值(上表已出现口径冲突,如 GPT-5.5 的输出上限)。
2. 实际发一次请求确认 `effort`/`thinking` 类参数在 OpenAI 兼容协议下的真实字段名和取值——这是 capability-gating 翻译规则的核心依据,错了会导致和 Haiku/Fable 同样性质的"传参报错"问题,但发现得比登记时晚(会在真实调用才炸,而不是配置期)。
3. 确认三个厂商是否都严格遵循 OpenAI 的 `chat.completions` 请求/响应 schema,还是有厂商特有的字段(如 GLM 的 thinking 独立字段而非 `reasoning_effort`)——如有差异,可能需要在 client 内部做"厂商专属参数名"的一层轻量映射(仍收敛在 client 内,不外泄给调用方,呼应 capability-gating 原则),而不是假设三家完全一致。

## 五、开放问题裁决（2026-07-08，用户已裁决 1/2/4，本计划据此定稿；3 待裁决见下）

1. **异常分类映射提取成共享模块**。**裁决：同意**。新增 `transport_errors.py`（不带厂商前缀），承载 `TransportError`/`classify_transport_exception`/`_KIND_BY_EXC_NAME`；`anthropic_client.py` 与新的 `openai_compatible_client.py` 都从它导入，不再各自定义一份。
2. **CLI 按 `--model` 分派 client 类**。**裁决：方案 (a)**——`ModelCapability` 新增 `client_kind: Literal["anthropic", "openai_compatible"]` 字段，`capabilities.py` 每条登记附带该字段，`cli.py` 的 `build_real_client` 按此字段构造对应 client。这是能力声明的扩展字段，不改 `ModelClient` 接口本身，不算破契约。
3. **`ToolSource.OPENAI` 原生 tool_calls 双通道**。**裁决：执行**（覆盖下节草稿分析的"建议不做"结论，见下节末尾的裁决说明）。
4. **真实冒烟顺序**。**裁决**：先接入 **gpt-5.4-mini**（`OPENAI_API_KEY`/`OPENAI_BASE_URL` 已就位）验证 client 骨架，再接入 **glm-5.2** 与 **deepseek-v4-flash**（本节撰写时预期用 `LLM_API_KEY`/`LLM_BASE_URL`，同一个 base_url 下两个不同 model_id）。三者共用一个 `OpenAICompatibleClient` 类，冒烟顺序即验证顺序：跑通一个说明骨架本身没问题，后两个主要验证 capability-gating 的厂商专属参数映射（`thinking`/`reasoning_effort`）是否按第四节的真实值正确工作。

### 3. `ToolSource.OPENAI` 双通道利弊分析（供决策）

**背景**：`text-protocol-spec.md:108` 在 M1 阶段预留了"M6 随 OpenAI-compatible client 一起加原生 tool_calls 双通道解析"，但那是预留，不是承诺执行——现在到了 M6，需要基于实际情况重新判断是否要做。

**支持做的理由**：
- OpenAI 系模型（尤其 gpt-5.4-mini 这类经过大量 function-calling RLHF 的模型）原生 tool-calling 路径上，API 会对模型输出做 JSON schema 约束，理论上比"指望模型正确输出 HTML 注释包裹的 JSON 文本标记"更不容易出现畸形/遗漏。
- agent 本身已有这条路径的实现可参考，设计风险较低。

**反对做的理由（权重更高）**：
- **没有当前证据表明需要它**。现有 80 个 golden task 全部靠文本协议在 4 个 Anthropic 模型上跑通；三个新模型接入的直接目标是"能用文本协议驱动 Exec/Edit"，不是"用上厂商原生 function-calling"——这是两个不同的目标，后者是能力扩展，前者才是 M6 范围内的任务。
- **双通道意味着协议层复杂度翻倍**：`protocol.py` 要同时认得两种工具调用来源并分别解析，`Task`/`Step` 循环要处理"这条 AssistantMessage 里的工具调用是文本标记来的还是原生 tool_calls 来的"，测试矩阵也要覆盖两套。这正是 spec.md 明确反对的"没有实际需求驱动的复杂度"。
- **M5 观察到的残留问题（模型偶发不遵循协议、用纯 prose 回答）性质不同，双通道未必能治它**。那个问题是模型不服从系统提示词里的角色/协议设定，属于提示词遵循度问题；换成原生 tool_calls 不改变模型是否愿意"扮演 ForgeAgent 角色"，模型一样可能不调用任何工具、直接用 prose 回答。用双通道去对治这个问题是**药不对症**，真正对治手段是提示词加固（已作为已知后续项记录在 ACTION_PLAN.md）。
- **文本协议本身是模型无关性的关键设计**（CLAUDE.md 大图第 3 点），三个新模型接入的意义之一就是验证"文本协议在非 Anthropic 模型上一样好用"——如果一开始就给 OpenAI 系开小灶用原生通道，反而没验证到这个假设，且未来接入 GLM/DeepSeek 之外的第五个厂商时，又要重新判断"这家要不要也开原生通道"，形成不收敛的特例累积。

**草稿建议**（撰写本节时）：M6 不做双通道，继续单文本协议路径——上面列出的四条反对理由，尤其"没有实际需求驱动的复杂度"，在撰写时是合理的谨慎判断。

**实际裁决（覆盖上述建议）：执行双通道**，已在 `openai_compatible_client.py`（`AssistantMessage.tool_calls: list[NativeToolCall]`，`_parse_response` 填充）与 `protocol.py`（新增 `ToolCallSource` 枚举 + `ToolCall.source` 字段、`_parse_native_tool_calls`、`parse()` 新增可选 `native_tool_calls` 参数）实现完毕，`step.py._handle_reply` 已接上 `native_tool_calls=reply.tool_calls`。两条通道解析到同一个 `ToolCall` 列表，仅靠 `source` 字段区分来源，`step.py` 的下游派发/执行逻辑完全不分支判断 `source`——复杂度增量收敛在协议解析层，没有扩散到执行环路,验证见 `test_step.py::test_both_channels_in_one_reply_both_execute`。

`text-protocol-spec.md:108` 那行"M6 支持（随 OpenAI-compatible client）：加 `ToolSource.OPENAI` 双通道解析"的表述**在撰写时就已经是准确的**（预判成立），不是本节草稿一度建议改写成"推迟"的那样——此前那条改写指令是基于草稿建议做出的,现已随裁决一并撤销,该文档该行无需任何改动。

## 六、单测清单(比照 `model-client-contract.md` §待 M2 落地的单测清单 的模式)

- `ClientConfig` 缺 key 环境变量 → 构造时报错(复用现有 `config.py` 机制,无需新代码)。
- 用注入的假 transport 验证:请求体正确组装(model/messages/system 消息在 messages 数组内而非顶层)、响应解析正确(`choices[0].message.content` → `AssistantMessage.content`)、`finish_reason` 透传到 `stop_reason`。
- 异常分类:模拟各 SDK 异常类名 → 正确的 `kind` + 可重试性,与 Anthropic client 的对应测试用同一套断言结构(如做了开放问题 1 的提取,两个 client 的这组测试可以共享参数化用例)。
- Capability-gating(依赖第四节核实后的真实值定稿,当前无法先写断言,标记为**待核实值定稿后补充**)。
- 三个模型的 `ModelCapability` 登记值与本文档表格一致(防止表格和代码漂移,与现有 Anthropic 四模型测试同构)。

---

**评审前提醒**:第四节的能力数值和 §五 的四个开放问题是本设计**尚未定案**的部分——尤其是 thinking/effort 的真实参数名,不核实清楚就写代码,大概率重复 M2 时"Haiku 传 effort 会报错"那类问题,只是这次是在三个新后端上各来一遍。建议核实顺序:先选一个厂商(建议 DeepSeek,协议疑似最贴近标准 OpenAI schema)把 client 骨架和单测跑通,再扩其余两家——即开放问题 4 的建议,与写这份文档时的整体节奏一致。
