"""Contract tests for the executable golden validation runner."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import replace
from enum import IntEnum
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from forgeagent.client import MockClient
from forgeagent.models import ClientError
from forgeagent.runtime import Runtime
from tests.golden import cases
from tests.golden.manifest import (
    GOLDEN_SCENARIOS,
    GoldenCheckError,
    GoldenEvidence,
    GoldenScenario,
    load_manifest_baseline,
    manifest_fingerprint,
)
from tests.golden.runner import (
    EXPECTED_IDS,
    EXPECTED_REAL_IDS,
    GoldenPreflightError,
    _load_offline_configuration_modules,
    default_output_dir,
    main,
    render_markdown,
    run_suite,
    validate_manifest,
    write_reports,
)

COMMON_IDS = ("G01", "G03", "G05", "G08", "G11", "G13", "G15", "G17", "G27", "G43")
BOUNDARY_IDS = ("G06", "G14", "G58", "G59", "G324", "G329", "G330", "G332", "G333", "G355")
EXPECTED_COMMON_EVIDENCE = {
    "G01": (
        "CSV summary matched",
        {"rows": 3, "sum": 60.0, "mean": 20.0},
    ),
    "G03": (
        "nested JSON was flattened exactly",
        {
            "columns": ["order_id", "customer", "city", "sku", "quantity"],
            "rows": [
                ["A-2", "Ada", "London", "P-2", "2"],
                ["A-2", "Ada", "London", "P-1", "1"],
                ["A-1", "Lin", "Shanghai", "P-3", "4"],
            ],
        },
    ),
    "G05": (
        "cross-block state was read and used",
        {
            "state": 42,
            "output": 50,
            "side_effects": 1,
            "state_reads": 1,
            "returned_value_uses": 1,
            "causal_delta": 8,
        },
    ),
    "G08": (
        "bug fix preserved the provided tests",
        {"before_exit_code": 1, "after_exit_code": 0, "test_hash_unchanged": True},
    ),
    "G11": (
        "CSV rows were merged and deduplicated exactly",
        {
            "columns": ["id", "name", "score"],
            "rows": [["1", "Ada", "10"], ["2", "Ben", "20"], ["3", "Cora", "30"]],
        },
    ),
    "G13": (
        "completion required an independent third round",
        {
            "rounds": 3,
            "failed_tool_round": 1,
            "successful_tool_round": 2,
            "completion_round": 3,
        },
    ),
    "G15": (
        "Edit produced one precise parseable version",
        {
            "edit_calls": 1,
            "versions": [1, 2],
            "history_size": 2,
            "changed_line": 4,
            "target_value": 15,
            "ast_valid": True,
        },
    ),
    "G17": (
        "inner join matched exactly",
        {
            "columns": ["user_id", "name", "score"],
            "rows": [["u2", "Grace", "88"], ["u1", "Ada", "91"]],
        },
    ),
    "G27": (
        "regression fix passed through an Edit version chain",
        {
            "before_exit_code": 1,
            "after_exit_code": 0,
            "edit_calls": 1,
            "versions": [1, 2],
        },
    ),
    "G43": (
        "word-frequency Top-N matched exactly",
        {
            "top_n": [
                ["forge", 4],
                ["code", 2],
                ["tests", 2],
                ["agents", 1],
                ["guide", 1],
            ]
        },
    ),
}
EXPECTED_BOUNDARY_EVIDENCE = {
    "G06": (
        "restricted denial returned through task feedback",
        {
            "rounds": 2,
            "failed_round": 1,
            "completion_round": 2,
            "target_content_exposed": False,
        },
    ),
    "G14": (
        "timeout was isolated from later work",
        {
            "rounds": 3,
            "timed_out_round": 1,
            "successful_round": 2,
            "worker_processes": 2,
            "workers_reaped": True,
        },
    ),
    "G58": (
        "audit hook blocked the out-of-root read",
        {
            "success": False,
            "error": "restricted: file access outside allowed root denied",
            "target_content_exposed": False,
        },
    ),
    "G59": (
        "audit hook blocked the out-of-root write",
        {
            "success": False,
            "error": "restricted: file access outside allowed root denied",
            "target_exists": False,
        },
    ),
    "G324": (
        "FileWrite rejected the out-of-root target",
        {
            "success": False,
            "detail": "FileWrite path is outside project root",
            "target_exists": False,
        },
    ),
    "G329": (
        "confirmed metadata fetch was blocked before connect",
        {
            "success": False,
            "detail": "WebFetch blocked by network policy",
            "connector_calls": 0,
        },
    ),
    "G330": (
        "private redirect was rejected before connect",
        {
            "blocked": True,
            "resolved_hosts": ["public.example", "private.example"],
            "public_connection_calls": 1,
            "private_connection_calls": 0,
        },
    ),
    "G332": (
        "WebFetch confirmation controlled fake network access",
        {
            "rejected_detail": "rejected: no interactive confirmation channel available",
            "rejected_network_calls": 0,
            "approved": True,
            "approved_network_calls": 1,
        },
    ),
    "G333": (
        "FileWrite confirmation did not replace the project-root boundary",
        {
            "filewrite_detail": "FileWrite was not approved by the user",
            "filewrite_created": False,
            "exec_success": True,
            "final_content": "written by Exec",
        },
    ),
    "G355": (
        "MCP slash output showed optional degradation and available tools",
        {
            "available_status": True,
            "unavailable_status": True,
            "available_tools": ["add", "echo"],
            "unavailable_tools": [],
            "pid_reaped": True,
        },
    ),
}

_GOLDEN_HEADING_ID = re.compile(r"^#{1,6}[ \t]+(G\d+)\b", re.MULTILINE)
_GOLDEN_TABLE_HEADER = ("ID", "描述", "Pass 判定")
_GOLDEN_ID = re.compile(r"^G\d+$")
_GOLDEN_CATEGORY_HEADING = re.compile(
    r"^#{2,3}[ \t]+(文件/数据处理|Python 执行与 sandbox 边界|"
    r"代码修改/小型重构|网络抓取或外部 API|系统查询/环境检查)"
)
_GOLDEN_CATEGORY_NAMES = {
    "文件/数据处理": "file_data",
    "Python 执行与 sandbox 边界": "execution_boundary",
    "代码修改/小型重构": "code_change",
    "网络抓取或外部 API": "network_api",
    "系统查询/环境检查": "system_query",
}
_EXPECTED_CATEGORY_TOTALS = {
    "file_data": 160,
    "execution_boundary": 100,
    "code_change": 80,
    "network_api": 40,
    "system_query": 20,
}
_EXPECTED_M15_CATEGORY_TOTALS = {
    "file_data": 8,
    "execution_boundary": 5,
    "code_change": 4,
    "network_api": 2,
    "system_query": 1,
}
_M18_CANDIDATE_IDS = frozenset(f"G{number:02d}" for number in range(401, 421))


def _golden_heading_ids(markdown: str) -> tuple[str, ...]:
    return tuple(_GOLDEN_HEADING_ID.findall(markdown))


def _golden_table_cells(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return tuple(cell.strip() for cell in stripped[1:-1].split("|"))


def _parse_golden_catalog_definitions(
    markdown: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    heading_ids = _golden_heading_ids(markdown)
    candidate_ids: list[str] = []
    in_candidate_table = False

    for line in markdown.splitlines():
        cells = _golden_table_cells(line)
        if cells is None:
            in_candidate_table = False
            continue
        if cells == _GOLDEN_TABLE_HEADER:
            in_candidate_table = True
            continue
        if in_candidate_table and cells and _GOLDEN_ID.fullmatch(cells[0]):
            candidate_ids.append(cells[0])

    return heading_ids, tuple(candidate_ids)


def _parse_golden_catalog_categories(markdown: str) -> dict[str, str]:
    categories: dict[str, str] = {}
    current_category: str | None = None
    in_candidate_table = False

    for line in markdown.splitlines():
        if line.startswith("## M18 扩充候选"):
            current_category = None
            in_candidate_table = False
            continue
        category_match = _GOLDEN_CATEGORY_HEADING.match(line)
        if category_match is not None:
            current_category = _GOLDEN_CATEGORY_NAMES[category_match.group(1)]
            in_candidate_table = False
            continue

        heading_match = _GOLDEN_HEADING_ID.match(line)
        if heading_match is not None and current_category is not None:
            scenario_id = heading_match.group(1)
            assert scenario_id not in categories
            categories[scenario_id] = current_category

        cells = _golden_table_cells(line)
        if cells is None:
            in_candidate_table = False
            continue
        if cells == _GOLDEN_TABLE_HEADER:
            in_candidate_table = True
            continue
        if (
            in_candidate_table
            and current_category is not None
            and cells
            and _GOLDEN_ID.fullmatch(cells[0])
        ):
            assert cells[0] not in categories
            categories[cells[0]] = current_category

    return categories


def _assert_golden_candidate_catalog(markdown: str) -> None:
    heading_ids, candidate_rows = _parse_golden_catalog_definitions(markdown)
    expected_heading_ids = frozenset(f"G{number:02d}" for number in range(1, 31))
    expected_candidate_ids = frozenset(f"G{number:02d}" for number in range(31, 421))
    expected_ids = expected_heading_ids | expected_candidate_ids
    heading_id_set = frozenset(heading_ids)
    candidate_id_set = frozenset(candidate_rows)
    all_ids = heading_id_set | candidate_id_set

    assert len(heading_ids) == len(heading_id_set)
    assert heading_id_set == expected_heading_ids
    assert len(candidate_rows) == len(candidate_id_set)
    assert candidate_id_set == expected_candidate_ids
    assert all_ids == expected_ids
    assert EXPECTED_IDS <= all_ids
    assert len(all_ids - EXPECTED_IDS) == 400

    categories = _parse_golden_catalog_categories(markdown)
    assert frozenset(categories) == expected_ids - _M18_CANDIDATE_IDS
    assert Counter(categories.values()) == _EXPECTED_CATEGORY_TOTALS
    m15_ids = {f"G{number}" for number in range(381, 401)}
    assert Counter(categories[scenario_id] for scenario_id in m15_ids) == (
        _EXPECTED_M15_CATEGORY_TOTALS
    )


def _assert_readme_proxy_migration_contract(readme: str) -> None:
    assert "[SECURITY][BREAKING]" in readme
    assert "ProxyHandler({})" in readme
    assert "NO_PROXY" in readme
    assert "no_proxy" in readme
    assert "不能恢复代理" in readme
    assert "允许该进程直连" in readme
    assert "在 ForgeAgent 外部预取到 `allowed_root` 后用 FileRead" in readme
    assert "明确受信任的 MCP fetch 工具" in readme


def _assert_readme_identity_contract(readme: str) -> None:
    assert "400 项文档任务" in readme
    assert "其余 380 项保留为候选目录" in readme
    assert "--no-identity" in readme
    assert "SOUL.md" in readme
    assert "AGENTS.md" in readme
    assert "MEMORY.md" in readme
    assert "identity-trust.json" in readme
    assert "首次使用需终端确认" in readme
    assert "docs/threat-model.md" in readme
    assert "SOUL 段始终存在" in readme
    assert "内置中性默认人格" in readme
    assert "只有 USER/AGENTS/MEMORY" in readme


def _assert_identity_threat_model_contract(threat_model: str) -> None:
    t12 = next((line for line in threat_model.splitlines() if line.startswith("| T12 |")), "")
    assert "| T12 | Identity file path/size/TOCTOU and persistent trust bypass |" in t12
    assert (
        "Unsafe or oversized AGENTS.md/MEMORY.md content is stripped with a masked diagnostic"
        in t12
    )
    assert (
        "an unreadable AGENTS.md or MEMORY.md raises IdentityConfigError and stops identity "
        "resolution" in t12
    )


def _pass(_: Path) -> GoldenEvidence:
    return GoldenEvidence(detail="checked", evidence={"value": [None, True, 1, 1.5, "ok"]})


def _fail(_: Path) -> GoldenEvidence:
    raise GoldenCheckError("expected check failed")


def _scenario(scenario_id: str, run_offline=_pass, *, real: bool = False) -> GoldenScenario:
    return GoldenScenario(
        scenario_id=scenario_id,
        title=f"Scenario {scenario_id}",
        run_offline=run_offline,
        run_real=(lambda _path, _client: _pass(_path)) if real else None,
    )


def test_manifest_has_exactly_the_approved_offline_and_real_ids():
    assert len(GOLDEN_SCENARIOS) == 20
    assert frozenset(scenario.scenario_id for scenario in GOLDEN_SCENARIOS) == EXPECTED_IDS
    assert (
        frozenset(
            scenario.scenario_id for scenario in GOLDEN_SCENARIOS if scenario.run_real is not None
        )
        == EXPECTED_REAL_IDS
    )


def _baseline_payload() -> dict[str, object]:
    path = Path(__file__).with_name("golden") / "manifest_baseline.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda items: items[1:],
        lambda items: (*items[:1], replace(items[1], title="lowered"), *items[2:]),
        lambda items: (*items[:1], replace(items[1], run_real=None), *items[2:]),
        lambda items: tuple(reversed(items)),
    ],
)
def test_validate_manifest_rejects_canonical_baseline_drift(mutate):
    with pytest.raises(GoldenPreflightError, match="canonical baseline"):
        validate_manifest(mutate(GOLDEN_SCENARIOS))


def test_manifest_fingerprint_matches_checked_in_baseline():
    assert manifest_fingerprint() == _baseline_payload()["fingerprint"]


def test_validate_manifest_accepts_the_unmodified_canonical_baseline():
    validate_manifest(GOLDEN_SCENARIOS)


def test_load_manifest_baseline_rejects_malformed_or_mismatched_payload(tmp_path):
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"schema": "wrong"}', encoding="utf-8")
    mismatched = tmp_path / "mismatched.json"
    mismatched.write_text(
        json.dumps(
            {
                "schema": "forgeagent.golden-manifest.v1",
                "scenarios": _baseline_payload()["scenarios"],
                "fingerprint": "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    for path in (malformed, mismatched):
        with pytest.raises(GoldenPreflightError, match="canonical baseline"):
            load_manifest_baseline(path)


def test_malformed_baseline_preflight_does_not_create_an_output_directory(tmp_path, monkeypatch):
    output_dir = tmp_path / "not-created"

    def malformed_baseline():
        raise GoldenPreflightError("golden manifest canonical baseline mismatch")

    monkeypatch.setattr("tests.golden.runner.load_manifest_baseline", malformed_baseline)

    assert main(["--output-dir", str(output_dir)]) == 2
    assert not output_dir.exists()


def test_golden_candidate_catalog_rejects_duplicate_missing_extra_and_misnumbered_headings():
    headings = "".join(f"### G{number:02d}\n" for number in range(1, 31))
    coverage_matrix = "| ID | Category |\n| --- | --- |\n" + "".join(
        f"| G{number:02d} | repeated reference |\n" for number in range(1, 16)
    )
    candidate_table = "| ID | 描述 | Pass 判定 |\n| --- | --- | --- |\n" + "".join(
        f"| G{number:02d} | candidate | checked |\n" for number in range(31, 421)
    )
    catalog = headings + coverage_matrix + candidate_table
    invalid_catalogs = (
        catalog.replace("### G30\n", ""),
        catalog.replace("| G420 | candidate | checked |\n", ""),
        catalog.replace("| G420 | candidate | checked |\n", "| G421 | candidate | checked |\n"),
        catalog.replace("| G420 | candidate | checked |\n", "| G0420 | candidate | checked |\n"),
        catalog + "| G420 | duplicate definition | checked |\n",
    )

    for invalid_catalog in invalid_catalogs:
        with pytest.raises(AssertionError):
            _assert_golden_candidate_catalog(invalid_catalog)


def test_golden_candidate_catalog_has_structured_definitions_and_candidates():
    catalog_path = Path(__file__).parent.parent / "docs" / "golden-tasks-seed.md"

    _assert_golden_candidate_catalog(catalog_path.read_text(encoding="utf-8"))


def test_golden_candidate_catalog_rejects_category_distribution_mutations():
    catalog_path = Path(__file__).parent.parent / "docs" / "golden-tasks-seed.md"
    catalog = catalog_path.read_text(encoding="utf-8")
    wrong_global_distribution = catalog.replace(
        "### 文件/数据处理（新增 8：G381–G388）",
        "### 系统查询/环境检查（新增 8：G381–G388）",
        1,
    )
    wrong_m15_distribution = catalog.replace("| G380 |", "| G-SWAP |", 1)
    wrong_m15_distribution = wrong_m15_distribution.replace("| G381 |", "| G380 |", 1)
    wrong_m15_distribution = wrong_m15_distribution.replace("| G-SWAP |", "| G381 |", 1)

    for invalid_catalog in (wrong_global_distribution, wrong_m15_distribution):
        with pytest.raises(AssertionError):
            _assert_golden_candidate_catalog(invalid_catalog)


def test_readme_documents_the_proxy_breaking_change_and_migration_paths():
    readme_path = Path(__file__).parent.parent / "README.md"

    _assert_readme_proxy_migration_contract(readme_path.read_text(encoding="utf-8"))


def test_readme_documents_identity_file_conventions_and_no_identity_flag():
    readme_path = Path(__file__).parent.parent / "README.md"

    _assert_readme_identity_contract(readme_path.read_text(encoding="utf-8"))


def test_threat_model_distinguishes_rejected_from_unreadable_project_identity():
    threat_model_path = Path(__file__).parent.parent / "docs" / "threat-model.md"

    _assert_identity_threat_model_contract(threat_model_path.read_text(encoding="utf-8"))


def test_common_cases_return_the_exact_evidence_contract(tmp_path):
    selected = tuple(
        scenario for scenario in GOLDEN_SCENARIOS if scenario.scenario_id in COMMON_IDS
    )

    suite = run_suite(selected, mode="offline")

    assert suite.exit_code == 0
    assert suite.passed == 10
    assert {
        result.scenario_id: (result.detail, result.evidence) for result in suite.results
    } == EXPECTED_COMMON_EVIDENCE


def test_boundary_cases_return_the_exact_evidence_contract():
    selected = tuple(
        scenario for scenario in GOLDEN_SCENARIOS if scenario.scenario_id in BOUNDARY_IDS
    )

    suite = run_suite(selected, mode="offline")

    assert suite.exit_code == 0
    assert suite.passed == 10
    assert {
        result.scenario_id: (result.detail, result.evidence) for result in suite.results
    } == EXPECTED_BOUNDARY_EVIDENCE


def _track_outside_fixture_roots(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    roots: list[Path] = []

    class TrackingTemporaryDirectory:
        def __init__(self, *args, **kwargs) -> None:
            self._temporary_directory = TemporaryDirectory(*args, **kwargs)

        def __enter__(self) -> str:
            directory = self._temporary_directory.__enter__()
            roots.append(Path(directory))
            return directory

        def __exit__(self, *args) -> None:
            self._temporary_directory.__exit__(*args)

    monkeypatch.setattr(cases, "TemporaryDirectory", TrackingTemporaryDirectory)
    return roots


@pytest.mark.parametrize(
    "runner",
    [
        cases.run_g06_offline,
        cases.run_g58_offline,
        cases.run_g59_offline,
        cases.run_g324_offline,
    ],
)
def test_out_of_root_fixture_roots_are_independent_and_cleaned_after_repeat(
    tmp_path, monkeypatch, runner
):
    roots = _track_outside_fixture_roots(monkeypatch)
    workdir = tmp_path / "scenario"

    runner(workdir)
    runner(workdir)

    assert len(roots) == 2
    assert roots[0] != roots[1]
    assert all(not root.exists() for root in roots)


@pytest.mark.parametrize(
    "runner",
    [
        cases.run_g06_offline,
        cases.run_g58_offline,
        cases.run_g59_offline,
        cases.run_g324_offline,
    ],
)
def test_out_of_root_fixture_root_is_cleaned_after_golden_check_error(
    tmp_path, monkeypatch, runner
):
    roots = _track_outside_fixture_roots(monkeypatch)

    def force_check_failure(*_args, **_kwargs) -> None:
        raise GoldenCheckError("forced fixture failure")

    monkeypatch.setattr(cases, "require", force_check_failure)

    with pytest.raises(GoldenCheckError, match="forced fixture failure"):
        runner(tmp_path / "scenario")

    assert len(roots) == 1
    assert not roots[0].exists()


@pytest.mark.parametrize(
    ("runner", "old_fixed_name"),
    [
        (cases.run_g59_offline, "g59-outside-write.txt"),
        (cases.run_g324_offline, "g324-outside-write.txt"),
    ],
)
def test_out_of_root_write_cases_do_not_depend_on_stale_fixed_siblings(
    tmp_path, runner, old_fixed_name
):
    stale_target = tmp_path / old_fixed_name
    stale_target.write_text("preexisting stale sibling", encoding="utf-8")

    evidence = runner(tmp_path / "scenario")

    assert stale_target.read_text(encoding="utf-8") == "preexisting stale sibling"
    assert evidence.evidence["target_exists"] is False


def test_g330_guards_the_public_hop_before_blocking_the_private_redirect(tmp_path):
    evidence = cases.run_g330_offline(tmp_path).evidence

    assert evidence["resolved_hosts"] == ["public.example", "private.example"]
    assert evidence["public_connection_calls"] == 1
    assert evidence["private_connection_calls"] == 0


def test_g355_rejects_an_injected_optional_tool_label(tmp_path, monkeypatch):
    from forgeagent.mcp_manager import MCPToolInfo

    list_tools = cases.MCPManager.list_tools

    def inject_optional_tool(manager):
        return [
            *list_tools(manager),
            MCPToolInfo(server="optional", name="add", description="Injected optional tool"),
        ]

    monkeypatch.setattr(cases.MCPManager, "list_tools", inject_optional_tool)

    with pytest.raises(GoldenCheckError, match="tool labels"):
        cases.run_g355_offline(tmp_path)


def test_default_runner_completes_all_twenty_cases():
    suite = run_suite(GOLDEN_SCENARIOS, mode="offline")

    assert suite.exit_code == 0
    assert suite.total == 20
    assert suite.passed == 20
    assert suite.failed == 0
    assert suite.pass_rate == 100.0


def test_g14_allows_cold_worker_start_after_timeout(tmp_path, monkeypatch):
    original_popen = cases.subprocess.Popen
    worker_count = 0

    def delayed_second_worker(command, *args, **kwargs):
        nonlocal worker_count
        if "forgeagent._sandbox_worker" in " ".join(str(part) for part in command):
            worker_count += 1
            if worker_count == 2:
                command = [
                    command[0],
                    "-I",
                    "-c",
                    "import runpy,time; time.sleep(0.3); "
                    "runpy.run_module('forgeagent._sandbox_worker', run_name='__main__')",
                ]
        return original_popen(command, *args, **kwargs)

    monkeypatch.setattr(cases.subprocess, "Popen", delayed_second_worker)

    evidence = cases.run_g14_offline(tmp_path)

    assert worker_count == 2
    assert evidence.evidence["successful_round"] == 2


def test_offline_main_runs_unpatched_twenty_case_core_and_writes_shared_summary(tmp_path):
    output_dir = tmp_path / "offline-core"

    assert main(["--output-dir", str(output_dir)]) == 0

    payload = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
    markdown = (output_dir / "report.md").read_text(encoding="utf-8")
    assert payload["mode"] == "offline"
    assert payload["total"] == 20
    assert payload["passed"] == 20
    assert payload["failed"] == 0
    assert payload["pass_rate"] == 100.0
    assert (
        f"Summary: {payload['passed']}/{payload['total']} passed "
        f"({payload['pass_rate']:.1f}%)" in markdown
    )
    assert markdown.count("| PASS |") == payload["passed"]
    assert "| FAIL |" not in markdown


def test_g01_rejects_string_encoded_numbers(tmp_path):
    result = tmp_path / "result.json"
    code = (
        "import json\n"
        f"with open({str(result)!r}, 'w', encoding='utf-8') as handle:\n"
        "    json.dump({'sum': '60', 'mean': '20'}, handle)\n"
    )
    client = MockClient(script=[cases._reply(cases._exec(code)), cases._reply(cases._done())])

    with pytest.raises(GoldenCheckError, match="built-in numeric"):
        cases._run_g01_case(tmp_path, client)


@pytest.mark.parametrize(
    "second_block",
    [
        "int(utils.get_state('subtotal'))\nprint(50)",
        "utils.get_state('subtotal') + 8\nprint(50)",
    ],
)
def test_g05_rejects_dead_state_use_followed_by_a_hard_coded_result(tmp_path, second_block):
    client = MockClient(
        script=[
            cases._reply(cases._exec(cases._g05_first_block(tmp_path), name="compute")),
            cases._reply(cases._exec(second_block, name="finish")),
            cases._reply(cases._done()),
        ]
    )

    with pytest.raises(GoldenCheckError, match="causal replay"):
        cases._run_g05_case(tmp_path, client)


def test_g05_rejects_conditional_hardcode_with_counterfactual_fallback(tmp_path):
    second_block = (
        "value = int(utils.get_state('subtotal'))\nprint(50 if value == 42 else value + 8)"
    )
    client = MockClient(
        script=[
            cases._reply(cases._exec(cases._g05_first_block(tmp_path), name="compute")),
            cases._reply(cases._exec(second_block, name="finish")),
            cases._reply(cases._done()),
        ]
    )

    with pytest.raises(GoldenCheckError, match="sink"):
        cases._run_g05_case(tmp_path, client)


def test_g05_model_code_cannot_call_the_recorder_or_forge_sink_evidence(tmp_path):
    backend = cases._ObservedRestrictedBackend(tmp_path)
    runtime = Runtime()
    first = backend.execute(cases._g05_first_block(tmp_path), runtime)
    second = backend.execute(
        "value = int(utils.get_state('subtotal'))\n"
        "_golden_record('sink', 50)\n"
        "print(50 if value == 42 else value + 8)",
        runtime,
    )

    assert first.success
    assert not second.success
    assert "NameError" in (second.error or "")
    assert "_golden_record" in (second.error or "")
    assert not [item for item in backend.observations() if item.get("kind") == "sink"]


def test_g05_causal_probe_does_not_leave_directories_or_symlinks_in_workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    probe_directory = tmp_path / "probe-only-directory"
    probe_symlink = tmp_path / "probe-only-symlink"
    second_block = (
        "from pathlib import Path\n"
        "import os\n"
        "value = int(utils.get_state('subtotal'))\n"
        "if value != 42:\n"
        "    Path('probe-only-directory').mkdir(exist_ok=True)\n"
        "    os.symlink('probe-only-directory', 'probe-only-symlink')\n"
        "print(50 if value == 42 else value + 8)"
    )
    client = MockClient(
        script=[
            cases._reply(cases._exec(cases._g05_first_block(tmp_path), name="compute")),
            cases._reply(cases._exec(second_block, name="finish")),
            cases._reply(cases._done()),
        ]
    )

    try:
        with pytest.raises(GoldenCheckError):
            cases._run_g05_case(tmp_path, client)
        probe_artifacts_persisted = probe_directory.exists() or probe_symlink.is_symlink()
    finally:
        if probe_symlink.is_symlink():
            probe_symlink.unlink()
        if probe_directory.exists():
            probe_directory.rmdir()

    assert not probe_artifacts_persisted


def test_g08_rejects_editing_the_provided_test_instead_of_fixing_source(tmp_path):
    code = (
        "from pathlib import Path\n"
        f"Path({str(tmp_path / 'test_calculator.py')!r}).write_text("
        "\"print('tests passed')\\n\", encoding='utf-8')\n"
    )
    client = MockClient(script=[cases._reply(cases._exec(code)), cases._reply(cases._done())])

    with pytest.raises(GoldenCheckError, match="test file hash"):
        cases._run_g08_case(tmp_path, client)


def test_g08_rejects_source_that_exits_zero_before_assertions_complete(tmp_path):
    source = tmp_path / "calculator.py"
    code = (
        "from pathlib import Path\n"
        f"Path({str(source)!r}).write_text("
        "'import os\\nos._exit(0)\\n', encoding='utf-8')\n"
    )
    client = MockClient(script=[cases._reply(cases._exec(code)), cases._reply(cases._done())])

    with pytest.raises(GoldenCheckError, match="completion witness"):
        cases._run_g08_case(tmp_path, client)


def test_g08_restricted_test_execution_blocks_out_of_root_source_side_effect(tmp_path):
    workdir = tmp_path / "scenario"
    external_target = tmp_path / "outside.txt"
    external_target.write_text("unchanged", encoding="utf-8")
    source = workdir / "calculator.py"
    generated_source = (
        "from pathlib import Path\n"
        f"Path({str(external_target)!r}).write_text('changed', encoding='utf-8')\n"
        "def clamp(value, lower, upper):\n"
        "    return min(max(value, lower), upper)\n"
    )
    code = (
        "from pathlib import Path\n"
        f"Path({str(source)!r}).write_text({generated_source!r}, encoding='utf-8')\n"
    )
    client = MockClient(script=[cases._reply(cases._exec(code)), cases._reply(cases._done())])

    with pytest.raises(GoldenCheckError, match="provided tests did not pass"):
        cases._run_g08_case(workdir, client)

    assert external_target.read_text(encoding="utf-8") == "unchanged"


def test_g08_test_timeout_is_fixed_and_restricted_worker_is_reaped(tmp_path):
    test_file = tmp_path / "hang.py"
    pid_file = tmp_path / "worker.pid"
    test_file.write_text(
        "import os\n"
        "from pathlib import Path\n"
        f"Path({str(pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
        "while True:\n"
        "    pass\n",
        encoding="utf-8",
    )

    with pytest.raises(GoldenCheckError, match="G08 test execution timed out"):
        cases._run_python_test(tmp_path, test_file.name, timeout_seconds=1.0)

    worker_pid = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            os.kill(worker_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.01)
    else:
        pytest.fail(f"restricted worker {worker_pid} survived the G08 timeout")


def test_g13_rejects_when_failed_tool_feedback_is_not_sent_to_round_two(tmp_path, monkeypatch):
    from forgeagent.step import Step

    render_feedback = Step._render_feedback

    def suppress_failed_tool_feedback(self, round_result):
        if any(not outcome.success for outcome in round_result.outcomes):
            return ""
        return render_feedback(self, round_result)

    monkeypatch.setattr(Step, "_render_feedback", suppress_failed_tool_feedback)

    with pytest.raises(GoldenCheckError, match="round 2.*failed tool feedback"):
        cases.run_g13_offline(tmp_path)


@pytest.mark.parametrize(
    ("runner_name", "initial_name", "replacement_name", "message"),
    [
        (
            "_run_g15_case",
            "G15_INITIAL_CODE",
            "G15_EXPECTED_CODE",
            "G15 must invoke Edit",
        ),
        (
            "_run_g27_case",
            "G27_INITIAL_CODE",
            "G27_EXPECTED_CODE",
            "G27 must invoke Edit",
        ),
    ],
)
def test_edit_cases_reject_whole_block_replacement(
    tmp_path, runner_name, initial_name, replacement_name, message
):
    case_runner = getattr(cases, runner_name)
    initial_code = getattr(cases, initial_name)
    replacement_code = getattr(cases, replacement_name)
    client = MockClient(
        script=[
            cases._reply(cases._exec(initial_code, name="target")),
            cases._reply(cases._exec(replacement_code, name="target")),
            cases._reply(cases._done()),
        ]
    )

    with pytest.raises(GoldenCheckError, match=message):
        case_runner(tmp_path, client)


@pytest.mark.parametrize(
    ("runner_name", "initial_name", "replacement_name", "small_old", "small_new"),
    [
        (
            "_run_g15_case",
            "G15_INITIAL_CODE",
            "G15_EXPECTED_CODE",
            "DEFAULT_TIMEOUT = 10",
            "DEFAULT_TIMEOUT = 15",
        ),
        (
            "_run_g27_case",
            "G27_INITIAL_CODE",
            "G27_EXPECTED_CODE",
            "value < limit",
            "value <= limit",
        ),
    ],
)
def test_edit_cases_reject_whole_block_edit_arguments(
    tmp_path, runner_name, initial_name, replacement_name, small_old, small_new
):
    case_runner = getattr(cases, runner_name)
    initial_code = getattr(cases, initial_name)
    replacement_code = getattr(cases, replacement_name)
    script = [
        cases._reply(cases._exec(initial_code, name="target")),
        cases._reply(cases._edit("target", initial_code, replacement_code)),
    ]
    if runner_name == "_run_g27_case":
        script.append(cases._reply(cases._exec(name="target")))
    script.append(cases._reply(cases._done()))

    with pytest.raises(
        GoldenCheckError,
        match=f"exact Edit arguments.*{small_old}.*{small_new}",
    ):
        case_runner(tmp_path, MockClient(script=script))


def test_g27_rejects_successful_unrelated_exec_after_exact_edit(tmp_path):
    client = MockClient(
        script=[
            cases._reply(cases._exec(cases.G27_INITIAL_CODE, name="target")),
            cases._reply(cases._edit("target", "value < limit", "value <= limit")),
            cases._reply(cases._exec("print('unrelated success')", name="unrelated")),
            cases._reply(cases._done()),
        ]
    )

    with pytest.raises(GoldenCheckError, match="successful post-Edit Exec.*target"):
        cases._run_g27_case(tmp_path, client)


def test_g43_rejects_float_counts(tmp_path):
    result = tmp_path / "top.json"
    top_n = [
        ["forge", 4.0],
        ["code", 2.0],
        ["tests", 2.0],
        ["agents", 1.0],
        ["guide", 1.0],
    ]
    code = (
        "import json\n"
        f"with open({str(result)!r}, 'w', encoding='utf-8') as handle:\n"
        f"    json.dump({top_n!r}, handle)\n"
    )
    client = MockClient(script=[cases._reply(cases._exec(code)), cases._reply(cases._done())])

    with pytest.raises(GoldenCheckError, match="exact list shape"):
        cases._run_g43_case(tmp_path, client)


def test_case_judges_do_not_use_python_assert_statements():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(cases))

    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]


def test_manifest_uses_approved_titles_for_boundary_scenarios():
    titles = {scenario.scenario_id: scenario.title for scenario in GOLDEN_SCENARIOS}

    assert titles["G43"] == "Text word-frequency Top-N"
    assert titles["G58"] == "Restricted out-of-root read"
    assert titles["G59"] == "Restricted out-of-root write"
    assert titles["G324"] == "FileWrite out-of-root rejection"


def test_manifest_preflight_rejects_duplicates_additions_and_catalog_prefix_matches(tmp_path):
    catalog = tmp_path / "catalog.md"
    catalog.write_text("### G010 is not G01\n", encoding="utf-8")
    duplicate = (_scenario("G01"), _scenario("G01"))

    with pytest.raises(GoldenPreflightError):
        validate_manifest(duplicate, catalog_path=catalog)

    complete_catalog = tmp_path / "complete.md"
    complete_catalog.write_text(
        "\n".join(f"### G{number:02d} definition" for number in range(1, 31))
        + "\n| ID | 描述 | Pass 判定 |\n| --- | --- | --- |\n"
        + "\n".join(
            f"| {scenario_id} | candidate | checked |"
            for scenario_id in sorted(EXPECTED_IDS)
            if int(scenario_id[1:]) > 30
        ),
        encoding="utf-8",
    )
    validate_manifest(GOLDEN_SCENARIOS, catalog_path=complete_catalog)


def test_manifest_preflight_rejects_coverage_reference_without_g01_definition(tmp_path):
    coverage_matrix = "| ID | Category |\n| --- | --- |\n| G01 | core |\n"
    core_headings = "\n".join(f"### G{number:02d} definition" for number in range(2, 31))
    candidate_table = "| ID | 描述 | Pass 判定 |\n| --- | --- | --- |\n" + "\n".join(
        f"| G{number:02d} | candidate | checked |" for number in range(31, 421)
    )
    catalog = tmp_path / "catalog.md"
    catalog.write_text(
        coverage_matrix + core_headings + "\n" + candidate_table,
        encoding="utf-8",
    )
    with pytest.raises(GoldenPreflightError, match="missing G01"):
        validate_manifest(GOLDEN_SCENARIOS, catalog_path=catalog)


def test_run_suite_returns_success_and_failure_exit_codes_and_shared_summary(tmp_path):
    passed = run_suite((_scenario("G01"),), mode="offline")
    failed = run_suite((_scenario("G01", _fail),), mode="offline")

    assert passed.exit_code == 0
    assert failed.exit_code == 1
    assert failed.failed == 1

    json_path, markdown_path = write_reports(failed, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["total"] == failed.total
    assert payload["passed"] == failed.passed
    assert payload["failed"] == failed.failed
    assert f"{failed.passed}/{failed.total}" in markdown_path.read_text(encoding="utf-8")
    assert render_markdown(failed) == markdown_path.read_text(encoding="utf-8")


def test_preflight_failure_does_not_create_an_output_directory(tmp_path, monkeypatch):
    output_dir = tmp_path / "not-created"
    monkeypatch.setattr("tests.golden.runner._load_manifest", lambda: (_scenario("G01"),))

    assert main(["--output-dir", str(output_dir)]) == 2
    assert not output_dir.exists()


class _IntegerEnum(IntEnum):
    VALUE = 1


class _IntegerSubclass(int):
    pass


class _ListSubclass(list):
    pass


class _GoldenEvidenceSubclass(GoldenEvidence):
    pass


def test_golden_evidence_subclass_is_a_fixed_failure_and_later_scenarios_continue(tmp_path):
    def invalid(_: Path) -> GoldenEvidence:
        return _GoldenEvidenceSubclass(detail="checked", evidence={"value": "ok"})

    suite = run_suite((_scenario("G01", invalid), _scenario("G03")), mode="offline")

    assert suite.failed == 1
    assert suite.passed == 1
    assert suite.results[0].detail == "invalid scenario result"
    assert suite.results[0].evidence == {}
    write_reports(suite, tmp_path)


def test_non_string_detail_is_a_fixed_failure_and_reports_continue(tmp_path):
    def invalid(_: Path) -> GoldenEvidence:
        return GoldenEvidence(detail=Path("secret-detail"), evidence={"value": "ok"})

    suite = run_suite((_scenario("G01", invalid), _scenario("G03")), mode="offline")

    assert suite.failed == 1
    assert suite.passed == 1
    assert suite.results[0].detail == "invalid evidence"
    assert suite.results[0].evidence == {}
    json_path, markdown_path = write_reports(suite, tmp_path)
    assert "secret-detail" not in json_path.read_text(encoding="utf-8")
    assert "secret-detail" not in markdown_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "evidence",
    [
        {"value": Path("not-json")},
        {"value": ("tuple",)},
        {1: "non-string key"},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": _IntegerEnum.VALUE},
        {"value": _IntegerSubclass(1)},
        {"value": _ListSubclass(["subclass"])},
    ],
)
def test_invalid_evidence_fails_only_its_scenario_and_reports_without_repr(tmp_path, evidence):
    class _SecretObject:
        def __repr__(self) -> str:
            return "secret-repr-must-not-appear"

    def invalid(_: Path) -> GoldenEvidence:
        return GoldenEvidence(detail="invalid", evidence=evidence)

    suite = run_suite((_scenario("G01", invalid), _scenario("G03")), mode="offline")

    assert suite.failed == 1
    assert suite.passed == 1
    assert suite.results[0].detail == "invalid evidence"
    assert suite.results[0].evidence == {}
    json_path, markdown_path = write_reports(suite, tmp_path)
    assert "secret-repr-must-not-appear" not in json_path.read_text(encoding="utf-8")
    assert "secret-repr-must-not-appear" not in markdown_path.read_text(encoding="utf-8")


def test_report_replaces_existing_files_atomically(tmp_path):
    suite = run_suite((_scenario("G01"),), mode="offline")
    json_path, markdown_path = write_reports(suite, tmp_path)
    json_path.write_text("stale", encoding="utf-8")
    markdown_path.write_text("stale", encoding="utf-8")

    replaced_json, replaced_markdown = write_reports(suite, tmp_path)

    assert replaced_json == json_path
    assert replaced_markdown == markdown_path
    assert json.loads(json_path.read_text(encoding="utf-8"))["schema"] == "forgeagent.golden.v1"
    assert markdown_path.read_text(encoding="utf-8").startswith("# ForgeAgent Golden Validation")


def test_each_report_is_replaced_by_a_same_directory_temporary_file(tmp_path, monkeypatch):
    suite = run_suite((_scenario("G01"),), mode="offline")
    replacements: list[tuple[Path, Path]] = []
    actual_replace = os.replace

    def observe_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        source_path = Path(source)
        target_path = Path(target)
        assert source_path.parent == target_path.parent
        assert source_path != target_path
        assert source_path.exists()
        replacements.append((source_path, target_path))
        actual_replace(source, target)

    monkeypatch.setattr("tests.golden.runner.os.replace", observe_replace)
    write_reports(suite, tmp_path)

    assert [target.name for _, target in replacements] == ["results.json", "report.md"]
    assert all(not source.exists() for source, _ in replacements)
    assert not list(tmp_path.glob(".*"))


@pytest.mark.parametrize("model_id", ["../../escape", "..", "gpt/5", "模型!@#", "x" * 80])
def test_real_output_directory_is_contained_and_bounded(tmp_path, model_id):
    root = tmp_path / "artifacts" / "golden" / "real"
    directory = default_output_dir(
        mode="real", model_id=model_id, artifact_root=tmp_path / "artifacts"
    )

    assert directory.is_relative_to(root)
    assert len(directory.name.rsplit("-", 1)[0]) <= 48


def test_normalized_model_collisions_receive_distinct_digest_directories(tmp_path):
    first = default_output_dir(mode="real", model_id="gpt/5", artifact_root=tmp_path / "artifacts")
    second = default_output_dir(mode="real", model_id="gpt:5", artifact_root=tmp_path / "artifacts")

    assert first != second
    assert first.parent == second.parent


def test_offline_main_restores_home_variables_after_normal_and_runner_failure(
    tmp_path, monkeypatch
):
    original = {name: os.environ.get(name) for name in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME")}
    output_dir = tmp_path / "normal"
    observed_homes: list[dict[str, str | None]] = []

    def observe_isolated_imports(_user_path: Path) -> None:
        observed_homes.append({name: os.environ.get(name) for name in original})

    monkeypatch.setattr(
        "tests.golden.runner._load_offline_configuration_modules", observe_isolated_imports
    )
    assert main(["--output-dir", str(output_dir)]) == 0
    assert observed_homes[0] != original
    assert {name: os.environ.get(name) for name in original} == original

    def raise_from_suite(*_args, **_kwargs):
        raise RuntimeError("runner exploded")

    monkeypatch.setattr("tests.golden.runner.run_suite", raise_from_suite)
    with pytest.raises(RuntimeError, match="runner exploded"):
        main(["--output-dir", str(tmp_path / "failure")])
    assert {name: os.environ.get(name) for name in original} == original


def test_offline_reports_run_inside_isolated_home_and_restore_after_report_error(
    tmp_path, monkeypatch
):
    names = ("HOME", "USERPROFILE", "XDG_CONFIG_HOME")
    original = {name: os.environ.get(name) for name in names}
    observed: list[dict[str, str | None]] = []
    actual_write_reports = write_reports

    monkeypatch.setattr(
        "tests.golden.runner._load_offline_configuration_modules",
        lambda _user_path: None,
    )

    def observe_write_reports(suite, output_dir):
        observed.append({name: os.environ.get(name) for name in names})
        return actual_write_reports(suite, output_dir)

    monkeypatch.setattr("tests.golden.runner.write_reports", observe_write_reports)
    assert main(["--output-dir", str(tmp_path / "normal")]) == 0
    assert observed[-1] != original
    assert {name: os.environ.get(name) for name in names} == original

    def fail_write_reports(suite, output_dir):
        del suite, output_dir
        observed.append({name: os.environ.get(name) for name in names})
        raise OSError("report write failed")

    monkeypatch.setattr("tests.golden.runner.write_reports", fail_write_reports)
    assert main(["--output-dir", str(tmp_path / "failure")]) == 2
    assert observed[-1] != original
    assert {name: os.environ.get(name) for name in names} == original


def test_offline_main_calls_real_suite_inside_isolated_home_and_restores_environment(
    tmp_path, monkeypatch
):
    names = ("HOME", "USERPROFILE", "XDG_CONFIG_HOME")
    original = {name: os.environ.get(name) for name in names}
    captured: list[dict[str, str | None]] = []
    real_run_suite = run_suite

    def observe_run_suite(*args, **kwargs):
        captured.append({name: os.environ.get(name) for name in names})
        return real_run_suite(*args, **kwargs)

    monkeypatch.setattr("tests.golden.runner.run_suite", observe_run_suite)

    assert main(["--output-dir", str(tmp_path / "suite")]) == 0
    assert len(captured) == 1
    captured_environment = captured[0]
    isolated_home = captured_environment["HOME"]
    assert isolated_home is not None
    assert all(captured_environment[name] == isolated_home for name in names)
    assert all(captured_environment[name] != original[name] for name in names)
    assert {name: os.environ.get(name) for name in names} == original


def test_offline_configuration_preflight_loads_mcp_config_without_constructing_manager(
    tmp_path,
    monkeypatch,
):
    import forgeagent.mcp_manager as mcp_manager

    calls: list[Path] = []

    def observe_load_mcp_config(*, user_path: Path):
        calls.append(user_path)
        return {}

    class ForbiddenManager:
        def __init__(self, *args, **kwargs):
            raise AssertionError("offline preflight must not construct MCPManager")

    monkeypatch.setattr(mcp_manager, "load_mcp_config", observe_load_mcp_config)
    monkeypatch.setattr(mcp_manager, "MCPManager", ForbiddenManager)
    user_path = tmp_path / ".forgeagent" / "mcp.yaml"

    _load_offline_configuration_modules(user_path)

    assert calls == [user_path]


def test_embedded_offline_main_ignores_preimported_home_bound_mcp_default(
    tmp_path,
    monkeypatch,
):
    import forgeagent.mcp_manager as mcp_manager
    from tests.golden import runner

    preimported_user_path = tmp_path / "preimport-home" / ".forgeagent" / "mcp.yaml"
    preimported_user_path.parent.mkdir(parents=True)
    preimported_user_path.write_text("mcpServers: [not-a-mapping]", encoding="utf-8")
    monkeypatch.setattr(mcp_manager, "DEFAULT_USER_MCP_PATH", preimported_user_path)
    actual_load = mcp_manager.load_mcp_config
    observed: list[tuple[Path | None, Path]] = []

    def observe_load_mcp_config(*args, **kwargs):
        observed.append((kwargs.get("user_path"), Path(os.environ["HOME"])))
        return actual_load(*args, **kwargs)

    monkeypatch.setattr(mcp_manager, "load_mcp_config", observe_load_mcp_config)

    assert runner.main(["--output-dir", str(tmp_path / "offline-report")]) == 0
    assert len(observed) == 1
    user_path, isolated_home = observed[0]
    assert user_path == isolated_home / ".forgeagent" / "mcp.yaml"
    assert user_path != preimported_user_path


def test_standalone_offline_runner_ignores_hostile_parent_mcp_config(tmp_path):
    hostile_home = tmp_path / "hostile-home"
    hostile_config = hostile_home / ".forgeagent" / "mcp.yaml"
    hostile_config.parent.mkdir(parents=True)
    hostile_config.write_text("mcpServers: [not-a-mapping]", encoding="utf-8")
    output_dir = tmp_path / "offline-report"
    environment = os.environ | {"HOME": str(hostile_home), "USERPROFILE": str(hostile_home)}

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.golden.runner",
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "golden preflight failed" not in completed.stdout
    payload = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "offline"
    assert payload["total"] == 20
    assert payload["passed"] == 20
    assert payload["failed"] == 0
    assert payload["pass_rate"] == 100.0


def test_offline_golden_never_calls_evaluator(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "forgeagent.evaluator.run_evaluator",
        lambda *args, **kwargs: pytest.fail("offline golden must not call evaluator"),
    )

    assert main(["--output-dir", str(tmp_path / "offline")]) == 0


def test_real_main_preserves_caller_home_and_parses_custom_model_without_network(tmp_path):
    home = tmp_path / "caller-home"
    config_dir = home / ".forgeagent"
    config_dir.mkdir(parents=True)
    (config_dir / "models.yaml").write_text(
        """\
