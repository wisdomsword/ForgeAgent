from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "m44_http_action_approval_smoke.py"


def test_m44_smoke_uses_real_loopback_without_replay_or_private_output() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=SCRIPT.parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "approval_status": "consumed",
        "dispatch_count": 1,
        "receipt_phase": "confirmed",
        "reconcile_dispatch_delta": 0,
        "unknown_resolution": "confirmed",
    }
    for private_value in (
        "m44-private-token",
        "complete private goal",
        "private-repository",
        "Traceback",
        "/tmp/",
        "/private/",
    ):
        assert private_value not in result.stdout
