"""Tasks 8-9 implementation slots for the trusted-core golden scenarios."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forgeagent.client import ModelClient

    from .manifest import GoldenEvidence


def _pending(scenario_id: str) -> GoldenEvidence:
    from .manifest import GoldenCheckError

    raise GoldenCheckError(f"{scenario_id} case implementation pending")


def run_g01_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G01")


def run_g01_real(workdir: Path, client: ModelClient) -> GoldenEvidence:
    return _pending("G01")


def run_g03_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G03")


def run_g03_real(workdir: Path, client: ModelClient) -> GoldenEvidence:
    return _pending("G03")


def run_g05_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G05")


def run_g06_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G06")


def run_g08_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G08")


def run_g08_real(workdir: Path, client: ModelClient) -> GoldenEvidence:
    return _pending("G08")


def run_g11_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G11")


def run_g11_real(workdir: Path, client: ModelClient) -> GoldenEvidence:
    return _pending("G11")


def run_g13_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G13")


def run_g14_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G14")


def run_g15_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G15")


def run_g17_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G17")


def run_g27_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G27")


def run_g43_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G43")


def run_g43_real(workdir: Path, client: ModelClient) -> GoldenEvidence:
    return _pending("G43")


def run_g58_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G58")


def run_g59_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G59")


def run_g324_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G324")


def run_g329_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G329")


def run_g330_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G330")


def run_g332_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G332")


def run_g333_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G333")


def run_g355_offline(workdir: Path) -> GoldenEvidence:
    return _pending("G355")
