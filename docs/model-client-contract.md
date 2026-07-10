# 模型客户端契约（M1 设计文档）

> 借鉴来源：agent `llm/base.py`（`BaseClient` 抽象基类 + 重试/退避 + `Message`/`AIMessage`/`ErrorMessage`）与 `llm/models.py`（`ModelInfo`/`ModelRegistry` 能力登记模式）。判定：**借鉴简化**（ACTION_PLAN.md §二）——保留统一重试/退避/错误处理的抽象基类，砍掉 agent 里 v1 不需要的部分（多源 native tool_calls 解析、stream_processor 回调等按需精简）。
> 覆盖范围：M2 交付的 Anthropic 原生 client + MockClient。OpenAI 兼容层（gpt-5.5/GLM-5.2/DeepSeek）留到 M6，本文档先把抽象接口定稳，届时新增实现类即可，不改契约。

## 设计目标

1. **模型无关的调用面**：上层（Task/Step 循环）只依赖本契约定义的接口，不感知具体是 Anthropic SDK 还是 Mock。
2. **能力差异显式声明**：不同模型在 `thinking`/`effort`/`max_output_tokens` 上的差异（见 `model-capability-matrix.md`）通过配置和能力登记表暴露，而不是让调用方各自 if/else 判断模型名。
3. **无 key 可测**：MockClient 必须能在没有真实 API key 的情况下驱动完整的 Task/Step 循环（对应 ACTION_PLAN.md §三 item 3 的"mock LLM 回放测试"）。

## 核心接口

```python
class GenerationParams(BaseModel):
    """一次生成的可调参数。上层用统一字段表达意图，不感知模型差异。"""
    max_output_tokens: int | None = None   # None = 用该模型 capability 的上限
    temperature: float | None = None
    thinking: Literal["on", "off", "auto"] = "auto"  # 三态意图（A1）：on=尽量开、off=尽量关、auto=用模型默认
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    timeout_seconds: float = 120.0          # 单次调用超时（Y2 补：此前缺失）

class ModelClient(ABC):
    """所有模型客户端的统一接口。"""

    @abstractmethod
    def complete(self, messages: list[Message], params: GenerationParams | None = None) -> AssistantMessage | ClientError:
        """发起一次补全请求，返回助手消息或结构化错误。永不抛出未捕获异常。"""

    @property
    @abstractmethod
    def capability(self) -> ModelCapability:
        """返回当前模型的能力声明（见下）。"""
```

- `complete()` 是唯一的调用入口，同步阻塞（v1 不做流式——ACTION_PLAN.md 技术选型未提流式需求，最小范围原则下不做）。
- **参数用显式的 `GenerationParams`，不用 `**kwargs`（Y1 修正）**：初稿的 `**kwargs` 让契约的"能力差异不外泄给调用方"目标落空。现在上层永远用统一字段表达**意图**（"要不要思考"、"多大 effort"），由**各 client 实现按自己的 `capability` 把意图翻译成后端实际参数**——这是 capability-gating 的落点，下节详述。
- 返回 `AssistantMessage`（成功）或 `ClientError`（错误性质见 `kind`），永不向上抛异常——错误处理在契约内部完成，上层只需判断返回类型。这一点直接借鉴 agent `BaseClient.__call__` 的"捕获所有已知异常，转成 `ErrorMessage`"模式。

### Capability-gating（Y1，契约核心）

调用方**从不**根据模型名写 if/else。翻译规则收敛在 client 实现内部，依据 `self.capability`：

