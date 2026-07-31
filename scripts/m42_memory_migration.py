from __future__ import annotations

import argparse
import json
import os
import stat
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from forgeagent.memory import MemoryManager

_MAX_MANIFEST_BYTES = 64 * 1024
_MANIFEST_REASONS = frozenset({"manifest_format", "manifest_path", "manifest_file"})


class ManifestInputError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason if reason in _MANIFEST_REASONS else "manifest_format"


def _load_manifest(root: Path, relative_name: str) -> dict[str, object]:
    relative = Path(relative_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ManifestInputError("manifest_path")
    candidate = root / relative
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ManifestInputError("manifest_path")
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise ManifestInputError("manifest_path")
    try:
        descriptor = os.open(
            candidate,
            os.O_RDONLY | no_follow | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError:
        raise ManifestInputError("manifest_file") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_MANIFEST_BYTES:
            raise ManifestInputError("manifest_file")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            raw = handle.read(_MAX_MANIFEST_BYTES + 1)
    except OSError:
        raise ManifestInputError("manifest_file") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise ManifestInputError("manifest_file")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise ManifestInputError("manifest_format") from None
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ManifestInputError("manifest_format")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="m42-memory-migration")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("readiness", "verify"):
        command = subparsers.add_parser(name)
        command.add_argument("--root", required=True)
    migrate = subparsers.add_parser("migrate")
    migrate.add_argument("--root", required=True)
    migrate.add_argument("--manifest", required=True)
    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--root", required=True)
    rollback.add_argument("--migration-id", required=True)
    return parser


def _print_result(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = Path(args.root).resolve()
        manager = MemoryManager(str(root))
        if args.command == "readiness":
            result = manager.readiness()
        elif args.command == "verify":
            result = manager.verify_project()
        elif args.command == "migrate":
            manifest = _load_manifest(root, args.manifest)
            result = manager.migrate_legacy(manifest)
        else:
            result = manager.rollback_migration(args.migration_id)
    except ManifestInputError as error:
        _print_result({"entry_count": 0, "reason": error.reason, "status": "rejected"})
        return 2
    except Exception:
        _print_result(
            {
                "entry_count": 0,
                "reason": "operation_failed",
                "status": "persistence_error",
            }
        )
        return 2
    _print_result(asdict(result))
    success = {
        "no_data",
        "legacy_ready",
        "current",
        "verified",
        "migrated",
        "not_required",
        "rolled_back",
    }
    return 0 if result.status in success else 2


if __name__ == "__main__":
    raise SystemExit(main())
