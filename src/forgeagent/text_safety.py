"""Shared validation for bounded model- and audit-facing text."""

from __future__ import annotations

import unicodedata
from typing import Any


def safe_text(value: Any, *, field: str, maximum: int, allow_empty: bool = False) -> str:
    """Validate bounded text while preserving the caller's empty-value policy."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if len(value) > maximum:
        raise ValueError(f"{field} is too long")
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for character in value
    ):
        raise ValueError(f"{field} contains unsafe characters")
    normalized = value if allow_empty else value.strip()
    if not allow_empty and not normalized:
        raise ValueError(f"{field} must not be blank")
    return normalized