| 上层意图 | client 依 capability 的翻译规则 |
|---|---|
| `thinking="on"` | `supports_thinking=False`（Haiku 4.5）→ 忽略，不传（该模型无思考能力）；否则请求思考（如传 `{type:"adaptive"}` 或按后端约定，Fable 5 本就强制开、省略即可） |
| `thinking="off"` | `thinking_always_on=True`（Fable 5）→ **无法满足**，记 debug 日志并按"开"执行（模型不支持关）；`supports_thinking=False`（Haiku）→ 本就不思考，无操作；否则按后端关思考的方式处理（若该模型默认开且不可显式关，同样降级为"关不掉"并记日志） |
| `thinking="auto"` | 用模型默认：省略 `thinking` 参数（Sonnet 5 省略即开、Fable 5 强制开、Haiku 无思考）——**最安全的默认，永不触发 400** |
| `params.effort` 有值 | `supports_effort=False`（Haiku 4.5）→ **丢弃该参数**（传了会报错），可选记一条 debug 日志；否则透传 |
| `params.max_output_tokens=None` | 取 `capability.max_output_tokens`（Haiku 是 64K，其余 128K）——不硬编码统一上限 |

**关于 `thinking="off"` 的诚实边界**：部分模型（如 Sonnet 5 默认开思考、Fable 5 强制开）可能无法真正关闭思考。client 遇到"关不掉"时**不报错**，而是降级为该模型能做到的最接近状态 + 记 debug 日志。因此 `off` 是"尽量关"的意图，不是硬保证——这个语义要在调用方文档里说清，避免误以为 `off` 一定生效。

这样"Haiku 不能传 effort/thinking"、"Fable 不能显式传 thinking"这类规则**只在 client 内写一次**，上层和其它 client 全不受影响。新增模型只加一行 capability 登记，不改调用点。

## 消息模型

```python
class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"

class Message(BaseModel):
    role: Role
    content: str
```

v1 只做纯文本消息（不做 agent 的多模态 `ImageItem`/`TextItem` 联合类型——图像输入超出当前 golden task 范围，属于最小范围原则下的裁剪，需要时再加）。

```python
class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    # 供上下文压缩（M3）与成本核算参考；字段名对齐 Anthropic usage 结构，
    # OpenAI 兼容层接入时在各自 client 内做字段映射，不污染这个通用模型。

class AssistantMessage(Message):
    role: Literal[Role.ASSISTANT] = Role.ASSISTANT
    usage: TokenUsage
    stop_reason: str      # 透传后端原始值（如 "end_turn"/"max_tokens"/"refusal"）
    # 注意：安全分类器拒答是"正常 200 响应 + stop_reason='refusal'"（见 capability matrix），
    # 因此 refusal 是 AssistantMessage 的一种，不是 ClientError——不要放进 ClientError.kind。

class ClientError(BaseModel):
    message: str
    kind: Literal["network", "auth", "rate_limit", "invalid_request", "timeout", "unknown"]
    attempts: int         # 实际尝试次数（含首次）
    # 语义修正（Y2）：不用 retryable 布尔——"重试耗尽后返回的错误"再标 retryable=True
    # 会误导调用方以为还该重试。改用 kind 表达错误性质，是否已尽力重试由 attempts 体现。
    # 调用方按 kind 决策：network/rate_limit/timeout 是重试已耗尽的可恢复类，
    # auth/invalid_request 是配置/请求错误（从不重试）。
    # refusal 不在此枚举——它是成功响应（AssistantMessage.stop_reason），由任务层处理。
```

**System 消息处理（Y2）**：Anthropic API 的 `system` 是**顶层参数**，不是 `messages` 数组里的一项；OpenAI 则是 messages 里 role=system 的一条。因此 `complete()` 收到的 `list[Message]` 里若含 `Role.SYSTEM`，各 client 实现负责按自己后端的要求转换（Anthropic client 抽出为顶层 `system=`，OpenAI client 保留在数组内）。这个差异吸收在 client 实现层，**上层永远用统一的 `list[Message]` 表达，不感知厂商差异**。

## 能力声明

```python
class ModelCapability(BaseModel):
    model_id: str
    context_window: int
    max_output_tokens: int
    supports_thinking: bool          # 是否接受 thinking 参数
    thinking_always_on: bool         # Fable 5 特例：True 时上层不能显式配置 thinking
    supports_effort: bool            # 是否接受 effort 参数（Haiku 4.5 为 False）
```

登记表按模型静态声明（借鉴 agent `ModelRegistry` 从 YAML 加载的模式，但 v1 直接用 Python dict 常量或简单 YAML 均可，M2 实现时二选一，不预先决定，避免过度设计）：

