"""Real worker regressions for the release audit's execution/state boundaries."""

import os
import subprocess
import sys

import pytest

from forgeagent._sandbox_worker import _BoundedCapture
from forgeagent.executor import ContainerBackend, RestrictedBackend, _parse_worker_frame
from forgeagent.external_actions import ExternalActionReceiptStore, ReceiptError
from forgeagent.runtime import Runtime


def test_restricted_relative_paths_use_project_directory(tmp_path):
    result = RestrictedBackend(allowed_root=str(tmp_path)).execute(
        "from pathlib import Path; Path('result.txt').write_text('ok')", Runtime()
    )
    assert result.success, result.error
    assert (tmp_path / "result.txt").read_text() == "ok"


def test_worker_capture_is_bounded_in_memory():
    capture = _BoundedCapture(None, 32)
    try:
        assert capture.write("x" * 100_000) == 100_000
        assert len(capture.getvalue()) < 100
        assert "truncated" in capture.getvalue()
    finally:
        capture.close()


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_restricted_output_is_bounded_before_parent_feedback(tmp_path, stream):
    result = RestrictedBackend(allowed_root=str(tmp_path)).execute(
        f"import sys; sys.{stream}.write('x' * (2 * 1024 * 1024))", Runtime()
    )
    assert result.success, result.error
    assert len(getattr(result, stream)) < 9 * 1024
    assert "truncated" in getattr(result, stream)


def test_oversized_state_fails_without_replacing_previous_state(tmp_path):
    runtime = Runtime()
    backend = RestrictedBackend(allowed_root=str(tmp_path))
    assert backend.execute("utils.set_state('old', 42)", runtime).success
    result = backend.execute("utils.set_state('large', 'x' * (2 * 1024 * 1024))", runtime)
    assert not result.success
    assert "limit" in result.error or "large" in result.error
    assert runtime.get_state("old") == 42
    assert runtime.get_state("large") is None


def _unknown_receipt(root):
    store = ExternalActionReceiptStore(str(root), task_id="audit", loop_id="a" * 32)
    receipt = store.create_prepared(server_label="demo", tool_label="send", request_digest="b" * 64)
    receipt = store.mark_dispatched(receipt.action_id, receipt.revision)
    receipt = store.mark_unknown(receipt.action_id, receipt.revision, "result_unknown")
    return store, receipt


@pytest.mark.parametrize("target", ["receipt", "directory", "parent"])
def test_restricted_cannot_delete_or_move_receipt_authority(tmp_path, target):
    store, receipt = _unknown_receipt(tmp_path)
    try:
        directory = tmp_path / ".forgeagent" / "receipts"
        if target == "receipt":
            path = directory / (receipt.action_id + ".json")
            code = f"from pathlib import Path; Path({str(path)!r}).unlink()"
        else:
            source = directory if target == "directory" else directory.parent
            code = (
                f"from pathlib import Path; Path({str(source)!r})"
                f".rename({str(tmp_path / 'moved')!r})"
            )
        result = RestrictedBackend(allowed_root=str(tmp_path)).execute(code, Runtime())
        assert not result.success
        assert len(store.list_pending()) == 1
    finally:
        store.close()


def test_missing_registered_receipt_fails_closed_after_restart(tmp_path):
    store, receipt = _unknown_receipt(tmp_path)
    store.close()
    path = tmp_path / ".forgeagent" / "receipts" / f"{receipt.action_id}.json"
    path.unlink()  # Simulate storage loss outside the task boundary.
    with pytest.raises(ReceiptError):
        reopened = ExternalActionReceiptStore(str(tmp_path))
        try:
            reopened.list_pending()
        finally:
            reopened.close()


def test_container_command_protects_receipts_with_read_only_mount(tmp_path, monkeypatch):
    monkeypatch.setattr("forgeagent.executor._verify_container_runtime", lambda *_: None)
    backend = ContainerBackend(allowed_root=str(tmp_path))
    try:
        command = backend._run_command("audit")
        root = tmp_path / ".forgeagent"
        assert f"{root}:{root}:ro" in command
    finally:
        backend.close()


def test_relative_descriptor_open_cannot_truncate_receipt(tmp_path):
    store, receipt = _unknown_receipt(tmp_path)
    try:
        code = (
            "import os\n"
            "root = os.open('.', os.O_RDONLY)\n"
            "parent = os.open('.forgeagent', os.O_RDONLY, dir_fd=root)\n"
            "receipts = os.open('receipts', os.O_RDONLY, dir_fd=parent)\n"
            f"os.open('{receipt.action_id}.json', os.O_WRONLY | os.O_TRUNC, dir_fd=receipts)\n"
        )
        result = RestrictedBackend(allowed_root=str(tmp_path)).execute(code, Runtime())
        assert not result.success
        assert store.load(receipt.action_id).phase == "unknown"
    finally:
        store.close()


def test_valid_legacy_receipts_are_adopted_without_changes(tmp_path):
    store, receipt = _unknown_receipt(tmp_path)
    store.close()
    directory = tmp_path / ".forgeagent" / "receipts"
    record = directory / f"{receipt.action_id}.json"
    original = record.read_bytes()
    (directory / ".catalog").unlink()  # Legacy stores predate the catalog.
    (directory / ".initialized").unlink(missing_ok=True)
    reopened = ExternalActionReceiptStore(str(tmp_path))
    try:
        assert reopened.list_pending()[0].phase == "unknown"
        assert record.read_bytes() == original
    finally:
        reopened.close()


