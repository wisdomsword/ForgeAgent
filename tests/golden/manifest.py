"""The fixed trusted-core golden scenario manifest."""

from __future__ import annotations

from collections.abc import Callable
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
