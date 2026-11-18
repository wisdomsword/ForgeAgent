"""Check locked Python and OpenSpec dependencies against public advisory databases."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/ci/dependency-audit"
OPENSPEC = ROOT / "tools/openspec"
PIP_AUDIT = "pip-audit==2.10.1"

PICOMATCH_ADVISORY = "https://github.com/advisories/GHSA-fc5q-39xc-vjpf"
PICOMATCH_PATH = "node_modules/picomatch"
PICOMATCH_VERSION = "2.3.2"
EXCEPTION_END = "2026-12-18"  # UTC, exclusive.


def npm_gate(report: dict, packages: dict, date: str) -> bool:
    """Accept exactly one known root advisory on the reviewed locked version."""
    if "error" in report or report.get("auditReportVersion") != 2:
        return False
    findings = report["vulnerabilities"]
    if not isinstance(findings, dict):
        return False
    if report["metadata"]["vulnerabilities"]["total"] != len(findings):
        return False
    if not findings:
        return True
    if date >= EXCEPTION_END:
        return False

    # npm reports the root advisory and a finding for each dependent package.
    pending = list(findings)
    for _ in range(len(findings)):
        for name in pending[:]:
            via = findings[name]["via"]
            if name == "picomatch":
                root = findings[name]
                if (
                    root["nodes"] != [PICOMATCH_PATH]
                    or packages.get(PICOMATCH_PATH, {}).get("version") != PICOMATCH_VERSION
                    or len(via) != 1
                    or not isinstance(via[0], dict)
                    or via[0].get("url") != PICOMATCH_ADVISORY
                ):
                    return False
            elif not via or any(
                not isinstance(parent, str) or parent not in findings or parent in pending
                for parent in via
            ):
                continue
            pending.remove(name)
    return "picomatch" in findings and not pending


def python_audit(name: str, pins: list[str], source: str) -> bool:
    if not pins or any(not re.fullmatch(r"[\w.-]+==[\w.+!~-]+", pin) for pin in pins):
        raise ValueError(f"{name} must contain exact package versions")
    requirements = OUTPUT / f"{name}.txt"
    requirements.write_text("\n".join(sorted(pins)) + "\n", encoding="utf-8")
    result = subprocess.run(
        [
            "uv",
            "tool",
            "run",
            "--from",
            PIP_AUDIT,
            "pip-audit",
            "--strict",
            "--no-deps",
            "--disable-pip",
            "--progress-spinner",
            "off",
            "--vulnerability-service",
            source,
            "--format",
            "json",
            "--output",
            str(OUTPUT / f"{name}-{source}.json"),
            "--requirement",
            str(requirements),
        ],
        check=False,
    )
    return result.returncode == 0


def npm_audit() -> bool:
    audit = OUTPUT / "openspec-npm.json"
    with audit.open("w", encoding="utf-8") as output:
        result = subprocess.run(
            ["npm", "audit", "--json", "--package-lock-only", "--prefix", str(OPENSPEC)],
            stdout=output,
            check=False,
        )
    report = json.loads(audit.read_text(encoding="utf-8"))
    packages = json.loads((OPENSPEC / "package-lock.json").read_text(encoding="utf-8"))["packages"]
    date = datetime.now(UTC).date().isoformat()
    if result.returncode not in {0, 1} or not npm_gate(report, packages, date):
        print(f"OpenSpec audit failed. See {audit}.", file=sys.stderr)
        return False
    if report["vulnerabilities"]:
        print(f"OpenSpec exception {PICOMATCH_ADVISORY}, expires {EXCEPTION_END} UTC. See {audit}.")
    return True


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    pinned = [
        f"{package['name']}=={package['version']}"
        for package in lock["package"]
        if package.get("source") != {"editable": "."}
    ]
    if any(
        p.get("source") not in ({"editable": "."}, {"registry": "https://pypi.org/simple"})
        for p in lock["package"]
    ):
        raise ValueError("Dependency with an unsupported source in uv.lock")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    build = (
        project["build-system"]["requires"] + project["tool"]["uv"]["build-constraint-dependencies"]
    )
    ci = (ROOT / "tools/ci-requirements.txt").read_text(encoding="utf-8").splitlines()
    results = [
        python_audit("locked-python", pinned, "pypi"),
        python_audit("locked-python", pinned, "osv"),
        python_audit("build-python", build, "pypi"),
        python_audit("ci-python", ci, "pypi"),
        npm_audit(),
    ]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