def test_missing_registered_receipt_blocks_new_actions(tmp_path):
    store, receipt = _unknown_receipt(tmp_path)
    try:
        (tmp_path / ".forgeagent" / "receipts" / f"{receipt.action_id}.json").unlink()
        with pytest.raises(ReceiptError):
            store.create_prepared(server_label="demo", tool_label="send", request_digest="b" * 64)
    finally:
        store.close()


def test_full_disk_backend_keeps_project_cwd_and_receipt_protection(tmp_path):
    store, receipt = _unknown_receipt(tmp_path)
    try:
        backend = RestrictedBackend(allowed_root="/", working_directory=str(tmp_path))
        result = backend.execute("open('result.txt', 'w').write('ok')", Runtime())
        assert result.success, result.error
        assert (tmp_path / "result.txt").read_text() == "ok"
        result = backend.execute(
            f"open('.forgeagent/receipts/{receipt.action_id}.json', 'w').write('changed')",
            Runtime(),
        )
        assert not result.success
        assert store.load(receipt.action_id).phase == "unknown"
    finally:
        store.close()


def test_direct_worker_pipe_flood_is_bounded(tmp_path):
    result = RestrictedBackend(allowed_root=str(tmp_path)).execute(
        "import sys; sys.__stdout__.write('x' * (2 * 1024 * 1024))", Runtime()
    )
    assert not result.success
    assert "size limit" in result.error
    assert len(result.stdout) < 9 * 1024


def test_full_disk_descriptor_mutation_cannot_move_receipts(tmp_path):
    store, receipt = _unknown_receipt(tmp_path)
    try:
        code = (
            "import os\n"
            "parent = os.open('.forgeagent', os.O_RDONLY)\n"
            "os.rename('receipts', 'moved', src_dir_fd=parent, dst_dir_fd=parent)\n"
        )
        result = RestrictedBackend(allowed_root="/", working_directory=str(tmp_path)).execute(
            code, Runtime()
        )
        assert not result.success
        assert store.load(receipt.action_id).phase == "unknown"
    finally:
        store.close()


def test_descriptor_permission_change_cannot_disable_receipt_parent(tmp_path):
    store, receipt = _unknown_receipt(tmp_path)
    metadata = tmp_path / ".forgeagent"
    original_mode = metadata.stat().st_mode & 0o777
    try:
        result = RestrictedBackend(allowed_root=str(tmp_path)).execute(
            "import os; fd = os.open('.forgeagent', os.O_RDONLY); os.fchmod(fd, 0o700)",
            Runtime(),
        )
        assert not result.success
        assert metadata.stat().st_mode & 0o777 == original_mode
        assert store.load(receipt.action_id).phase == "unknown"
    finally:
        store.close()


def test_recovery_capture_rejects_fifo_without_blocking(tmp_path):
    path = tmp_path / "capture"
    os.mkfifo(path)
    code = (
        "import sys; from forgeagent.executor import _read_worker_capture_paths; "
        "assert _read_worker_capture_paths({'stdout':sys.argv[1]}) == ('','')"
    )
    subprocess.run([sys.executable, "-c", code, str(path)], timeout=2, check=True)


def test_missing_catalog_does_not_reset_initialized_store(tmp_path):
    store, receipt = _unknown_receipt(tmp_path)
    store.close()
    directory = tmp_path / ".forgeagent" / "receipts"
    (directory / f"{receipt.action_id}.json").unlink()
    (directory / ".catalog").unlink()
    with pytest.raises(ReceiptError):
        ExternalActionReceiptStore(str(tmp_path))


def test_failed_catalog_update_preserves_recoverable_prepared_receipt(tmp_path, monkeypatch):
    store = ExternalActionReceiptStore(str(tmp_path), task_id="audit")
    original = store._write_catalog

    def fail_write(_identifiers):
        raise ReceiptError("injected catalog write failure")

    monkeypatch.setattr(store, "_write_catalog", fail_write)
    with pytest.raises(ReceiptError):
        store.create_prepared(server_label="demo", tool_label="send", request_digest="b" * 64)
    monkeypatch.setattr(store, "_write_catalog", original)
    try:
        pending = store.list_pending()
        assert len(pending) == 1
        assert pending[0].phase == "prepared" and pending[0].revision == 0
    finally:
        store.close()


def test_capture_keeps_a_prefix_at_multibyte_truncation():
    capture = _BoundedCapture(None, 3)
    try:
        capture.write("xx☺")
        capture.write("1")
        assert capture.getvalue() == "xx\n... output truncated ...\n"
    finally:
        capture.close()


@pytest.mark.parametrize(
    "frame",
    [
        '{"state":{},"extra":' + "9" * 6000 + "}",
        '{"state":{"nested":' + "[" * 20_000 + "0" + "]" * 20_000 + "}}",
    ],
    ids=["oversized-integer", "excessive-nesting"],
)
def test_pathological_json_frames_never_escape_as_parser_exceptions(frame):
    result = _parse_worker_frame(frame, 0, "", worker_label="sandbox worker")
    # Decoder depth behavior differs between Python versions. Valid frames can
    # remain dictionaries; a decoder rejection must be a structured failure.
    if isinstance(result, dict):
        assert isinstance(result["state"], dict)
    else:
        assert not result.success
        assert "invalid result" in result.error


def test_catalog_capacity_rejection_does_not_poison_store(tmp_path, monkeypatch):
    monkeypatch.setattr("forgeagent.external_actions._MAX_CATALOG_BYTES", 36)
    store = ExternalActionReceiptStore(str(tmp_path), task_id="audit")
    try:
        store.create_prepared(server_label="demo", tool_label="send", request_digest="b" * 64)
        with pytest.raises(ReceiptError, match="too large"):
            store.create_prepared(server_label="demo", tool_label="send", request_digest="b" * 64)
        assert len(store.list_pending()) == 1
    finally:
        store.close()