| model_id | context_window | max_output_tokens | supports_thinking | thinking_always_on | supports_effort |
|---|---|---|---|---|---|
| `claude-sonnet-5` | 1,000,000 | 128,000 | true | false | true |
| `claude-opus-4-8` | 1,000,000 | 128,000 | true | false | true |
| `claude-haiku-4-5` | 200,000 | 64,000 | false | false | false |
| `claude-fable-5` | 1,000,000 | 128,000 | true | true | true |

数据来源与推荐用途见 `model-capability-matrix.md`，此表只保留契约需要的机器可读字段。

## 配置契约（M6 修订：`ClientConfig` 已废弃，改为 YAML 分组注册表）

v1 设计曾用 `ClientConfig`（单条配置，`api_key_env` 固定优先级扫描）。M6 真实冒烟测试暴露了根因 bug：当用户同时导出多个厂商的环境变量（这是正常用法，见 CLAUDE.md 项目使命的"通用大模型，配置驱动"要求），固定优先级扫描会把请求路由到*先匹配到 key 的那个 profile*，而不是模型实际所属的厂商——与请求的模型无关，取决于哪个环境变量先设置。改为按 model_id 精确路由到其注册的 group，不做扫描。详见 `model_registry.py`。

两个内置 YAML 文件，各管一件事，避免用户重复配置：

- `src/forgeagent/res/models.yaml` —— 模型能力声明（`ModelCapability` 字段 + `aliases`），不含任何连接信息。
- `src/forgeagent/res/config.yaml` —— provider 分组的路由信息（`api_key_env`/`base_url_env` + 该组下的 `models` 列表），不含能力字段。

```python
class ModelEntry(BaseModel):     # models.yaml 的一条模型声明
    client_kind: Literal["anthropic", "openai_compatible"]
    context_window: int
    max_output_tokens: int
    supports_thinking: bool
    thinking_always_on: bool
    supports_effort: bool
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    aliases: list[str] = []

class GroupConfig(BaseModel):    # config.yaml 的一个 provider 分组
    api_key_env: str | None = None
    api_key: str | None = None   # 仅用户本机覆盖文件可填字面 key，内置文件永不出现
    base_url_env: str | None = None
    base_url: str | None = None
    models: list[str] = []       # 该组服务的 model_id 列表（跨组不可重复，加载时校验）
```

- **硬约束不变**：内置 `res/config.yaml` 只存环境变量名，永不出现真实 key。`~/.forgeagent/config.yaml`（用户本机、不进 git）可选择性填字面 `api_key`/`base_url`，字面值优先于对应的 `*_env`。
- `model_id` 必须在合并后的所有 group 中全局唯一；一个模型在 `models.yaml` 有能力声明但未被任何 group 的 `models` 列表引用，会在解析时报清晰错误（缺 key 的失败必须在启动时就发生，不能拖到调用时才发现）。
- `GenerationParams`（单次调用的生成意图）与 `RetryPolicy` 不再挂在配置对象上——`ClientConfig` 删除后，重试参数直接使用各 client 构造函数自身的默认值（`max_attempts=3` 等），不再有独立的按配置定制入口（YAGNI：至今没有需要为单个 provider 定制重试策略的场景）。

## 重试/退避契约

直接借鉴 agent `RetryConfig`（指数退避 + jitter）与 `BaseClient.__call__` 的重试循环结构，简化为（此 `RetryPolicy` 即 `ClientConfig.retry` 挂载的类型，每配置一份）：

```python
class RetryPolicy(BaseModel):
    max_attempts: int = 3
    backoff_base_seconds: float = 1.0
    backoff_factor: float = 2.0
```

