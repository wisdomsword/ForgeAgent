"""The fixed trusted-core golden scenario manifest."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import cases

if TYPE_CHECKING:
    from forgeagent.client import ModelClient


@dataclass(frozen=True)
class GoldenEvidence:
    detail: str
    evidence: dict[str, object]


OfflineRunner = Callable[[Path], GoldenEvidence]
RealRunner = Callable[[Path, "ModelClient"], GoldenEvidence]


@dataclass(frozen=True)
class GoldenScenario:
    scenario_id: str
    title: str
    run_offline: OfflineRunner
    run_real: RealRunner | None = None


class GoldenCheckError(Exception):
    """A scenario's explicit machine-check failure."""


class GoldenPreflightError(Exception):
    """The manifest, selected model, or report destination cannot be used."""


GOLDEN_SCENARIOS: tuple[GoldenScenario, ...] = (
    GoldenScenario("G01", "CSV summary", cases.run_g01_offline, cases.run_g01_real),
    GoldenScenario("G03", "JSON structure transform", cases.run_g03_offline, cases.run_g03_real),
    GoldenScenario("G05", "Cross-block state", cases.run_g05_offline),
    GoldenScenario("G06", "Restricted denial", cases.run_g06_offline),
    GoldenScenario("G08", "Bug fix", cases.run_g08_offline, cases.run_g08_real),
    GoldenScenario("G11", "Merge and deduplicate", cases.run_g11_offline, cases.run_g11_real),
    GoldenScenario("G13", "Error feedback loop", cases.run_g13_offline),
    GoldenScenario("G14", "Restricted timeout", cases.run_g14_offline),
    GoldenScenario("G15", "Incremental edit", cases.run_g15_offline),
    GoldenScenario("G17", "Two-file key join", cases.run_g17_offline),
    GoldenScenario("G27", "Fix regression with edit chain", cases.run_g27_offline),
    GoldenScenario("G43", "Text word-frequency Top-N", cases.run_g43_offline, cases.run_g43_real),
    GoldenScenario("G58", "Restricted out-of-root read", cases.run_g58_offline),
    GoldenScenario("G59", "Restricted out-of-root write", cases.run_g59_offline),
    GoldenScenario("G324", "FileWrite out-of-root rejection", cases.run_g324_offline),
    GoldenScenario("G329", "Confirmed WebFetch policy", cases.run_g329_offline),
    GoldenScenario("G330", "Redirect boundary", cases.run_g330_offline),
    GoldenScenario("G332", "WebFetch no-channel", cases.run_g332_offline),
    GoldenScenario("G333", "File boundary", cases.run_g333_offline),
    GoldenScenario("G355", "MCP slash command", cases.run_g355_offline),
)

_BASELINE_SCHEMA = "forgeagent.golden-manifest.v1"
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")


def _fingerprint_rows(rows: Sequence[tuple[str, str, bool]]) -> str:
    payload = [
        {"scenario_id": scenario_id, "title": title, "run_real": run_real}
        for scenario_id, title, run_real in rows
    ]
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def manifest_fingerprint(scenarios: Sequence[GoldenScenario] = GOLDEN_SCENARIOS) -> str:
    """Return the canonical digest of the approved manifest identity fields."""
    rows = tuple((item.scenario_id, item.title, item.run_real is not None) for item in scenarios)
    return _fingerprint_rows(rows)


def load_manifest_baseline(path: Path | None = None) -> tuple[tuple[str, str, bool], ...]:
    """Load and authenticate the checked-in canonical scenario identity list."""
    try:
        payload = json.loads(
            (path or Path(__file__).with_name("manifest_baseline.json")).read_text(encoding="utf-8")
        )
        if type(payload) is not dict or set(payload) != {"schema", "scenarios", "fingerprint"}:
            raise ValueError
        if payload["schema"] != _BASELINE_SCHEMA or not _FINGERPRINT.fullmatch(
            payload["fingerprint"]
        ):
            raise ValueError
        scenarios = payload["scenarios"]
        if type(scenarios) is not list or len(scenarios) != 20:
            raise ValueError
        rows = tuple(
            (row["scenario_id"], row["title"], row["run_real"])
            for row in scenarios
            if type(row) is dict
            and set(row) == {"scenario_id", "title", "run_real"}
            and type(row["scenario_id"]) is str
            and type(row["title"]) is str
            and type(row["run_real"]) is bool
        )
        if len(rows) != len(scenarios) or _fingerprint_rows(rows) != payload["fingerprint"]:
            raise ValueError
        return rows
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise GoldenPreflightError("golden manifest canonical baseline mismatch") from exc
