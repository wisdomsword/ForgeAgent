from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_HOME_STATE = pytest.StashKey[tuple[Path, str | None, str | None]]()


def pytest_sessionstart(session: pytest.Session) -> None:
    worker = getattr(session.config, "workerinput", {}).get("workerid", "main")
    home = Path(tempfile.mkdtemp(prefix=f"forgeagent-test-home-{worker}-"))
    session.config.stash[_HOME_STATE] = (
        home,
        os.environ.get("HOME"),
        os.environ.get("USERPROFILE"),
    )
    os.environ["HOME"] = str(home)
    os.environ["USERPROFILE"] = str(home)


def pytest_sessionfinish(session: pytest.Session) -> None:
    state = session.config.stash.get(_HOME_STATE, None)
    if state is None:
        return
    home, old_home, old_userprofile = state
    for name, value in (("HOME", old_home), ("USERPROFILE", old_userprofile)):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    shutil.rmtree(home, ignore_errors=True)
