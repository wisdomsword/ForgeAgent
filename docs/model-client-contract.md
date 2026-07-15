# Model Client Contract

This is the current vendor-neutral boundary used by `Task` and `Step`. Provider
request and response shapes stay inside concrete clients.

## Types

```python
class GenerationParams(BaseModel):
    max_output_tokens: int | None = None
    temperature: float | None = None
    thinking: Literal["on", "off", "auto"] = "auto"
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    timeout_seconds: float = 120.0

class TextItem(BaseModel):
    type: Literal["text"] = "text"
    text: str

class ImageItem(BaseModel):
    type: Literal["image"] = "image"
    media_type: Literal["image/jpeg", "image/png", "image/gif", "image/webp"]
    data: str                         # base64 encoded bytes

ContentItem = Annotated[TextItem | ImageItem, Field(discriminator="type")]

class Message(BaseModel):
    role: Role                        # system | user | assistant
    content: str | list[ContentItem]

class NativeToolCall(BaseModel):
    id: str
    name: str
    arguments: str                    # raw JSON string

class AssistantMessage(Message):
    role: Literal[Role.ASSISTANT] = Role.ASSISTANT
    usage: TokenUsage
    stop_reason: str                  # provider value, passed through
    tool_calls: list[NativeToolCall] = Field(default_factory=list)

class ClientError(BaseModel):
    message: str
    kind: Literal["network", "auth", "rate_limit", "invalid_request", "timeout", "unknown"]
    attempts: int = Field(ge=1)

class ModelCapability(BaseModel):
    model_id: str
    context_window: int
    max_output_tokens: int
    supports_thinking: bool
    thinking_always_on: bool
    supports_effort: bool
    supports_images: bool = False
    client_kind: Literal["anthropic", "openai_compatible"]
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"

class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0

class StreamEvent(BaseModel):
    kind: Literal["text_delta", "thinking_delta", "done"]
    text: str = ""
    message: AssistantMessage | None = None
```

`AssistantMessage` is a successful response even when `stop_reason` is
`refusal` or `content_filter`; refusal is not a `ClientError`. Native tool-call
arguments remain a JSON string until `protocol.parse()` validates them against
the active tool registry.

`ModelClient.complete(messages, params=None)` returns `AssistantMessage | ClientError`.
Known backend and transport failures are returned, not raised. `stream()` returns
an iterator of `StreamEvent | ClientError`; its terminal event is exactly one
`DONE` carrying the complete `AssistantMessage`. The default implementation calls
`complete()`, yields one full `TEXT_DELTA`, then `DONE`. A stream error yields one
`ClientError` and ends without `DONE`.

`Step` forwards deltas only for display. Only `DONE.message` enters parsing and
conversation history. A stream that ends before the provider terminal event is a
`ClientError`. A mid-stream failure is not retried, and partial protocol text is
discarded. OpenAI-compatible native tool-call fragments are accumulated; after the
first such fragment, text/thinking deltas are not forwarded, and the calls appear
on the final `DONE` message.

## Capability gating

Callers express intent and never branch on a model name.

- `max_output_tokens=None` becomes `capability.max_output_tokens`.
- `thinking="auto"` omits an explicit thinking parameter and uses the provider default.
- `thinking="on"` is sent only when `supports_thinking` is true and
  `thinking_always_on` is false. Anthropic uses `thinking: {type: "adaptive"}`;
  OpenAI-compatible uses `extra_body: {thinking: {type: "enabled"}}`.
- `thinking="off"` is best effort. Unsupported or always-on models cannot be
  forced to change; no error is raised.
- `effort` is dropped when `supports_effort` is false. Anthropic sends supported
  effort under `output_config`; OpenAI-compatible sends `reasoning_effort`.
- An image-bearing message sent to a model with `supports_images=false` returns
  `ClientError(kind="invalid_request", attempts=1)`; the image is never discarded.
- Anthropic moves system messages to its top-level `system` field. OpenAI-compatible
  clients keep them in the `messages` array.
- `max_tokens_param` records the OpenAI-compatible output-limit spelling. Anthropic
  always uses `max_tokens`.

## Completion, retry, and parsing

Each concrete client builds its provider request and calls the shared retry loop.
The default maximum is three attempts, with delays
`backoff_base_seconds * backoff_factor ** (attempt - 1)`, default base `1.0` and
factor `2.0`.

| Failure | Kind | Retry | Result |
| --- | --- | --- | --- |
| timeout/connection/server failure | `timeout` or `network` | yes | retry until exhausted |
| rate limiting | `rate_limit` | yes | retry until exhausted |
| authentication/permission | `auth` | no | immediate error, attempts 1 |
| invalid request | `invalid_request` | no | immediate error, attempts 1 |
| unclassified exception | `unknown` | no | immediate error, attempts 1 |

After retries, `attempts` is the number of calls actually made. A successful
transport response that cannot be parsed is a non-retried
`ClientError(kind="invalid_request", attempts=<that attempt>)`; retrying malformed
JSON or an HTML response does not repair it. A refusal is a normal assistant result
and is outside retry handling.

## Registry and routing

`src/forgeagent/res/models.yaml` declares model capability data and aliases;
`src/forgeagent/res/config.yaml` declares provider groups. Built-in configuration
contains no literal API key. The built-in groups currently route exactly as follows:

| Group | Key env | Base URL env | Models |
| --- | --- | --- | --- |
| `anthropic` | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL` | `claude-sonnet-5`, `claude-opus-4-8`, `claude-haiku-4-5`, `claude-fable-5` |
| `openai` | `OPENAI_API_KEY` | `OPENAI_BASE_URL` | `gpt-5.5`, `gpt-5.4-mini` |
| `llm` | `LLM_API_KEY` | `LLM_BASE_URL` | `glm-5.2`, `deepseek-v4-flash` |

The model id (or alias) resolves to one and only one group. Other groups' env
variables are ignored. Duplicate group membership, unknown models, alias
collisions, and capability entries not referenced by a group are registry errors.
The optional user files `~/.forgeagent/models.yaml` and
`~/.forgeagent/config.yaml` are merged over the built-ins. A user config may add
literal `api_key` or `base_url`; a literal value wins over its corresponding
`*_env` value. Literal keys are never placed in the shipped files.

Model discovery is not a registry-wide routing mechanism. The Anthropic concrete
client may resolve a logical model id to a dated id exposed by its configured
endpoint, once per client instance, with the result cached per base URL. The
OpenAI-compatible client does not perform model discovery; its configured model id
is used as-is.

## MockClient

`MockClient(script, capability=None)` copies a list of `AssistantMessage | ClientError`
and returns entries strictly in order on successive `complete()` calls. It performs
no network access and needs no key. `calls_made` reports served entries. When the
script is exhausted it raises `MockScriptExhausted`, including the supplied length
and attempted call number; this is a test-authoring error and must not be silently
converted into a model response.