- 可重试类（网络超时/连接失败/`rate_limit`）→ 按退避重试直至 `max_attempts`；耗尽后返回 `ClientError(kind="network"|"rate_limit"|"timeout", attempts=max_attempts)`。
- 不可重试类（4xx 鉴权失败→`auth`、参数校验失败→`invalid_request`）→ 立即返回对应 `kind`，`attempts=1`，不重试。
- 上层按 `kind` 决策：可重试类已耗尽说明短期内难恢复（提示用户/降级/终止）；`auth`/`invalid_request` 是配置或请求本身的错，重试无意义，应直接暴露给用户修配置。
- **安全拒答不是错误**：它是成功的 `AssistantMessage(stop_reason="refusal")`，不进重试逻辑；由任务层按 `text-protocol-spec.md` 的 front-matter `task_status`（`completed:false, status:refused`）流程处理。
- 单次调用超时由 `GenerationParams.timeout_seconds` 控制，超时算可重试类（`kind="timeout"`）。

## MockClient 契约

```python
class MockClient(ModelClient):
    def __init__(self, script: list[AssistantMessage | ClientError]):
        """script 是预录制的响应序列，按调用顺序依次返回。"""
```

- 每次 `complete()` 调用按顺序弹出 `script` 中的下一项返回，不发起任何网络请求。
- `script` 耗尽后再调用 → 报测试用的明确错误（防止测试用例本身写少了步骤而被无声忽略）。
- 用于驱动 M2 单测（协议解析器的畸形输入用例）与 M3 的"mock LLM 回放测试端到端跑通"验收——录制的响应内容就是本协议 spec（`text-protocol-spec.md`）里定义的 Markdown+标记格式，不是厂商原始 API 响应结构。

## 与 agent 的差异（明确记录）

| 项                | agent                                           | ForgeAgent v1                                         | 后续安排                                                                                                                                               |
| ---------------- | ------------------------------------------------- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| 流式支持             | 支持 `stream_processor` 回调                          | v1 不做，同步阻塞                                            | **M8**：流式主要改善交互观感，非 code-as-action 环路必需。`complete()` 接口预留返回类型扩展点，届时加 `stream()` 而非改现有签名                                                |
| 多模态消息            | `TextItem`/`ImageItem` 联合类型                       | v1 纯文本，图像输入留待需要时再加                                    | **M8**：`Message.content` 现为 `str`，届时改为 `str \| list[ContentItem]` 联合类型，向后兼容纯文本                                                               |
| 原生 tool_calls 解析 | `AIMessage.tool_calls` 承载厂商原生 function-calling 结果 | v1 不做，工具调用只走文本协议（见 `text-protocol-spec.md`），契约里不留这个字段 | **M6**：随 OpenAI-compatible client 一起做（`text-protocol-spec.md` 已对齐：M6 支持 `ToolSource.OPENAI` 双通道）。届时 `AssistantMessage` 增补 tool_calls 字段，文本协议单通道仍保留 |
| 能力登记来源           | YAML 文件 + `ModelRegistry` 类，支持 alias/reload       | v1 用静态表即可，不做运行时 reload（无插件系统，不需要热更新）                  | **M8**（随插件化）：有插件系统后才需要 alias/运行时 reload；在此之前静态表足够                                                                                          |

## 待 M2 落地的单测清单

- `ClientConfig` 缺少环境变量对应的 key → 构造时报错，不在调用时才失败。
- 可重试类异常触发重试，验证退避次数与 `attempts` 计数正确，耗尽后 `kind` 正确。
- 不可重试错误（模拟 4xx）不触发重试，立即返回 `kind="auth"`/`"invalid_request"`，`attempts=1`。
- 单次调用超时 → `kind="timeout"`，且计入可重试类。
- **Capability-gating（Y1）**：给 Haiku client 传 `effort`/`thinking="on"` → 实际发出的请求里 effort 被丢弃、不带思考参数；给 Fable client 传 `thinking="off"` → 降级为"开"并记 debug 日志（不报错）；任意模型传 `thinking="auto"` → 省略 thinking 参数；`max_output_tokens=None` → 取该模型 capability 上限（Haiku=64K）。这些断言校验调用点无需判断模型名。
- `MockClient` 按序返回脚本内容；脚本耗尽后调用报错。
- 四个模型的 `ModelCapability` 登记值与 `model-capability-matrix.md` 一致（防止表格和代码漂移）。
