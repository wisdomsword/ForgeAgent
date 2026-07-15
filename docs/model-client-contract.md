# Model Client Contract

This document describes the current vendor-neutral model-client boundary. Upper layers use only `ModelClient`, `Message`, `GenerationParams`, and the response types; provider-specific request and response shapes remain inside the concrete client.

## Requests and results

```python
class ModelClient(ABC):
    def complete(
        self, messages: list[Message], params: GenerationParams | None = None
    ) -> AssistantMessage | ClientError: ...

    def stream(
        self, messages: list[Message], params: GenerationParams | None = None
    ) -> Iterator[StreamEvent | ClientError]: ...
```

- `complete()` performs one synchronous request. Known backend and transport failures are returned as `ClientError`; callers do not need a provider-specific exception path.
- `AssistantMessage` is a successful response, including a provider refusal (`stop_reason="refusal"`); refusal is not a `ClientError`.
- `ClientError.kind` is one of `network`, `auth`, `rate_limit`, `invalid_request`, `timeout`, or `unknown`. `attempts` records completed attempts.
- `GenerationParams` expresses portable intent: output limit, temperature, `thinking` (`on`, `off`, `auto`), `effort`, and timeout. Clients capability-gate unsupported parameters. In particular, `thinking="off"` is a preference, not a guarantee for an always-thinking model.

## Streaming

`stream()` yields zero or more `TEXT_DELTA` and `THINKING_DELTA` events, then exactly one `DONE` event carrying the full `AssistantMessage`. The `DONE` message is structurally the same result shape used by `complete()`.

The base implementation degrades to `complete()`: it emits one full-text `TEXT_DELTA` followed by `DONE`. Concrete Anthropic and OpenAI-compatible clients provide real streaming. A known streaming failure yields one `ClientError` and ends the iterator; a stream that ends before a provider finish reason is also a `ClientError`, not a partial `DONE` response.

`Step` uses `complete()` unless its caller supplies a stream-display callback. In streaming mode it forwards text and thinking deltas for display, but only the terminal `DONE` message enters protocol parsing and conversation history. Native OpenAI-compatible tool-call fragments are accumulated for `DONE`; once such fragments appear, subsequent deltas are not forwarded as text.

## Message content and images

`Message.content` is either a plain string or an ordered `list[ContentItem]`:

```python
class TextItem(BaseModel):
    type: Literal["text"] = "text"
    text: str

class ImageItem(BaseModel):
    type: Literal["image"] = "image"
    media_type: Literal["image/jpeg", "image/png", "image/gif", "image/webp"]
    data: str  # base64 bytes
```

Plain-text callers remain compatible. A client rejects an image request with `ClientError(kind="invalid_request")` when its `ModelCapability.supports_images` is false; it never silently discards images. Concrete clients translate image items to their provider wire format.

## Usage accounting

`TokenUsage` reports `input_tokens`, `output_tokens`, `cached_tokens`, and `reasoning_tokens`.

- Anthropic cache creation and cache-read input tokens are combined into `cached_tokens`; Anthropic bills thinking within `output_tokens`, so its separate `reasoning_tokens` value is `0`.
- OpenAI-compatible clients read `prompt_tokens_details.cached_tokens` when present. For reasoning, they take the greater of the standard nested and non-standard top-level reasoning-token values because compatible providers place authoritative data differently.
- Missing usage fields are represented as zero. ForgeAgent does not estimate token counts.

## Provider translation

The caller always supplies the same `list[Message]`. Anthropic clients separate system messages into their provider's top-level system field; OpenAI-compatible clients retain system messages in the messages array. Capability declarations select image eligibility, thinking and effort parameters, output-token parameter spelling, and client implementation without upper-layer model-name branching.

`MockClient` replays scripted `AssistantMessage` or `ClientError` values without keys or network access. Exhausting its script is a test-authoring error and raises `MockScriptExhausted`.
