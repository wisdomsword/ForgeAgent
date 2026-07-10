"""The `utils` runtime object injected into executed code.

See docs/threat-model.md (cross-block state) and ACTION_PLAN §二 (borrow agent's
runtime.py state mechanism, simplified). Generated code calls `utils.set_state(...)`
to report results structured, and `utils.get_state(...)` to read state a prior block
saved. State is a plain dict held by the runtime; the executor backend decides how it
persists across blocks (trusted: shared in-process; restricted: serialized by the main
process — see M4).
"""

from __future__ import annotations

from typing import Any


class Runtime:
    """The `utils` object exposed to executed code blocks.

    One Runtime instance is shared across the blocks of a single task, so state set by
    one block is visible to later blocks. Kept intentionally small — only what v1 needs.
    """

    def __init__(self, state: dict[str, Any] | None = None):
        self._state: dict[str, Any] = state if state is not None else {}
        self._result: dict[str, Any] | None = None

    def set_state(self, key: str, value: Any) -> None:
        """Save a value under `key` for later blocks to read via get_state."""
        self._state[key] = value

    def get_state(self, key: str, default: Any = None) -> Any:
        """Read a value a prior block saved; return `default` if absent."""
        return self._state.get(key, default)

    def has_state(self, key: str) -> bool:
        """Whether `key` has been set."""
        return key in self._state

    def set_result(self, success: bool, **fields: Any) -> None:
        """Report a structured task/block result: success plus arbitrary fields.

        Makes execution outcomes machine-readable for the feedback loop rather than
        relying on parsing stdout.
        """
        self._result = {"success": success, **fields}

    @property
    def result(self) -> dict[str, Any] | None:
        """The last structured result reported via set_result, or None."""
        return self._result

    @property
    def state(self) -> dict[str, Any]:
        """The live state dict (the executor backend reads/persists this)."""
        return self._state
