"""Unit tests for multimodal messages (M9 Phase 2).

Covers the ContentItem discriminated union, both clients' wire-shape translation,
the supports_images capability gate, str-only backward compatibility, and
image_input.py's detection/loading logic. No real network/key.
"""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from forgeagent.anthropic_client import AnthropicClient
from forgeagent.image_input import MAX_IMAGE_BYTES, detect_media_type, load_images
from forgeagent.models import (
    ClientError,
    ImageItem,
    Message,
    ModelCapability,
    Role,
    TextItem,
)
from forgeagent.openai_compatible_client import OpenAICompatibleClient

# 1x1 transparent PNG, valid magic number + minimal well-formed bytes.
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 20
_GIF_BYTES = b"GIF89a" + b"\x00" * 20
_WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 20


def _cap(client_kind: str, supports_images: bool) -> ModelCapability:
    return ModelCapability(
        model_id=f"test-{client_kind}",
        context_window=100_000,
        max_output_tokens=8_000,
        supports_thinking=False,
        thinking_always_on=False,
        supports_effort=False,
        supports_images=supports_images,
        client_kind=client_kind,
    )


# --- ContentItem discriminated union -----------------------------------------


def test_message_content_stays_plain_string_by_default():
    msg = Message(role=Role.USER, content="hello")
    assert msg.content == "hello"


def test_message_content_accepts_content_item_list():
    msg = Message(
        role=Role.USER,
        content=[
            TextItem(text="what is this?"),
            ImageItem(media_type="image/png", data="abc123"),
        ],
    )
    assert isinstance(msg.content, list)
    assert msg.content[0].type == "text"
    assert msg.content[1].type == "image"


def test_content_item_discriminator_rejects_unknown_type():
    with pytest.raises(ValidationError):
        Message(role=Role.USER, content=[{"type": "audio", "data": "x"}])


# --- Anthropic translation ----------------------------------------------------


def test_anthropic_render_content_passes_through_plain_string():
    client = AnthropicClient(capability=_cap("anthropic", True), api_key="k")
    system, turns = _split_system_via_build_request(client, "hello")
    assert turns[0]["content"] == "hello"


def test_anthropic_render_content_builds_image_blocks():
    client = AnthropicClient(capability=_cap("anthropic", True), api_key="k")
    msgs = [
        Message(
            role=Role.USER,
            content=[
                TextItem(text="describe"),
                ImageItem(media_type="image/png", data="b64data"),
            ],
        )
    ]
    req = client.build_request(msgs, _params())
    blocks = req["messages"][0]["content"]
    assert blocks == [
        {"type": "text", "text": "describe"},
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "b64data"},
        },
    ]


def test_anthropic_rejects_image_when_capability_lacks_support():
    client = AnthropicClient(
        capability=_cap("anthropic", False),
        api_key="k",
        transport=lambda req, t: pytest.fail("transport must not be called"),
    )
    msgs = [Message(role=Role.USER, content=[ImageItem(media_type="image/png", data="x")])]
    result = client.complete(msgs)
    assert isinstance(result, ClientError)
    assert result.kind == "invalid_request"


# --- OpenAI-compatible translation -------------------------------------------


def test_openai_render_content_passes_through_plain_string():
    client = OpenAICompatibleClient(capability=_cap("openai_compatible", True), api_key="k")
    req = client.build_request([Message(role=Role.USER, content="hello")], _params())
    assert req["messages"][0]["content"] == "hello"


def test_openai_render_content_builds_image_url_data_uri():
    client = OpenAICompatibleClient(capability=_cap("openai_compatible", True), api_key="k")
    msgs = [
        Message(
            role=Role.USER,
            content=[
                TextItem(text="describe"),
                ImageItem(media_type="image/jpeg", data="b64data"),
            ],
        )
    ]
    req = client.build_request(msgs, _params())
    parts = req["messages"][0]["content"]
    assert parts == [
        {"type": "text", "text": "describe"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,b64data"}},
    ]


def test_openai_rejects_image_when_capability_lacks_support():
    client = OpenAICompatibleClient(
        capability=_cap("openai_compatible", False),
        api_key="k",
        transport=lambda req, t: pytest.fail("transport must not be called"),
    )
    msgs = [Message(role=Role.USER, content=[ImageItem(media_type="image/png", data="x")])]
    result = client.complete(msgs)
    assert isinstance(result, ClientError)
    assert result.kind == "invalid_request"


def test_openai_accepts_image_when_capability_supports_it():
    from types import SimpleNamespace

    def transport(req, t):
        message = SimpleNamespace(content="ok", tool_calls=None)
        choice = SimpleNamespace(message=message, finish_reason="stop")
        return SimpleNamespace(
            choices=[choice],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, prompt_tokens_details=None),
        )

    client = OpenAICompatibleClient(
        capability=_cap("openai_compatible", True), api_key="k", transport=transport
    )
    msgs = [Message(role=Role.USER, content=[ImageItem(media_type="image/png", data="x")])]
    result = client.complete(msgs)
    assert not isinstance(result, ClientError)


# --- image_input.py: detect_media_type ---------------------------------------


def test_detect_media_type_png():
    assert detect_media_type(_PNG_BYTES) == "image/png"


def test_detect_media_type_jpeg():
    assert detect_media_type(_JPEG_BYTES) == "image/jpeg"


def test_detect_media_type_gif():
    assert detect_media_type(_GIF_BYTES) == "image/gif"


def test_detect_media_type_webp():
    assert detect_media_type(_WEBP_BYTES) == "image/webp"


def test_detect_media_type_unrecognized_returns_none():
    assert detect_media_type(b"not an image") is None


