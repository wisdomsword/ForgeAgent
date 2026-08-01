"""Model client abstraction and a key-free MockClient.

See docs/model-client-contract.md. ModelClient is the single call surface the upper
layers depend on; concrete clients translate to/from their backend. complete() never
raises for backend/transport failures — it returns AssistantMessage or ClientError.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

from .models import (
    AssistantMessage,
    ClientError,
    GenerationParams,
    Message,
    ModelCapability,
    StreamEvent,
    StreamEventKind,
)


@dataclass(frozen=True)
class ProviderAttempt:
    attempt: int
    status: Literal["started", "success", "error", "interrupted"]
    error_kind: str | None = None


AttemptObserver = Callable[[ProviderAttempt], None]


class ModelClient(ABC):
    """Unified interface for all model clients."""

    @abstractmethod
    def complete(
        self, messages: list[Message], params: GenerationParams | None = None
    ) -> AssistantMessage | ClientError:
        """Make one completion request, returning a response or a structured error.

        Never raises for known backend/transport errors — those become ClientError.
        """

    @property
    @abstractmethod
    def capability(self) -> ModelCapability:
        """The capability declaration of the model this client serves."""

    def stream(
        self, messages: list[Message], params: GenerationParams | None = None
    ) -> Iterator[StreamEvent | ClientError]:
        """Stream one completion as incremental events, ending with a DONE event that
        carries the complete AssistantMessage (structurally identical to complete()).

        Default implementation degrades to complete(): one TEXT_DELTA with the full
        text, then DONE. Subclasses override with real streaming. Like complete(),
        errors are yielded as a ClientError (then the iterator ends), never raised.
        """
        result = self.complete(messages, params)
        if isinstance(result, ClientError):
            yield result
            return
        yield StreamEvent(kind=StreamEventKind.TEXT_DELTA, text=result.content)
        yield StreamEvent(kind=StreamEventKind.DONE, message=result)

    def close(self) -> None:
        """Release provider resources owned by this client.

        The base implementation is intentionally a no-op so lightweight test
        doubles and clients backed by injected transports need no lifecycle code.
        """

    def set_attempt_observer(self, observer: AttemptObserver | None) -> AttemptObserver | None:
        previous = getattr(self, "_attempt_observer", None)
        self._attempt_observer = observer
        return previous

    def _notify_attempt(self, event: ProviderAttempt) -> None:
        observer = getattr(self, "_attempt_observer", None)
        if observer is not None:
            try:
                observer(event)
            except Exception:  # observer is diagnostic only
                pass


class MockScriptExhausted(RuntimeError):
    """Raised when a MockClient is called more times than its script provides.

    This is a test-authoring error (the test supplied fewer responses than the run
    consumed) and must surface loudly rather than be silently ignored.
    """


class MockClient(ModelClient):
    """A client that replays a pre-recorded response sequence. No key, no network.

    Drives key-free end-to-end tests (protocol parser, Task/Step loop). Each
    complete() call pops the next scripted item in order.
    """

    def __init__(
        self,
        script: list[AssistantMessage | ClientError],
        capability: ModelCapability | None = None,
    ):
        self._script = list(script)
        self._index = 0
        # A minimal default capability so MockClient works without a real model id.
        self._capability = capability or ModelCapability(
            model_id="mock",
            context_window=1_000_000,
            max_output_tokens=128_000,
            supports_thinking=True,
            thinking_always_on=False,
            supports_effort=True,
            client_kind="anthropic",
        )

    def complete(
        self, messages: list[Message], params: GenerationParams | None = None
    ) -> AssistantMessage | ClientError:
        if self._index >= len(self._script):
            raise MockScriptExhausted(
                f"MockClient script exhausted: {len(self._script)} response(s) provided, "
                f"but complete() was called {self._index + 1} time(s)."
            )
        item = self._script[self._index]
        self._index += 1
        return item

    @property
    def capability(self) -> ModelCapability:
        return self._capability

    @property
    def calls_made(self) -> int:
        """Number of complete() calls served so far (useful for test assertions)."""
        return self._index
