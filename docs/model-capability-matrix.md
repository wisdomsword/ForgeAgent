# 模型 Capability Matrix（M1 设计文档）

> 数据来源：claude-api skill 内建参考文档（缓存日期 2026-06-24）。这是快照，非实时；上线前用 `GET /v1/models/{id}` 核实一次。
> 范围：ACTION_PLAN.md M2 明确列出的四个 Anthropic 原生模型。gpt-5.5 / gpt-5.4-mini / GLM-5.2 / DeepSeek v4 flash 走 OpenAI 兼容层，登记值与核实来源见 `docs/m6-openai-compatible-client.md` §四（M6 新增，二手聚合数据，非官方一手实测，上线前仍需核实）。

## 矩阵

| 模型 | Model ID | Context | Max Output | 价格（输入/输出，每 1M token） | Tool Use | Vision | Extended Thinking | 推荐档位 |
|---|---|---|---|---|---|---|---|---|
| Claude Fable 5 | `claude-fable-5` | 1M | 128K | $10.00 / $50.00 | 支持，含 structured output | 高精度（长边 2576px） | **始终开启**，不可关闭；`thinking` 参数必须省略或设 `{type:"adaptive"}`，显式 enabled/disabled 都会 400；原始 CoT 从不返回 | 最难的长链路推理/agentic 任务，非默认升级路径——贵且有安全分类器拒答风险 |
| Claude Opus 4.8 | `claude-opus-4-8` | 1M | 128K | $5.00 / $25.00 | 支持，含 structured output | 高精度（长边 2576px） | 支持 adaptive，但**默认关闭**，需显式 `{type:"adaptive"}` | 默认"全力"通用模型，长链路 agentic、代码评审/调试 |
| Claude Sonnet 5 | `claude-sonnet-5` | 1M | 128K | $3.00 / $15.00（2026-08-31 前 intro 价 $2.00 / $10.00） | 支持，含 structured output | 高精度（长边 2576px，Sonnet 系首个） | **默认开启**（省略 `thinking` 参数即启用，相对 Sonnet 4.6 是静默行为变化）；effort 支持全档 low/medium/high/xhigh/max（Sonnet 系首个支持 xhigh/max） | 能力/成本平衡最佳，**ForgeAgent 默认主模型候选** |
| Claude Haiku 4.5 | `claude-haiku-4-5`（全称 `claude-haiku-4-5-20251001`） | 200K | **64K**（当前唯一低于 128K 的模型） | $1.00 / $5.00 | 支持，含 structured output | 支持，但未见高精度模式说明，按标准分辨率处理 | **无确认支持**——未出现在任何"支持 adaptive thinking"名单中；`effort` 参数在该模型上会直接报错 | 最快最便宜，**ForgeAgent 廉价 subagent 档位**，对应 spec.md「小任务交给便宜模型」 |

## 对 ForgeAgent 的结论

- **主模型**：`claude-sonnet-5`。价格与能力平衡最好，且是 Sonnet 系第一个支持 xhigh/max effort 和高精度视觉的型号。
- **Subagent 廉价档**：`claude-haiku-4-5`。注意两点会影响 M2 client 实现：
  1. max output 64K，不是其余三款的 128K，配置里不能写死统一上限。
  2. 不要传 `effort` 参数（会报错）；也不要传 `thinking` 参数（未见支持声明，按"不支持"处理，省略即可）。
- **Fable 5**：仅作为 M5 的 opt-in smoke test，不接入默认路径。接入时需注意：
  - 省略 `thinking` 参数（不可显式 enable/disable）。
  - 必须检查 `stop_reason == "refusal"`，且按 ACTION_PLAN.md 目前范围**不**默认开启 server-side fallback（那是增加复杂度的可选项，v1 不做）。
  - 账号需 30 天数据保留，与 ZDR 组织不兼容——如果用户组织要求 ZDR，Fable 5 直接不可用，需在文档里提示。
- **Opus 4.8**：预留为"用户显式要求更强能力"时的可配置选项，不是默认值。默认 adaptive thinking 关闭，除非配置显式打开。
- **开发期 subagent 模型选择（治开发过程，非产品配置）**：开发 ForgeAgent 时派发给 subagent 的编码/测试任务，**主用 `claude-sonnet-5`**；仅明确的小任务（机械改名、单文件小改、格式化等）用廉价的 `claude-haiku-4-5`。注意这与产品运行时的档位选择是两码事——产品运行时的模型由用户配置驱动；这里说的是 `subagent-task-template.md` 派发时的默认选型。此前模板"默认便宜模型"的表述已据此修正为"默认 sonnet-5、小任务才 haiku-4-5"。
- 四个模型 tool use 与 structured output 全部支持，M2 的模型客户端契约可以对这四个模型统一走 tool-use 接口（即便 ForgeAgent 自身协议层不依赖厂商 function-calling，接入时仍可选择是否使用原生 tool use，契约文档另行定义）。
- Context window 四款统一为 1M（Haiku 除外，200K），M2 配置加载器的默认值可按"每模型独立声明 context_length / max_output"处理，不能全局假设同一个数字——这与 agent `llm/models.py` 的 `ModelInfo` 按模型登记能力的做法一致，值得直接借鉴该模式。