models:
  local-golden-model:
    client_kind: openai_compatible
    context_window: 32000
    max_output_tokens: 4096
    supports_thinking: false
    thinking_always_on: false
    supports_effort: false
""",
        encoding="utf-8",
    )
    (config_dir / "config.yaml").write_text(
        """\
groups:
  local-golden:
    api_key: local-test-key
    base_url: https://example.invalid/v1
    models: [local-golden-model]
""",
        encoding="utf-8",
    )
    output_dir = tmp_path / "real"
    names = ("HOME", "USERPROFILE", "XDG_CONFIG_HOME")
    environment = os.environ | {name: str(home) for name in names}
    environment["FORGE_GOLDEN_OUTPUT_DIR"] = str(output_dir)
    script = """\
import json
import os
from datetime import UTC, datetime
from tests.golden import runner

names = ("HOME", "USERPROFILE", "XDG_CONFIG_HOME")
before = {name: os.environ.get(name) for name in names}
observed = {}

def no_network_suite(scenarios, *, mode, model, real_client):
    observed["environment"] = {name: os.environ.get(name) for name in names}
    observed["model"] = real_client.capability.model_id
    observed["selected"] = [scenario.scenario_id for scenario in scenarios]
    now = datetime.now(UTC).isoformat()
    return runner.GoldenSuite(
        mode=mode,
        model=model,
        started_at=now,
        finished_at=now,
        results=(),
    )

