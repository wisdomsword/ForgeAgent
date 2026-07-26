"""Restricted Python entry point for host-defined evaluator checks."""

from __future__ import annotations

import os
import runpy
import sys
import traceback
from pathlib import Path

from ._sandbox_worker import _install_audit_hook


def main() -> int:
    allowed_root = os.environ.pop("FORGEAGENT_CHECK_ROOT")
    arguments = sys.argv[1:]
    _install_audit_hook(
        allowed_root,
        writes_only_in_root=True,
        readable_directory_roots=(sys.base_prefix, sys.prefix),
        allowed_files=(os.devnull,),
    )
    sys.path.insert(0, allowed_root)
    try:
        if arguments[:1] == ["-c"] and len(arguments) >= 2:
            sys.argv = ["-c", *arguments[2:]]
            namespace = {"__name__": "__main__", "__file__": "<check>"}
            exec(compile(arguments[1], "<check>", "exec"), namespace)  # noqa: S102
        elif arguments[:1] == ["-m"] and len(arguments) >= 2:
            sys.argv = [arguments[1], *arguments[2:]]
            runpy.run_module(arguments[1], run_name="__main__", alter_sys=True)
        elif arguments and not arguments[0].startswith("-"):
            sys.argv = [arguments[0], *arguments[1:]]
            runpy.run_path(str(Path(arguments[0])), run_name="__main__")
        else:
            print("unsupported check invocation", file=sys.stderr)
            return 2
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except PermissionError as exc:
        if str(exc).startswith("restricted:"):
            print(str(exc), file=sys.stderr)
        else:
            traceback.print_exc()
        return 1
    except BaseException:  # noqa: BLE001 - worker must return a stable process result
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
