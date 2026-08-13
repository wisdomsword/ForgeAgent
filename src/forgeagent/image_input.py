"""Load images from a path (file or directory) into ImageItem list.

Shared by cli.py's `--image` flag and the REPL's `/image` slash command
(docs/m9-streaming-multimodal-commands.md §3.4). Media-type detection is
magic-number sniffing rather than the deprecated stdlib `imghdr`.
"""

from __future__ import annotations

import base64
from pathlib import Path

from .models import ImageItem

__all__ = ["detect_media_type", "load_images", "MAX_IMAGE_BYTES", "MAX_IMAGES_PER_REQUEST"]

# Anthropic API limits (docs/m9 §3.4): 5MB per image, 20 images per request.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES_PER_REQUEST = 20

_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
)
_HEADER_BYTES = 12


class _UnrecognizedImageError(ValueError):
    """A file is not one of the image formats accepted by this input."""


def detect_media_type(data: bytes) -> str | None:
    """Sniff the image media type from its leading bytes, or None if unrecognized."""
    for signature, media_type in _SIGNATURES:
        if data.startswith(signature):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _load_one(path: Path) -> ImageItem:
    size = path.stat().st_size
    if size > MAX_IMAGE_BYTES:
        with path.open("rb") as image_file:
            header = image_file.read(_HEADER_BYTES)
        if detect_media_type(header) is None:
            raise _UnrecognizedImageError(f"{path}: not a recognized image (jpeg/png/gif/webp)")
        raise ValueError(
            f"{path}: image is {size} bytes, exceeds the {MAX_IMAGE_BYTES}-byte per-image limit"
        )

    # The file can grow after stat(). Keep that race bounded rather than turning it
    # into an unbounded read of a now-oversized path.
    with path.open("rb") as image_file:
        data = image_file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        if detect_media_type(data[:_HEADER_BYTES]) is None:
            raise _UnrecognizedImageError(f"{path}: not a recognized image (jpeg/png/gif/webp)")
        raise ValueError(
            f"{path}: image is at least {len(data)} bytes, exceeds the {MAX_IMAGE_BYTES}-byte "
            "per-image limit"
        )
    media_type = detect_media_type(data)
    if media_type is None:
        raise _UnrecognizedImageError(f"{path}: not a recognized image (jpeg/png/gif/webp)")
    return ImageItem(media_type=media_type, data=base64.b64encode(data).decode("ascii"))


def load_images(path: str) -> list[ImageItem]:
    """Load one image file, or every recognized image in a directory (non-recursive).

    A directly-named file that isn't a recognized image raises ValueError. A file
    encountered while scanning a directory is silently skipped if unrecognized (mixed
    directories are expected). Files are sorted by name for deterministic ordering.
    """
    p = Path(path)
    if not p.exists():
        raise ValueError(f"{path}: no such file or directory")

    if p.is_file():
        images = [_load_one(p)]
    else:
        items: list[ImageItem] = []
        for entry in sorted(p.iterdir(), key=lambda e: e.name):
            if not entry.is_file():
                continue
            try:
                items.append(_load_one(entry))
            except _UnrecognizedImageError:
                continue
        images = items

    if len(images) > MAX_IMAGES_PER_REQUEST:
        raise ValueError(
            f"{path}: {len(images)} images exceeds the {MAX_IMAGES_PER_REQUEST}-image "
            "per-request limit; narrow the selection"
        )
    return images