runner.run_suite = no_network_suite
code = runner.main([
    "--real-model",
    "local-golden-model",
    "--output-dir",
    os.environ["FORGE_GOLDEN_OUTPUT_DIR"],
])
after = {name: os.environ.get(name) for name in names}
print(json.dumps(
    {"code": code, "before": before, "after": after, "observed": observed},
    sort_keys=True,
))
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.splitlines()[-1])
    assert result["code"] == 0
    assert result["before"] == {name: str(home) for name in names}
    assert result["after"] == result["before"]
    assert result["observed"]["environment"] == result["before"]
    assert result["observed"]["model"] == "local-golden-model"
    assert result["observed"]["selected"] == ["G01", "G03", "G08", "G11", "G43"]
    assert json.loads((output_dir / "results.json").read_text(encoding="utf-8"))["mode"] == "real"


@pytest.mark.parametrize("scenario_id", ["G01", "G03", "G08", "G11", "G43"])
def test_real_and_offline_entrypoints_share_one_case_runner(scenario_id, tmp_path, monkeypatch):
    runner_name = f"_run_{scenario_id.lower()}_case"
    offline = getattr(cases, f"run_{scenario_id.lower()}_offline")
    real = getattr(cases, f"run_{scenario_id.lower()}_real")
    observed_clients: list[object] = []
    sentinel = GoldenEvidence(detail="sentinel", evidence={})

    def observe(_workdir, client):
        observed_clients.append(client)
        return sentinel

    monkeypatch.setattr(cases, runner_name, observe)
    real_client = object()

    assert offline(tmp_path / "offline") is sentinel
    assert real(tmp_path / "real", real_client) is sentinel
    assert isinstance(observed_clients[0], MockClient)
    assert observed_clients[1] is real_client