# --- image_input.py: load_images ----------------------------------------------


def test_load_images_single_file(tmp_path):
    f = tmp_path / "pic.png"
    f.write_bytes(_PNG_BYTES)
    images = load_images(str(f))
    assert len(images) == 1
    assert images[0].media_type == "image/png"
    assert base64.b64decode(images[0].data) == _PNG_BYTES


def test_load_images_directory_collects_sorted(tmp_path):
    (tmp_path / "b.png").write_bytes(_PNG_BYTES)
    (tmp_path / "a.jpg").write_bytes(_JPEG_BYTES)
    images = load_images(str(tmp_path))
    assert len(images) == 2
    # sorted by filename: a.jpg before b.png
    assert images[0].media_type == "image/jpeg"
    assert images[1].media_type == "image/png"


def test_load_images_directory_skips_unrecognized_files(tmp_path):
    (tmp_path / "readme.txt").write_bytes(b"not an image")
    (tmp_path / "pic.png").write_bytes(_PNG_BYTES)
    images = load_images(str(tmp_path))
    assert len(images) == 1
    assert images[0].media_type == "image/png"


def test_load_images_explicit_bad_file_raises(tmp_path):
    f = tmp_path / "readme.txt"
    f.write_bytes(b"not an image")
    with pytest.raises(ValueError):
        load_images(str(f))


def test_load_images_missing_path_raises():
    with pytest.raises(ValueError):
        load_images("/no/such/path/anywhere")


def test_load_images_per_image_size_cap(tmp_path):
    f = tmp_path / "big.png"
    # magic number + padding past the 5MB cap
    f.write_bytes(_PNG_BYTES + b"\x00" * (5 * 1024 * 1024))
    with pytest.raises(ValueError):
        load_images(str(f))


def test_load_images_rechecks_size_after_read_when_file_grows(tmp_path, monkeypatch):
    image = tmp_path / "grown.png"
    image.write_bytes(_PNG_BYTES + b"\x00" * (5 * 1024 * 1024))
    original_stat = Path.stat

    def report_smaller_size(path: Path, *args, **kwargs):
        if path == image:
            original_result = original_stat(path, *args, **kwargs)
            return SimpleNamespace(st_size=0, st_mode=original_result.st_mode)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", report_smaller_size)

    with pytest.raises(ValueError, match=r"grown\.png: image is .* exceeds"):
        load_images(str(image))


def test_load_images_bounds_read_when_file_grows_after_stat(tmp_path, monkeypatch):
    image = tmp_path / "grown.png"
    image.write_bytes(_PNG_BYTES + b"\\x00" * (5 * 1024 * 1024))
    original_stat = Path.stat
    original_open = Path.open
    requested_sizes: list[int] = []

    def report_smaller_size(path: Path, *args, **kwargs):
        if path == image:
            result = original_stat(path, *args, **kwargs)
            return SimpleNamespace(st_size=0, st_mode=result.st_mode)
        return original_stat(path, *args, **kwargs)

    def record_read_bound(path: Path, *args, **kwargs):
        image_file = original_open(path, *args, **kwargs)
        original_read = image_file.read

        def read(size=-1):
            requested_sizes.append(size)
            return original_read(size)

        monkeypatch.setattr(image_file, "read", read)
        return image_file

    monkeypatch.setattr(Path, "stat", report_smaller_size)
    monkeypatch.setattr(Path, "open", record_read_bound)

    with pytest.raises(ValueError, match=r"grown\.png: image is at least .* exceeds"):
        load_images(str(image))

    assert requested_sizes == [MAX_IMAGE_BYTES + 1]


def test_load_images_per_request_count_cap(tmp_path, monkeypatch):
    for i in range(25):
        (tmp_path / f"img{i:02d}.png").write_bytes(_PNG_BYTES)
    (tmp_path / "img15.txt").write_text("not an image")
    original_open = Path.open
    opened = []

    def record_open(path, *args, **kwargs):
        opened.append(path.name)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", record_open)

    with pytest.raises(ValueError, match="21 images exceeds the 20-image per-request limit"):
        load_images(str(tmp_path))

    assert opened == sorted([f"img{i:02d}.png" for i in range(21)] + ["img15.txt"])


def test_load_images_directory_rejects_recognized_oversized_file(tmp_path):
    (tmp_path / "small.png").write_bytes(_PNG_BYTES)
    (tmp_path / "big.png").write_bytes(_PNG_BYTES + b"\x00" * (5 * 1024 * 1024))
    with pytest.raises(ValueError, match=r"big\.png: image is .* exceeds"):
        load_images(str(tmp_path))


def test_load_images_directory_skips_oversized_non_image_without_full_read(tmp_path, monkeypatch):
    small = tmp_path / "small.png"
    large_non_image = tmp_path / "large.bin"
    small.write_bytes(_PNG_BYTES)
    large_non_image.write_bytes(b"not an image" + b"\x00" * (5 * 1024 * 1024))

    original_read_bytes = Path.read_bytes

    def fail_if_large_non_image_is_fully_read(path: Path) -> bytes:
        if path == large_non_image:
            raise AssertionError("oversized non-image must not be fully read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_if_large_non_image_is_fully_read)

    images = load_images(str(tmp_path))

    assert len(images) == 1
    assert images[0].media_type == "image/png"


# --- helpers -------------------------------------------------------------------


def _params():
    from forgeagent.models import GenerationParams

    return GenerationParams()


def _split_system_via_build_request(client: AnthropicClient, content: str):
    req = client.build_request([Message(role=Role.USER, content=content)], _params())
    return req.get("system"), req["messages"]
