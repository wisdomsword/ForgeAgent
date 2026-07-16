"""Executable trusted-core golden validation protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forgeagent.client import ModelClient

    from .manifest import GoldenScenario


EXPECTED_IDS = frozenset(
    {
        "G01",
        "G03",
        "G05",
        "G06",
        "G08",
        "G11",
        "G13",
        "G14",
        "G15",
        "G17",
        "G27",
        "G43",
        "G58",
        "G59",
        "G324",
        "G329",
        "G330",
        "G332",
        "G333",
        "G355",
    }
)
EXPECTED_REAL_IDS = frozenset({"G01", "G03", "G08", "G11", "G43"})
JSON_SCHEMA = "forgeagent.golden.v1"
INVALID_EVIDENCE_DETAIL = "invalid evidence"
_HOME_VARIABLES = ("HOME", "USERPROFILE", "XDG_CONFIG_HOME")
_CORE_HEADING_ID = re.compile(r"^#{1,6}[ \t]+(G(?:0[1-9]|[12][0-9]|30))(?:[ \t]|$)", re.MULTILINE)
_CANDIDATE_TABLE_HEADER = ("ID", "描述", "Pass 判定")
_CANDIDATE_ID = re.compile(r"G(?:3[1-9]|[4-9][0-9]|[12][0-9]{2}|3[0-7][0-9]|380)")


class GoldenPreflightError(Exception):
    """The manifest, selected model, or report destination cannot be used."""


@dataclass(frozen=True)
class GoldenResult:
    scenario_id: str
    title: str
    passed: bool
    duration: float
    detail: str
    evidence: dict[str, object]


@dataclass(frozen=True)
class GoldenSuite:
    mode: str
    model: str | None
    started_at: str
    finished_at: str
    results: tuple[GoldenResult, ...]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(result.passed for result in self.results)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return 0.0 if not self.total else self.passed * 100 / self.total

    @property
    def exit_code(self) -> int:
        return 0 if not self.failed else 1


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "golden-tasks-seed.md"


def _catalog_table_cells(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return tuple(cell.strip() for cell in stripped[1:-1].split("|"))


def _catalog_definition_ids(catalog: str) -> set[str]:
    definition_ids = set(_CORE_HEADING_ID.findall(catalog))
    in_candidate_table = False
    for line in catalog.splitlines():
        cells = _catalog_table_cells(line)
        if cells is None:
            in_candidate_table = False
            continue
        if cells == _CANDIDATE_TABLE_HEADER:
            in_candidate_table = True
            continue
        if in_candidate_table and cells and _CANDIDATE_ID.fullmatch(cells[0]):
            definition_ids.add(cells[0])
    return definition_ids


def validate_manifest(
    scenarios: Sequence[GoldenScenario], *, catalog_path: Path | None = None
) -> None:
    """Reject any manifest drift before a scenario or report directory is created."""
    identifiers = tuple(scenario.scenario_id for scenario in scenarios)
    identifier_set = frozenset(identifiers)
    real_identifiers = frozenset(
        scenario.scenario_id for scenario in scenarios if scenario.run_real is not None
    )
    if (
        len(scenarios) != 20
        or len(identifier_set) != len(scenarios)
        or identifier_set != EXPECTED_IDS
    ):
        raise GoldenPreflightError("golden manifest IDs must match the approved core exactly")
    if len(real_identifiers) != 5 or real_identifiers != EXPECTED_REAL_IDS:
        raise GoldenPreflightError(
            "golden manifest real-model IDs must match the approved core exactly"
        )

    try:
        catalog = (catalog_path or _catalog_path()).read_text(encoding="utf-8")
    except OSError as exc:
        raise GoldenPreflightError("golden task catalog is unavailable") from exc
    definition_ids = _catalog_definition_ids(catalog)
    for scenario_id in identifier_set:
        if scenario_id not in definition_ids:
            raise GoldenPreflightError(f"golden task catalog is missing {scenario_id}")


def _validate_evidence(value: object) -> bool:
    if value is None:
        return True
    if type(value) is bool or type(value) is str or type(value) is int:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_validate_evidence(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _validate_evidence(item) for key, item in value.items())
    return False


def _valid_evidence(evidence: object) -> bool:
    if type(evidence) is not dict or not _validate_evidence(evidence):
        return False
    try:
        json.dumps(evidence, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True


def run_suite(
    scenarios: Sequence[GoldenScenario],
    *,
    mode: str,
    model: str | None = None,
    real_client: ModelClient | None = None,
) -> GoldenSuite:
    """Run each scenario in a fresh work directory and keep going after failures."""
    from .manifest import GoldenCheckError, GoldenEvidence

    started_at = datetime.now(UTC).isoformat()
    results: list[GoldenResult] = []
    for scenario in scenarios:
        began = time.perf_counter()
        try:
            prefix = f"forgeagent-golden-{scenario.scenario_id}-"
            with tempfile.TemporaryDirectory(prefix=prefix) as name:
                workdir = Path(name)
                if mode == "real":
                    if scenario.run_real is None or real_client is None:
                        raise GoldenCheckError("real-model runner is unavailable")
                    evidence = scenario.run_real(workdir, real_client)
                else:
                    evidence = scenario.run_offline(workdir)
            duration = time.perf_counter() - began
            if type(evidence) is not GoldenEvidence:
                results.append(
                    GoldenResult(
                        scenario.scenario_id,
                        scenario.title,
                        False,
                        duration,
                        "invalid scenario result",
                        {},
                    )
                )
            elif type(evidence.detail) is not str or not _valid_evidence(evidence.evidence):
                results.append(
                    GoldenResult(
                        scenario.scenario_id,
                        scenario.title,
                        False,
                        duration,
                        INVALID_EVIDENCE_DETAIL,
                        {},
                    )
                )
            else:
                results.append(
                    GoldenResult(
                        scenario.scenario_id,
                        scenario.title,
                        True,
                        duration,
                        evidence.detail,
                        evidence.evidence,
                    )
                )
        except GoldenCheckError as exc:
            results.append(
                GoldenResult(
                    scenario.scenario_id,
                    scenario.title,
                    False,
                    time.perf_counter() - began,
                    str(exc),
                    {},
                )
            )
        except Exception as exc:
            results.append(
                GoldenResult(
                    scenario.scenario_id,
                    scenario.title,
                    False,
                    time.perf_counter() - began,
                    f"unexpected scenario error: {type(exc).__name__}",
                    {},
                )
            )
    return GoldenSuite(
        mode=mode,
        model=model,
        started_at=started_at,
        finished_at=datetime.now(UTC).isoformat(),
        results=tuple(results),
    )


def _suite_payload(suite: GoldenSuite) -> dict[str, object]:
    return {
        "schema": JSON_SCHEMA,
        "mode": suite.mode,
        "model": suite.model,
        "started_at": suite.started_at,
        "finished_at": suite.finished_at,
        "total": suite.total,
        "passed": suite.passed,
        "failed": suite.failed,
        "pass_rate": suite.pass_rate,
        "results": [asdict(result) for result in suite.results],
    }


def render_markdown(suite: GoldenSuite) -> str:
    """Render the already-judged suite; this function performs no second evaluation."""
    lines = [
        "# ForgeAgent Golden Validation",
        "",
        f"Mode: `{suite.mode}`",
        f"Model: `{suite.model or 'offline'}`",
        f"Summary: {suite.passed}/{suite.total} passed ({suite.pass_rate:.1f}%)",
        "",
        "| ID | Title | Result | Duration (s) | Detail |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for result in suite.results:
        detail = result.detail.replace("|", "\\|").replace("\n", " ")
        status = "PASS" if result.passed else "FAIL"
        lines.append(
            f"| {result.scenario_id} | {result.title} | {status} | "
            f"{result.duration:.3f} | {detail} |"
        )
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def write_reports(suite: GoldenSuite, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "results.json"
    markdown_path = output_dir / "report.md"
    _atomic_write(json_path, json.dumps(_suite_payload(suite), indent=2, ensure_ascii=True) + "\n")
    _atomic_write(markdown_path, render_markdown(suite))
    return json_path, markdown_path


def default_output_dir(
    *, mode: str, model_id: str | None, artifact_root: Path = Path("artifacts")
) -> Path:
    if mode == "offline":
        return artifact_root / "golden" / "offline"
    if mode != "real" or model_id is None:
        raise GoldenPreflightError("real output requires a model identifier")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", model_id).strip("-_")[:48] or "model"
    digest = hashlib.sha256(model_id.encode("utf-8")).hexdigest()[:8]
    return artifact_root / "golden" / "real" / f"{slug}-{digest}"


def _load_manifest() -> tuple[GoldenScenario, ...]:
    from .manifest import GOLDEN_SCENARIOS

    return GOLDEN_SCENARIOS


def _load_offline_configuration_modules(user_path: Path) -> None:
    """Bind all home-derived defaults only after offline home isolation is active."""
    from forgeagent import cli, mcp_manager, model_registry

    mcp_manager.load_mcp_config(user_path=user_path)
    del cli, mcp_manager, model_registry


def _build_real_client(model_id: str) -> ModelClient:
    from forgeagent.cli import build_real_client

    return build_real_client(model_id)


@contextmanager
def _isolated_offline_home() -> Iterator[None]:
    original = {name: os.environ.get(name) for name in _HOME_VARIABLES}
    with tempfile.TemporaryDirectory(prefix="forgeagent-golden-home-") as home:
        try:
            for name in _HOME_VARIABLES:
                os.environ[name] = home
            yield
        finally:
            for name, value in original.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def _prepare_output_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise GoldenPreflightError("golden output directory is unavailable") from exc


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ForgeAgent trusted golden core")
    parser.add_argument("--real-model", metavar="MODEL_ID")
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the offline core or the five explicit real-model scenarios."""
    args = _parse_args(argv)
    isolation = nullcontext() if args.real_model is not None else _isolated_offline_home()
    with isolation:
        try:
            scenarios = _load_manifest()
            if args.real_model is not None:
                validate_manifest(scenarios)
                client = _build_real_client(args.real_model)
                selected = tuple(
                    scenario for scenario in scenarios if scenario.run_real is not None
                )
                output_dir = args.output_dir or default_output_dir(
                    mode="real", model_id=args.real_model
                )
            else:
                user_path = Path(os.environ["HOME"]) / ".forgeagent" / "mcp.yaml"
                _load_offline_configuration_modules(user_path)
                validate_manifest(scenarios)
                output_dir = args.output_dir or default_output_dir(mode="offline", model_id=None)
            _prepare_output_dir(output_dir)
        except Exception as exc:
            print(f"golden preflight failed: {type(exc).__name__}")
            return 2
        if args.real_model is not None:
            suite = run_suite(selected, mode="real", model=args.real_model, real_client=client)
        else:
            suite = run_suite(scenarios, mode="offline")
        try:
            write_reports(suite, output_dir)
        except OSError as exc:
            print(f"golden report failed: {type(exc).__name__}")
            return 2
        return suite.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