def test_real_preflight_missing_local_credential_exits_two_without_report(tmp_path):
    home = tmp_path / "caller-home"
    config_dir = home / ".forgeagent"
    config_dir.mkdir(parents=True)
    (config_dir / "models.yaml").write_text(
        """models:
  missing-key-model:
    client_kind: openai_compatible
    context_window: 32000
    max_output_tokens: 4096
    supports_thinking: false
    thinking_always_on: false
    supports_effort: false
""",
        encoding="utf-8",
    )
    (config_dir / "config.yaml").write_text(
        """groups:
  local-golden:
    api_key_env: GOLDEN_MISSING_KEY
    models: [missing-key-model]
""",
        encoding="utf-8",
    )
    output_dir = tmp_path / "missing-key-report"
    names = ("HOME", "USERPROFILE", "XDG_CONFIG_HOME")
    environment = os.environ | {name: str(home) for name in names}
    environment.pop("GOLDEN_MISSING_KEY", None)
    script = f"""\
from tests.golden import runner

raise SystemExit(runner.main([
    '--real-model',
    'missing-key-model',
    '--output-dir',
    {str(output_dir)!r},
]))
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 2
    assert "golden preflight failed" in completed.stdout
    assert not output_dir.exists()


def test_provider_auth_rejection_is_runtime_exit_one_with_report(tmp_path, monkeypatch):
    errors = [ClientError(message="rejected", kind="auth", attempts=1) for _ in range(5)]
    monkeypatch.setattr("tests.golden.runner._build_real_client", lambda _model: MockClient(errors))
    output_dir = tmp_path / "provider-rejection"

    assert main(["--real-model", "configured-model", "--output-dir", str(output_dir)]) == 1
    payload = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
    assert payload["total"] == 5
    assert payload["passed"] == 0
    assert payload["failed"] == 5
