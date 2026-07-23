"""Executable trusted-core golden scenarios and their independent judges."""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.response
from dataclasses import dataclass
from email.message import Message as EmailMessage
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

from rich.console import Console

from forgeagent.client import MockClient, ModelClient
from forgeagent.executor import ExecResult, ExecutorBackend, RestrictedBackend
from forgeagent.mcp_manager import MCPManager, MCPServerConfig
from forgeagent.models import (
    AssistantMessage,
    ClientError,
    GenerationParams,
    Message,
    TokenUsage,
)
from forgeagent.policy import CodeAnalyzer
from forgeagent.protocol import EditArgs, ExecArgs, FileWriteArgs, WebFetchArgs, parse
from forgeagent.runtime import Runtime
from forgeagent.skills import SkillDefinition, SkillRegistry
from forgeagent.ssrf_guard import SSRFGuardError, guarded_urlopen
from forgeagent.tools import (
    CodeBlockStore,
    ExecTool,
    FileWriteTool,
    ToolContext,
    WebFetchTool,
)

if TYPE_CHECKING:
    from .manifest import GoldenEvidence


def require(condition: bool, message: str) -> None:
    if not condition:
        from .manifest import GoldenCheckError

        raise GoldenCheckError(message)


def _evidence(*, detail: str, evidence: dict[str, object]) -> GoldenEvidence:
    from .manifest import GoldenEvidence

    return GoldenEvidence(detail=detail, evidence=evidence)


def _invalid(message: str, cause: Exception) -> None:
    from .manifest import GoldenCheckError

    raise GoldenCheckError(message) from cause


def _reply(text: str) -> AssistantMessage:
    return AssistantMessage(content=text, usage=TokenUsage(), stop_reason="end_turn")


def _tool_call(name: str, arguments: dict[str, object]) -> str:
    return f"<!-- ToolCall: {json.dumps({'name': name, 'arguments': arguments})} -->"


def _exec(code: str | None = None, name: str | None = None) -> str:
    arguments: dict[str, object] = {}
    if code is not None:
        arguments["code"] = code
    if name is not None:
        arguments["name"] = name
    return _tool_call("Exec", arguments)


def _edit(name: str, old: str, new: str) -> str:
    return _tool_call("Edit", {"name": name, "old": old, "new": new})


def _done() -> str:
    return "---\ntask_status:\n  completed: true\n  confidence: 0.95\n---\ndone"


@dataclass(frozen=True)
class CandidateResult:
    passed: bool
    first_request: str
    second_request: str
    feedback: str
    round_count: int


def _request_text(messages: list[Message]) -> str:
    return "\n".join(message.content for message in messages if isinstance(message.content, str))


def _feedback_text(messages: list[Message]) -> str:
    content = messages[-1].content
    return content if isinstance(content, str) else ""


def _skill_call(name: str) -> str:
    return _tool_call("Skill", {"name": name})


def _registry_with_skill(marker: str) -> SkillRegistry:
    return SkillRegistry(
        {
            "review-python": SkillDefinition(
                name="review-python",
                trigger="Use when reviewing Python.",
                steps=f"1. {marker}",
                failure_branches="Stop when the diff is unavailable.",
                completion_criteria="All findings are recorded.",
                source="user",
            )
        }
    )


def _candidate_result(client: _RecordingMockClient, outcome) -> CandidateResult:
    return CandidateResult(
        passed=outcome.status.completed,
        first_request=_request_text(client.messages_by_call[0]),
        second_request=_request_text(client.messages_by_call[1]),
        feedback=_feedback_text(client.messages_by_call[1]),
        round_count=len(outcome.rounds),
    )


def run_skill_candidate(tmp_path: Path) -> CandidateResult:
    from forgeagent.task import Task

    client = _RecordingMockClient(script=[_reply(_skill_call("review-python")), _reply(_done())])
    outcome = Task(
        client,
        skills=_registry_with_skill("UNIQUE-SKILL-STEP"),
        allowed_root=str(tmp_path),
    ).run("review the change")
    return _candidate_result(client, outcome)


def run_no_skill_control(tmp_path: Path) -> CandidateResult:
    from forgeagent.task import Task

    client = _RecordingMockClient(script=[_reply(_skill_call("review-python")), _reply(_done())])
    outcome = Task(client, allowed_root=str(tmp_path)).run("review the change")
    return _candidate_result(client, outcome)


def _run_task(workdir: Path, client: ModelClient, goal: str, *, backend=None):
    from forgeagent.task import Task

    workdir.mkdir(parents=True, exist_ok=True)
    execution_backend = backend or RestrictedBackend(allowed_root=str(workdir), secret_values=set())
    task = Task(client, backend=execution_backend, allowed_root=str(workdir))
    return task, task.run(goal)


def _require_completed(outcome, scenario_id: str) -> None:
    require(outcome.status.completed, f"{scenario_id} task did not complete")


def _tool_context(
    workdir: Path,
    *,
    backend: ExecutorBackend | None = None,
    confirmer=None,
    tier: str = "restricted",
) -> ToolContext:
    return ToolContext(
        blocks=CodeBlockStore(),
        backend=backend or RestrictedBackend(allowed_root=str(workdir), secret_values=set()),
        runtime=Runtime(),
        analyzer=CodeAnalyzer(),
        confirmer=confirmer,
        tier=tier,
        allowed_root=str(workdir),
    )


class _GoldenHeaders:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get_content_type(self) -> str:
        return self._content_type


class _GoldenResponse:
    def __init__(self, body: bytes, content_type: str = "text/plain") -> None:
        self._body = body
        self.headers = _GoldenHeaders(content_type)

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def __enter__(self) -> _GoldenResponse:
        return self

    def __exit__(self, *_exc_info) -> bool:
        return False


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    require(bool(rows), f"{path.name} is empty")
    return rows[0], rows[1:]


def _run_g01_case(workdir: Path, client: ModelClient) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    source = workdir / "data.csv"
    result = workdir / "result.json"
    source.write_text("value\n10\n20\n30\n", encoding="utf-8")
    goal = (
        f"Read {source}, calculate the sum and mean of value, and write JSON with keys "
        f"sum and mean to {result}. Execute the work before completing."
    )
    _, outcome = _run_task(workdir, client, goal)
    _require_completed(outcome, "G01")
    require(result.exists(), "G01 result.json was not created")
    try:
        payload = json.loads(result.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _invalid("G01 result.json is invalid", exc)
    require(type(payload) is dict, "G01 result must be a JSON object")
    require(set(payload) == {"sum", "mean"}, "G01 result keys differ")
    require(
        type(payload["sum"]) in (int, float) and type(payload["mean"]) in (int, float),
        "G01 sum and mean must be built-in numeric types",
    )
    require(abs(payload["sum"] - 60.0) < 1e-6, "G01 sum differs")
    require(abs(payload["mean"] - 20.0) < 1e-6, "G01 mean differs")
    return _evidence(
        detail="CSV summary matched",
        evidence={"rows": 3, "sum": 60.0, "mean": 20.0},
    )


def _g01_client(workdir: Path) -> MockClient:
    source = workdir / "data.csv"
    result = workdir / "result.json"
    code = (
        "import csv, json\n"
        f"with open({str(source)!r}, newline='', encoding='utf-8') as handle:\n"
        "    values = [float(row['value']) for row in csv.DictReader(handle)]\n"
        f"with open({str(result)!r}, 'w', encoding='utf-8') as handle:\n"
        "    json.dump({'sum': sum(values), 'mean': sum(values) / len(values)}, handle)\n"
    )
    return MockClient(script=[_reply(_exec(code, "summary")), _reply(_done())])


def run_g01_offline(workdir: Path) -> GoldenEvidence:
    return _run_g01_case(workdir, _g01_client(workdir))


def run_g01_real(workdir: Path, client: ModelClient) -> GoldenEvidence:
    return _run_g01_case(workdir, client)


def _run_g03_case(workdir: Path, client: ModelClient) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    source = workdir / "orders.json"
    result = workdir / "orders.csv"
    source.write_text(
        json.dumps(
            {
                "orders": [
                    {
                        "id": "A-2",
                        "customer": {"name": "Ada", "city": "London"},
                        "items": [
                            {"sku": "P-2", "quantity": 2},
                            {"sku": "P-1", "quantity": 1},
                        ],
                    },
                    {
                        "id": "A-1",
                        "customer": {"name": "Lin", "city": "Shanghai"},
                        "items": [{"sku": "P-3", "quantity": 4}],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    goal = (
        f"Flatten {source} to {result}. Write one row per item with columns in this exact "
        "order: order_id, customer, city, sku, quantity. Preserve order and execute it."
    )
    _, outcome = _run_task(workdir, client, goal)
    _require_completed(outcome, "G03")
    columns, rows = _read_csv(result)
    expected_columns = ["order_id", "customer", "city", "sku", "quantity"]
    expected_rows = [
        ["A-2", "Ada", "London", "P-2", "2"],
        ["A-2", "Ada", "London", "P-1", "1"],
        ["A-1", "Lin", "Shanghai", "P-3", "4"],
    ]
    require(columns == expected_columns, "G03 columns or column order differ")
    require(len(rows) == 3, "G03 row count differs")
    require(rows == expected_rows, "G03 row order or cell content differs")
    return _evidence(
        detail="nested JSON was flattened exactly",
        evidence={"columns": expected_columns, "rows": expected_rows},
    )


def _g03_client(workdir: Path) -> MockClient:
    source = workdir / "orders.json"
    result = workdir / "orders.csv"
    code = (
        "import csv, json\n"
        f"data = json.loads(open({str(source)!r}, encoding='utf-8').read())\n"
        f"with open({str(result)!r}, 'w', newline='', encoding='utf-8') as handle:\n"
        "    writer = csv.writer(handle)\n"
        "    writer.writerow(['order_id', 'customer', 'city', 'sku', 'quantity'])\n"
        "    for order in data['orders']:\n"
        "        for item in order['items']:\n"
        "            writer.writerow([order['id'], order['customer']['name'], "
        "order['customer']['city'], item['sku'], item['quantity']])\n"
    )
    return MockClient(script=[_reply(_exec(code, "flatten")), _reply(_done())])


def run_g03_offline(workdir: Path) -> GoldenEvidence:
    return _run_g03_case(workdir, _g03_client(workdir))


def run_g03_real(workdir: Path, client: ModelClient) -> GoldenEvidence:
    return _run_g03_case(workdir, client)


def _g05_first_block(workdir: Path) -> str:
    counter = workdir / "sideeffect.log"
    return (
        f"with open({str(counter)!r}, 'a', encoding='utf-8') as handle:\n"
        "    handle.write('ran\\n')\n"
        "utils.set_state('subtotal', 6 * 7)"
    )


class _ObservedRestrictedBackend(RestrictedBackend):
    """RestrictedBackend with tests-only, second-block state-use instrumentation."""

    def __init__(self, workdir: Path) -> None:
        super().__init__(allowed_root=str(workdir), secret_values=set())
        self._workdir = workdir
        self._executions = 0
        self._marker = secrets.token_hex(24)
        self._marker_file = workdir / ".g05-observation.jsonl"
        self._probe_state = secrets.randbelow(1_000_000) + 1_000
        self._probe_stdout = ""
        self._probe_observations: list[dict[str, object]] = []

    def execute(self, code: str, runtime: Runtime):
        if self._executions == 1:
            with TemporaryDirectory(prefix="forgeagent-g05-replay-") as replay_directory:
                replay_root = Path(replay_directory)
                replay_marker_file = replay_root / ".g05-causal-probe.jsonl"
                probe_backend = RestrictedBackend(
                    allowed_root=str(replay_root), secret_values=set()
                )
                probe_runtime = Runtime({"subtotal": self._probe_state})
                probe = probe_backend.execute(
                    self._instrument(
                        code,
                        marker_file=replay_marker_file,
                        execution_root=replay_root,
                    ),
                    probe_runtime,
                )
                self._probe_stdout = probe.stdout.strip() if probe.success else ""
                self._probe_observations = self._read_observations(replay_marker_file)
        self._executions += 1
        if self._executions == 2:
            code = self._instrument(
                code,
                marker_file=self._marker_file,
                execution_root=self._workdir,
            )
        return super().execute(code, runtime)

    def _instrument(self, code: str, *, marker_file: Path, execution_root: Path) -> str:
        return f"""
def _golden_execute_model_block():
    import json
    import os

    marker_file = {str(marker_file)!r}
    marker = {self._marker!r}
    original_get_state = utils.get_state

    def record(kind, payload):
        with open(marker_file, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(
                {{'marker': marker, 'kind': kind, 'payload': payload}}
            ) + '\\n')

    class TaintedNumber:
        def __init__(self, value, derived=False):
            self.value = value
            self.derived = derived

        def _used(self):
            record('use', self.value)

        def __add__(self, other):
            self._used()
            return TaintedNumber(self.value + other, derived=True)

        def __radd__(self, other):
            self._used()
            return TaintedNumber(other + self.value, derived=True)

        def __int__(self):
            self._used()
            return int(self.value)

        def __float__(self):
            self._used()
            return float(self.value)

        def __str__(self):
            if self.derived:
                record('sink', self.value)
            else:
                self._used()
            return str(self.value)

    class WrappedUtils:
        def get_state(self, key, default=None):
            value = original_get_state(key, default)
            record('read', {{'key': key, 'value': value}})
            return TaintedNumber(value)

    os.chdir({str(execution_root)!r})
    model_globals = {{
        '__builtins__': __builtins__,
        '__name__': '__forgeagent_block__',
        'utils': WrappedUtils(),
    }}
    exec(compile({code!r}, '<forgeagent-model-block>', 'exec'), model_globals, model_globals)

_golden_execute_model_block()
del _golden_execute_model_block
"""

    def _read_observations(self, marker_file: Path) -> list[dict[str, object]]:
        if not marker_file.exists():
            return []
        return [
            value
            for value in (
                json.loads(line) for line in marker_file.read_text(encoding="utf-8").splitlines()
            )
            if value.get("marker") == self._marker
        ]

    def observations(self) -> list[dict[str, object]]:
        return self._read_observations(self._marker_file)


def _run_g05_case(workdir: Path, client: ModelClient) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    backend = _ObservedRestrictedBackend(workdir)
    task, outcome = _run_task(
        workdir,
        client,
        "Compute 6 * 7 once with a file side effect, save it as state subtotal, then read "
        "that state in a separate block, add 8, print the result, and complete.",
        backend=backend,
    )
    _require_completed(outcome, "G05")
    require(len(outcome.rounds) >= 2, "G05 did not execute two blocks")
    second = outcome.rounds[1].outcomes
    require(len(second) == 1 and second[0].exec_result is not None, "G05 second block missing")
    stdout = second[0].exec_result.stdout.strip()
    require(stdout == "50", "G05 output differs from 50")
    require(task.runtime.get_state("subtotal") == 42, "G05 state differs from 42")
    counter = workdir / "sideeffect.log"
    require(counter.exists(), "G05 side effect file is missing")
    require(
        counter.read_text(encoding="utf-8").splitlines() == ["ran"], "G05 side effect count differs"
    )
    observations = backend.observations()
    reads = [item for item in observations if item.get("kind") == "read"]
    uses = [item for item in observations if item.get("kind") == "use"]
    require(
        len(reads) == 1 and reads[0].get("payload") == {"key": "subtotal", "value": 42},
        "G05 state read marker differs",
    )
    require(len(uses) == 1 and uses[0].get("payload") == 42, "G05 returned value use missing")
    probe_reads = [item for item in backend._probe_observations if item.get("kind") == "read"]
    probe_uses = [item for item in backend._probe_observations if item.get("kind") == "use"]
    require(
        len(probe_reads) == 1
        and probe_reads[0].get("payload") == {"key": "subtotal", "value": backend._probe_state},
        "G05 causal replay state read marker differs",
    )
    require(
        len(probe_uses) == 1 and probe_uses[0].get("payload") == backend._probe_state,
        "G05 causal replay returned value use missing",
    )
    require(
        backend._probe_stdout == str(backend._probe_state + 8),
        "G05 causal replay output did not follow alternate state",
    )
    sinks = [item for item in observations if item.get("kind") == "sink"]
    probe_sinks = [item for item in backend._probe_observations if item.get("kind") == "sink"]
    require(
        len(sinks) == 1 and sinks[0].get("payload") == 50,
        "G05 canonical sink marker differs",
    )
    require(
        len(probe_sinks) == 1 and probe_sinks[0].get("payload") == backend._probe_state + 8,
        "G05 causal replay sink marker differs",
    )
    return _evidence(
        detail="cross-block state was read and used",
        evidence={
            "state": 42,
            "output": 50,
            "side_effects": 1,
            "state_reads": 1,
            "returned_value_uses": 1,
            "causal_delta": 8,
        },
    )


def run_g05_offline(workdir: Path) -> GoldenEvidence:
    client = MockClient(
        script=[
            _reply(_exec(_g05_first_block(workdir), "compute")),
            _reply(_exec("print(utils.get_state('subtotal') + 8)", "finish")),
            _reply(_done()),
        ]
    )
    return _run_g05_case(workdir, client)


G08_INITIAL_CODE = """def clamp(value, lower, upper):
    return min(max(value, lower), upper - 1)
"""
G08_TEST_CODE = """from calculator import clamp

if clamp(10, 0, 10) != 10:
    raise SystemExit(1)
if clamp(-2, 0, 10) != 0:
    raise SystemExit(1)
print("G08 assertions completed")
"""
G08_TEST_WITNESS = "G08 assertions completed"


def _run_python_test(workdir: Path, filename: str, *, timeout_seconds: float = 5.0) -> ExecResult:
    test_path = workdir / filename
    code = (
        "import os, runpy, sys\n"
        f"os.chdir({str(workdir)!r})\n"
        f"sys.path.insert(0, {str(workdir)!r})\n"
        f"runpy.run_path({str(test_path)!r}, run_name='__main__')\n"
    )
    result = RestrictedBackend(
        allowed_root=str(workdir),
        timeout_seconds=timeout_seconds,
        secret_values=set(),
    ).execute(code, Runtime())
    timeout_error = f"execution timed out after {timeout_seconds}s (process killed)"
    require(result.error != timeout_error, "G08 test execution timed out")
    return result


def _run_g08_case(workdir: Path, client: ModelClient) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    source = workdir / "calculator.py"
    test_file = workdir / "test_calculator.py"
    source.write_text(G08_INITIAL_CODE, encoding="utf-8")
    test_file.write_text(G08_TEST_CODE, encoding="utf-8")
    before_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()
    before_result = _run_python_test(workdir, test_file.name)
    require(not before_result.success, "G08 provided tests did not fail before the fix")
    goal = (
        f"Fix the boundary bug in {source} so the provided test {test_file} passes. "
        "Do not modify the test file. Execute the fix and verification before completing."
    )
    _, outcome = _run_task(workdir, client, goal)
    _require_completed(outcome, "G08")
    after_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()
    require(after_hash == before_hash, "G08 test file hash changed")
    after_result = _run_python_test(workdir, test_file.name)
    if after_result.error and "sandbox worker failed (exit 0)" in after_result.error:
        require(False, "G08 test completion witness is missing")
    require(after_result.success, "G08 provided tests did not pass after the fix")
    require(
        after_result.stdout.splitlines() == [G08_TEST_WITNESS],
        "G08 test completion witness is missing",
    )
    require(
        hashlib.sha256(test_file.read_bytes()).hexdigest() == before_hash,
        "G08 test file hash changed",
    )
    return _evidence(
        detail="bug fix preserved the provided tests",
        evidence={
            "before_exit_code": 1,
            "after_exit_code": 0,
            "test_hash_unchanged": True,
        },
    )


def _g08_client(workdir: Path) -> MockClient:
    source = workdir / "calculator.py"
    code = (
        "from pathlib import Path\n"
        f"path = Path({str(source)!r})\n"
        "text = path.read_text(encoding='utf-8')\n"
        "path.write_text(text.replace('upper - 1', 'upper'), encoding='utf-8')\n"
        "print('source fixed')\n"
    )
    return MockClient(script=[_reply(_exec(code, "fix")), _reply(_done())])


def run_g08_offline(workdir: Path) -> GoldenEvidence:
    return _run_g08_case(workdir, _g08_client(workdir))


def run_g08_real(workdir: Path, client: ModelClient) -> GoldenEvidence:
    return _run_g08_case(workdir, client)


def _run_g11_case(workdir: Path, client: ModelClient) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    first = workdir / "part-a.csv"
    second = workdir / "part-b.csv"
    result = workdir / "merged.csv"
    first.write_text("id,name,score\n3,Cora,30\n1,Ada,10\n", encoding="utf-8")
    second.write_text("id,name,score\n2,Ben,20\n1,Ada,10\n", encoding="utf-8")
    goal = (
        f"Merge {first} and {second} into {result}; deduplicate by id, sort by numeric id, "
        "and preserve columns id,name,score in that exact order. Execute it."
    )
    _, outcome = _run_task(workdir, client, goal)
    _require_completed(outcome, "G11")
    columns, rows = _read_csv(result)
    expected_columns = ["id", "name", "score"]
    expected_rows = [["1", "Ada", "10"], ["2", "Ben", "20"], ["3", "Cora", "30"]]
    require(columns == expected_columns, "G11 columns differ")
    require(len(rows) == 3, "G11 deduplicated row count differs")
    require({row[0] for row in rows} == {"1", "2", "3"}, "G11 primary keys differ")
    require(rows == expected_rows, "G11 row order or cells differ")
    return _evidence(
        detail="CSV rows were merged and deduplicated exactly",
        evidence={"columns": expected_columns, "rows": expected_rows},
    )


def _g11_client(workdir: Path) -> MockClient:
    first = workdir / "part-a.csv"
    second = workdir / "part-b.csv"
    result = workdir / "merged.csv"
    code = (
        "import csv\n"
        "by_id = {}\n"
        f"for path in [{str(first)!r}, {str(second)!r}]:\n"
        "    with open(path, newline='', encoding='utf-8') as handle:\n"
        "        for row in csv.DictReader(handle):\n"
        "            by_id.setdefault(row['id'], row)\n"
        f"with open({str(result)!r}, 'w', newline='', encoding='utf-8') as handle:\n"
        "    writer = csv.DictWriter(handle, fieldnames=['id', 'name', 'score'])\n"
        "    writer.writeheader()\n"
        "    writer.writerows(by_id[key] for key in sorted(by_id, key=int))\n"
    )
    return MockClient(script=[_reply(_exec(code, "merge")), _reply(_done())])


def run_g11_offline(workdir: Path) -> GoldenEvidence:
    return _run_g11_case(workdir, _g11_client(workdir))


def run_g11_real(workdir: Path, client: ModelClient) -> GoldenEvidence:
    return _run_g11_case(workdir, client)


class _RecordingMockClient(MockClient):
    def __init__(self, script: list[AssistantMessage | ClientError]) -> None:
        super().__init__(script)
        self.messages_by_call: list[list[Message]] = []

    def complete(
        self, messages: list[Message], params: GenerationParams | None = None
    ) -> AssistantMessage | ClientError:
        self.messages_by_call.append([message.model_copy(deep=True) for message in messages])
        return super().complete(messages, params)


def run_g13_offline(workdir: Path) -> GoldenEvidence:
    del workdir
    premature = _done()
    client = _RecordingMockClient(
        script=[
            _reply(premature + "\n" + _exec("print(undefined_variable)", "calc")),
            _reply(premature + "\n" + _exec("print(2 + 2)", "calc")),
            _reply(_done()),
        ]
    )
    from forgeagent.task import Task

    outcome = Task(client).run("Compute 2 + 2, recovering from the first execution error.")
    _require_completed(outcome, "G13")
    require(len(outcome.rounds) == 3, "G13 must require exactly three rounds")
    first, second, third = outcome.rounds
    require("completed: true" in first.text, "G13 failed round lacks premature completion")
    require("completed: true" in second.text, "G13 successful round lacks premature completion")
    require(not first.completed and not second.completed, "G13 accepted premature completion")
    require(
        len(first.outcomes) == 1 and not first.outcomes[0].success, "G13 first tool did not fail"
    )
    require("NameError" in first.outcomes[0].detail, "G13 first failure was not fed back")
    require(len(client.messages_by_call) >= 2, "G13 client did not receive round 2")
    round_two_feedback = [
        message.content
        for message in client.messages_by_call[1]
        if type(message.content) is str and "[Exec calc] FAILED:" in message.content
    ]
    require(
        len(round_two_feedback) == 1 and "NameError" in round_two_feedback[0],
        "G13 round 2 is missing failed tool feedback",
    )
    require(len(second.outcomes) == 1 and second.outcomes[0].success, "G13 second tool failed")
    require(second.outcomes[0].exec_result is not None, "G13 successful result missing")
    require(second.outcomes[0].exec_result.stdout.strip() == "4", "G13 corrected output differs")
    require(third.completed and not third.outcomes, "G13 third round was not independent")
    return _evidence(
        detail="completion required an independent third round",
        evidence={
            "rounds": 3,
            "failed_tool_round": 1,
            "successful_tool_round": 2,
            "completion_round": 3,
        },
    )


G15_INITIAL_CODE = '''"""Retry policy used by the service."""

RETRY_LIMIT = 3
DEFAULT_TIMEOUT = 10

def request_policy():
    return {"retries": RETRY_LIMIT, "timeout": DEFAULT_TIMEOUT}
'''
G15_EXPECTED_CODE = G15_INITIAL_CODE.replace("DEFAULT_TIMEOUT = 10", "DEFAULT_TIMEOUT = 15")


def _run_step(workdir: Path, client: ModelClient, goal: str):
    from forgeagent.task import Task
    from forgeagent.tools import CodeBlockStore

    workdir.mkdir(parents=True, exist_ok=True)
    store = CodeBlockStore()
    with patch("forgeagent.step.CodeBlockStore", return_value=store):
        outcome = Task(
            client,
            backend=RestrictedBackend(allowed_root=str(workdir), secret_values=set()),
            allowed_root=str(workdir),
        ).run(goal)
    return SimpleNamespace(rounds=outcome.rounds, blocks=store)


def _structured_call_outcomes(rounds):
    calls = []
    for round_result in rounds:
        parsed = parse(round_result.text)
        require(
            len(parsed.tool_calls) == len(round_result.outcomes),
            "golden structured tool-call history differs from outcomes",
        )
        calls.extend(zip(parsed.tool_calls, round_result.outcomes, strict=True))
    return calls


def _run_g15_case(workdir: Path, client: ModelClient) -> GoldenEvidence:
    step = _run_step(
        workdir,
        client,
        "Create the supplied target block, then use Edit to change only DEFAULT_TIMEOUT "
        "from 10 to 15. Do not replace the whole block.",
    )
    require(bool(step.rounds), "G15 produced no rounds")
    require(step.rounds[-1].stopped_reason == "completed", "G15 did not complete")
    call_outcomes = _structured_call_outcomes(step.rounds)
    successful_edits = [
        (call, outcome)
        for call, outcome in call_outcomes
        if call.name == "Edit" and outcome.success
    ]
    require(len(successful_edits) == 1, "G15 must invoke Edit successfully exactly once")
    edit_args = successful_edits[0][0].arguments
    require(
        isinstance(edit_args, EditArgs)
        and edit_args.name == "target"
        and edit_args.old == "DEFAULT_TIMEOUT = 10"
        and edit_args.new == "DEFAULT_TIMEOUT = 15",
        "G15 exact Edit arguments must be DEFAULT_TIMEOUT = 10 then DEFAULT_TIMEOUT = 15",
    )
    history = [block for block in step.blocks.history if block.name == "target"]
    require([block.version for block in history] == [1, 2], "G15 version chain differs")
    require(len(history) == 2, "G15 old version was not retained")
    old_lines = history[0].code.splitlines()
    new_lines = history[1].code.splitlines()
    changed = [
        index + 1
        for index, pair in enumerate(zip(old_lines, new_lines, strict=True))
        if pair[0] != pair[1]
    ]
    require(len(old_lines) == len(new_lines), "G15 changed line count")
    require(changed == [4], "G15 changed more than the target position")
    require(history[1].code == G15_EXPECTED_CODE, "G15 target value differs")
    try:
        tree = ast.parse(history[1].code)
    except SyntaxError as exc:
        _invalid("G15 new version is not valid Python", exc)
    timeout_values = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "DEFAULT_TIMEOUT"
            for target in node.targets
        )
        and isinstance(node.value, ast.Constant)
    ]
    require(timeout_values == [15], "G15 AST target value differs")
    return _evidence(
        detail="Edit produced one precise parseable version",
        evidence={
            "edit_calls": 1,
            "versions": [1, 2],
            "history_size": 2,
            "changed_line": 4,
            "target_value": 15,
            "ast_valid": True,
        },
    )


def run_g15_offline(workdir: Path) -> GoldenEvidence:
    client = MockClient(
        script=[
            _reply(_exec(G15_INITIAL_CODE, "target")),
            _reply(_edit("target", "DEFAULT_TIMEOUT = 10", "DEFAULT_TIMEOUT = 15")),
            _reply(_done()),
        ]
    )
    return _run_g15_case(workdir, client)


def _run_g17_case(workdir: Path, client: ModelClient) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    users = workdir / "users.csv"
    scores = workdir / "scores.csv"
    result = workdir / "joined.csv"
    users.write_text("user_id,name\nu2,Grace\nu1,Ada\nu4,Ken\n", encoding="utf-8")
    scores.write_text("user_id,score\nu1,91\nu3,77\nu2,88\n", encoding="utf-8")
    goal = (
        f"Inner join {users} and {scores} on user_id into {result}. Preserve left-file "
        "order and write exact columns user_id,name,score. Execute it."
    )
    _, outcome = _run_task(workdir, client, goal)
    _require_completed(outcome, "G17")
    columns, rows = _read_csv(result)
    expected_columns = ["user_id", "name", "score"]
    expected_rows = [["u2", "Grace", "88"], ["u1", "Ada", "91"]]
    require(columns == expected_columns, "G17 columns differ")
    require(len(rows) == 2, "G17 joined row count differs")
    require(rows == expected_rows, "G17 joined row values or order differ")
    return _evidence(
        detail="inner join matched exactly",
        evidence={"columns": expected_columns, "rows": expected_rows},
    )


def run_g17_offline(workdir: Path) -> GoldenEvidence:
    users = workdir / "users.csv"
    scores = workdir / "scores.csv"
    result = workdir / "joined.csv"
    code = (
        "import csv\n"
        f"with open({str(scores)!r}, newline='', encoding='utf-8') as handle:\n"
        "    score_by_id = {row['user_id']: row['score'] for row in csv.DictReader(handle)}\n"
        f"with open({str(users)!r}, newline='', encoding='utf-8') as handle:\n"
        "    joined = [[row['user_id'], row['name'], score_by_id[row['user_id']]] "
        "for row in csv.DictReader(handle) if row['user_id'] in score_by_id]\n"
        f"with open({str(result)!r}, 'w', newline='', encoding='utf-8') as handle:\n"
        "    writer = csv.writer(handle)\n"
        "    writer.writerow(['user_id', 'name', 'score'])\n"
        "    writer.writerows(joined)\n"
    )
    client = MockClient(script=[_reply(_exec(code, "join")), _reply(_done())])
    return _run_g17_case(workdir, client)


G27_INITIAL_CODE = """def includes_limit(value, limit):
    return value < limit

if not includes_limit(5, 5):
    raise RuntimeError("boundary regression")
"""
G27_EXPECTED_CODE = G27_INITIAL_CODE.replace("value < limit", "value <= limit")


def _run_g27_case(workdir: Path, client: ModelClient) -> GoldenEvidence:
    step = _run_step(
        workdir,
        client,
        "Run the provided target block to reproduce its regression, use Edit to fix only "
        "the comparison, rerun the same block until its provided test passes, then complete.",
    )
    require(bool(step.rounds), "G27 produced no rounds")
    require(step.rounds[-1].stopped_reason == "completed", "G27 did not complete")
    call_outcomes = _structured_call_outcomes(step.rounds)
    exec_outcomes = [outcome for call, outcome in call_outcomes if call.name == "Exec"]
    successful_edits = [
        (index, call, outcome)
        for index, (call, outcome) in enumerate(call_outcomes)
        if call.name == "Edit" and outcome.success
    ]
    require(
        len(exec_outcomes) >= 2 and not exec_outcomes[0].success, "G27 tests did not fail before"
    )
    require(len(successful_edits) == 1, "G27 must invoke Edit successfully exactly once")
    edit_index, edit_call, _ = successful_edits[0]
    edit_args = edit_call.arguments
    require(
        isinstance(edit_args, EditArgs)
        and edit_args.name == "target"
        and edit_args.old == "value < limit"
        and edit_args.new == "value <= limit",
        "G27 exact Edit arguments must be value < limit then value <= limit",
    )
    successful_post_edit_execs = [
        call
        for call, outcome in call_outcomes[edit_index + 1 :]
        if call.name == "Exec" and outcome.success
    ]
    require(
        len(successful_post_edit_execs) == 1
        and isinstance(successful_post_edit_execs[0].arguments, ExecArgs)
        and successful_post_edit_execs[0].arguments.name == "target",
        "G27 successful post-Edit Exec must target block target",
    )
    history = [block for block in step.blocks.history if block.name == "target"]
    require([block.version for block in history] == [1, 2], "G27 Edit version chain differs")
    require(history[0].code == G27_INITIAL_CODE, "G27 old version was not retained")
    require(history[1].code == G27_EXPECTED_CODE, "G27 fix was not the precise edit")
    return _evidence(
        detail="regression fix passed through an Edit version chain",
        evidence={
            "before_exit_code": 1,
            "after_exit_code": 0,
            "edit_calls": 1,
            "versions": [1, 2],
        },
    )


def run_g27_offline(workdir: Path) -> GoldenEvidence:
    client = MockClient(
        script=[
            _reply(_exec(G27_INITIAL_CODE, "target")),
            _reply(_edit("target", "value < limit", "value <= limit")),
            _reply(_exec(name="target")),
            _reply(_done()),
        ]
    )
    return _run_g27_case(workdir, client)


def _run_g43_case(workdir: Path, client: ModelClient) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    source = workdir / "words.txt"
    result = workdir / "top.json"
    source.write_text(
        "Forge agents forge code. Tests guide Forge; code guides tests. Forge tools.",
        encoding="utf-8",
    )
    goal = (
        f"Count case-insensitive words in {source}, sort by count descending then word "
        f"ascending for ties, and write the top 5 as JSON pairs to {result}. Execute it."
    )
    _, outcome = _run_task(workdir, client, goal)
    _require_completed(outcome, "G43")
    try:
        actual = json.loads(result.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _invalid("G43 output JSON is invalid", exc)
    expected = [["forge", 4], ["code", 2], ["tests", 2], ["agents", 1], ["guide", 1]]
    require(
        type(actual) is list
        and all(
            type(item) is list and len(item) == 2 and type(item[0]) is str and type(item[1]) is int
            for item in actual
        ),
        "G43 output must have exact list shape with built-in str words and int counts",
    )
    require(actual == expected, "G43 Top-N words, counts, or order differ")
    return _evidence(
        detail="word-frequency Top-N matched exactly",
        evidence={"top_n": expected},
    )


def _g43_client(workdir: Path) -> MockClient:
    source = workdir / "words.txt"
    result = workdir / "top.json"
    code = (
        "import json, re\n"
        "from collections import Counter\n"
        f"text = open({str(source)!r}, encoding='utf-8').read().lower()\n"
        "counts = Counter(re.findall(r'[a-z]+', text))\n"
        "top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]\n"
        f"with open({str(result)!r}, 'w', encoding='utf-8') as handle:\n"
        "    json.dump(top, handle)\n"
    )
    return MockClient(script=[_reply(_exec(code, "count")), _reply(_done())])


def run_g43_offline(workdir: Path) -> GoldenEvidence:
    return _run_g43_case(workdir, _g43_client(workdir))


def run_g43_real(workdir: Path, client: ModelClient) -> GoldenEvidence:
    return _run_g43_case(workdir, client)


def run_g06_offline(workdir: Path) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    secret = "g06-target-content-must-not-be-read"
    with TemporaryDirectory(prefix="forgeagent-g06-outside-") as outside_directory:
        target = Path(outside_directory) / "g06-outside-secret.txt"
        target.write_text(secret, encoding="utf-8")
        client = _RecordingMockClient(
            script=[
                _reply(_exec(f"print(open({str(target)!r}, encoding='utf-8').read())", "escape")),
                _reply(_done()),
            ]
        )

        _, outcome = _run_task(workdir, client, "Read the supplied out-of-project file.")

        require(len(outcome.rounds) == 2, "G06 task did not continue after restricted denial")
        failed_round, completion_round = outcome.rounds
        require(
            len(failed_round.outcomes) == 1 and not failed_round.outcomes[0].success,
            "G06 restricted operation was not recorded as a structured failure",
        )
        failed = failed_round.outcomes[0]
        require(failed.exec_result is not None, "G06 restricted failure lacks an ExecResult")
        require(
            failed.detail == "restricted: file access outside allowed root denied",
            "G06 restricted failure detail differs",
        )
        require(
            secret not in failed.exec_result.stdout
            and secret not in failed.exec_result.stderr
            and secret not in (failed.exec_result.error or ""),
            "G06 out-of-root target content was exposed",
        )
        require(
            len(client.messages_by_call) >= 2, "G06 denial feedback was not returned to the task"
        )
        feedback = [
            message.content
            for message in client.messages_by_call[1]
            if type(message.content) is str and "[Exec escape] FAILED:" in message.content
        ]
        require(
            len(feedback) == 1
            and "restricted: file access outside allowed root denied" in feedback[0],
            "G06 task feedback lacks the structured denial",
        )
        require(secret not in feedback[0], "G06 task feedback exposed target content")
        require(
            completion_round.completed and not completion_round.outcomes,
            "G06 task did not reach an independent completion round",
        )
        return _evidence(
            detail="restricted denial returned through task feedback",
            evidence={
                "rounds": 2,
                "failed_round": 1,
                "completion_round": 2,
                "target_content_exposed": False,
            },
        )


def run_g14_offline(workdir: Path) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    backend = RestrictedBackend(
        allowed_root=str(workdir),
        timeout_seconds=0.2,
        cpu_seconds=0,
        secret_values=set(),
    )
    client = _RecordingMockClient(
        script=[
            _reply(_exec("while True:\n    pass", "runaway")),
            _reply(_exec("print('later work succeeded')", "later")),
            _reply(_done()),
        ]
    )
    workers: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def record_worker(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        command = args[0] if args else kwargs.get("args", [])
        if "forgeagent._sandbox_worker" in " ".join(str(part) for part in command):
            workers.append(process)
        return process

    with patch("forgeagent.executor.subprocess.Popen", side_effect=record_worker):
        _, outcome = _run_task(
            workdir,
            client,
            "Run the supplied long operation, then perform independent later work.",
            backend=backend,
        )

    require(len(outcome.rounds) == 3, "G14 task did not follow timeout, success, completion")
    timed_out, later, completed = outcome.rounds
    require(
        len(timed_out.outcomes) == 1 and not timed_out.outcomes[0].success,
        "G14 runaway block did not fail",
    )
    timeout_detail = "execution timed out after 0.2s (process killed)"
    require(timed_out.outcomes[0].detail == timeout_detail, "G14 timeout detail differs")
    require(len(client.messages_by_call) >= 2, "G14 timeout feedback was not returned")
    timeout_feedback = [
        message.content
        for message in client.messages_by_call[1]
        if type(message.content) is str and "[Exec runaway] FAILED:" in message.content
    ]
    require(
        len(timeout_feedback) == 1 and timeout_detail in timeout_feedback[0],
        "G14 timeout feedback differs",
    )
    require(
        len(later.outcomes) == 1
        and later.outcomes[0].success
        and later.outcomes[0].exec_result is not None
        and later.outcomes[0].exec_result.stdout.strip() == "later work succeeded",
        "G14 later independent work did not succeed",
    )
    require(completed.completed and not completed.outcomes, "G14 task did not complete")
    require(len(workers) == 2, "G14 worker process count differs")
    require(
        all(process.poll() is not None for process in workers),
        "G14 left a sandbox worker running",
    )
    return _evidence(
        detail="timeout was isolated from later work",
        evidence={
            "rounds": 3,
            "timed_out_round": 1,
            "successful_round": 2,
            "worker_processes": 2,
            "workers_reaped": True,
        },
    )


def run_g58_offline(workdir: Path) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    secret = "g58-target-content-must-not-be-read"
    with TemporaryDirectory(prefix="forgeagent-g58-outside-") as outside_directory:
        target = Path(outside_directory) / "g58-outside-secret.txt"
        target.write_text(secret, encoding="utf-8")
        result = RestrictedBackend(allowed_root=str(workdir), secret_values=set()).execute(
            "import os\n"
            f"os.chdir({str(workdir)!r})\n"
            f"print(open({str(target)!r}, encoding='utf-8').read())\n",
            Runtime(),
        )

        require(not result.success, "G58 out-of-root read unexpectedly succeeded")
        require(
            result.error == "restricted: file access outside allowed root denied",
            "G58 audit-hook failure detail differs",
        )
        require(
            secret not in result.stdout
            and secret not in result.stderr
            and secret not in result.error,
            "G58 out-of-root target content was exposed",
        )
        return _evidence(
            detail="audit hook blocked the out-of-root read",
            evidence={
                "success": False,
                "error": result.error,
                "target_content_exposed": False,
            },
        )


def run_g59_offline(workdir: Path) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="forgeagent-g59-outside-") as outside_directory:
        target = Path(outside_directory) / "g59-outside-write.txt"
        result = RestrictedBackend(allowed_root=str(workdir), secret_values=set()).execute(
            "import os\n"
            f"os.chdir({str(workdir)!r})\n"
            f"open({str(target)!r}, 'w', encoding='utf-8').write('outside')\n",
            Runtime(),
        )

        require(not result.success, "G59 out-of-root write unexpectedly succeeded")
        require(
            result.error == "restricted: file access outside allowed root denied",
            "G59 audit-hook failure detail differs",
        )
        require(not target.exists(), "G59 created the out-of-root target")
        return _evidence(
            detail="audit hook blocked the out-of-root write",
            evidence={"success": False, "error": result.error, "target_exists": False},
        )


def run_g324_offline(workdir: Path) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="forgeagent-g324-outside-") as outside_directory:
        target = Path(outside_directory) / "g324-outside-write.txt"
        outcome = FileWriteTool().run(
            FileWriteArgs(path=str(target), content="outside"),
            _tool_context(workdir, confirmer=lambda _args: True),
        )

        require(not outcome.success, "G324 out-of-root FileWrite unexpectedly succeeded")
        require(
            outcome.detail == "FileWrite path is outside project root",
            "G324 FileWrite failure detail differs",
        )
        require(not target.exists(), "G324 created the out-of-root target")
        return _evidence(
            detail="FileWrite rejected the out-of-root target",
            evidence={"success": False, "detail": outcome.detail, "target_exists": False},
        )


def run_g329_offline(workdir: Path) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    metadata_host = "169.254.169.254"
    resolver_calls: list[str] = []
    connector_calls: list[tuple[object, ...]] = []

    def resolve(host, port, *args, **kwargs):
        del args, kwargs
        resolver_calls.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (metadata_host, port))]

    def connect(*args, **kwargs):
        connector_calls.append((*args, kwargs))
        raise RuntimeError("G329 connector double fired")

    with (
        patch("forgeagent.ssrf_guard.socket.getaddrinfo", side_effect=resolve),
        patch("forgeagent.ssrf_guard.socket.socket", side_effect=connect),
    ):
        outcome = WebFetchTool().run(
            WebFetchArgs(url=f"http://{metadata_host}/latest/meta-data/"),
            _tool_context(workdir, confirmer=lambda _args: True),
        )

    require(resolver_calls == [metadata_host], "G329 metadata host was not guarded exactly once")
    require(not outcome.success, "G329 metadata WebFetch unexpectedly succeeded")
    require(
        outcome.detail == "WebFetch blocked by network policy",
        "G329 WebFetch failure detail differs",
    )
    require(connector_calls == [], "G329 attempted a guarded connection")
    require(not list(workdir.glob("webfetch_*")), "G329 saved a blocked response")
    return _evidence(
        detail="confirmed metadata fetch was blocked before connect",
        evidence={"success": False, "detail": outcome.detail, "connector_calls": 0},
    )


def run_g330_offline(workdir: Path) -> GoldenEvidence:
    del workdir
    public_url = "http://public.example/redirect"
    private_url = "http://private.example/metadata"
    resolved_hosts: list[str] = []
    connection_calls: list[tuple[str, int]] = []
    closed_connections: list[tuple[str, int]] = []
    real_build_opener = urllib.request.build_opener

    class FakeSocket:
        def __init__(self, *_args, **_kwargs) -> None:
            self._connected_address: tuple[str, int] | None = None

        def settimeout(self, _timeout) -> None:
            pass

        def bind(self, _address) -> None:
            pass

        def connect(self, address) -> None:
            self._connected_address = address
            connection_calls.append(address)

        def close(self) -> None:
            if self._connected_address is not None:
                closed_connections.append(self._connected_address)

    class SyntheticPublicRedirect(urllib.request.BaseHandler):
        handler_order = 100

        def http_open(self, request):
            if request.full_url != public_url:
                return None
            from forgeagent.ssrf_guard import _guarded_create_connection

            connection = _guarded_create_connection(("public.example", 80), timeout=1)
            connection.close()
            headers = EmailMessage()
            headers["Location"] = private_url
            response = urllib.response.addinfourl(io.BytesIO(), headers, request.full_url, 302)
            response.msg = "synthetic redirect"
            return response

    def build_opener(*handlers):
        return real_build_opener(SyntheticPublicRedirect(), *handlers)

    def resolve(host, port, *args, **kwargs):
        del args, kwargs
        resolved_hosts.append(host)
        address = {"public.example": "8.8.8.8", "private.example": "10.0.0.8"}[host]
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]

    blocked = False
    with (
        patch("forgeagent.ssrf_guard.urllib.request.build_opener", side_effect=build_opener),
        patch("forgeagent.ssrf_guard.socket.getaddrinfo", side_effect=resolve),
        patch("forgeagent.ssrf_guard.socket.socket", side_effect=FakeSocket),
    ):
        try:
            guarded_urlopen(public_url, timeout=1)
        except SSRFGuardError:
            blocked = True

    require(blocked, "G330 private redirect was not blocked")
    require(
        resolved_hosts == ["public.example", "private.example"],
        "G330 guarded host resolution differs",
    )
    require(connection_calls == [("8.8.8.8", 80)], "G330 public connection count differs")
    require(closed_connections == connection_calls, "G330 public connection was not closed")
    return _evidence(
        detail="private redirect was rejected before connect",
        evidence={
            "blocked": True,
            "resolved_hosts": resolved_hosts,
            "public_connection_calls": 1,
            "private_connection_calls": 0,
        },
    )


def run_g332_offline(workdir: Path) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    url = "https://public.example/data.txt"
    fake_network_calls: list[str] = []

    def fake_public_response(request_url: str, **_kwargs):
        fake_network_calls.append(request_url)
        return _GoldenResponse(b"public fixture response")

    with patch("forgeagent.tools.guarded_urlopen", side_effect=fake_public_response):
        rejected = WebFetchTool().run(WebFetchArgs(url=url), _tool_context(workdir))
        calls_after_rejection = len(fake_network_calls)
        approved = WebFetchTool().run(
            WebFetchArgs(url=url),
            _tool_context(workdir, confirmer=lambda _args: True),
        )

    require(not rejected.success, "G332 no-channel WebFetch unexpectedly succeeded")
    require(
        rejected.detail == "rejected: no interactive confirmation channel available",
        "G332 no-channel rejection detail differs",
    )
    require(calls_after_rejection == 0, "G332 no-channel path called fake network")
    require(approved.success, "G332 approved fake public response failed")
    require(fake_network_calls == [url], "G332 approved path did not use one fake response")
    saved = list(workdir.glob("webfetch_*"))
    require(len(saved) == 1, "G332 approved response artifact count differs")
    require(
        saved[0].read_text(encoding="utf-8") == "public fixture response",
        "G332 approved response artifact differs",
    )
    return _evidence(
        detail="WebFetch confirmation controlled fake network access",
        evidence={
            "rejected_detail": rejected.detail,
            "rejected_network_calls": 0,
            "approved": True,
            "approved_network_calls": 1,
        },
    )


def run_g333_offline(workdir: Path) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / "inside.txt"
    context = _tool_context(workdir, confirmer=lambda _args: False)
    refused = FileWriteTool().run(
        FileWriteArgs(path=target.name, content="written by FileWrite"), context
    )

    require(not refused.success, "G333 denied FileWrite unexpectedly succeeded")
    require(
        refused.detail == "FileWrite was not approved by the user",
        "G333 FileWrite denial detail differs",
    )
    require(not target.exists(), "G333 denied FileWrite created the target")
    executed = ExecTool().run(
        ExecArgs(
            name="inside-write",
            code=f"open({str(target)!r}, 'w', encoding='utf-8').write('written by Exec')",
        ),
        context,
    )

    require(executed.success, "G333 later Exec write failed")
    require(target.exists(), "G333 later Exec did not create the inside-root target")
    final_content = target.read_text(encoding="utf-8")
    require(final_content == "written by Exec", "G333 later Exec content differs")
    return _evidence(
        detail="FileWrite confirmation did not replace the project-root boundary",
        evidence={
            "filewrite_detail": refused.detail,
            "filewrite_created": False,
            "exec_success": True,
            "final_content": final_content,
        },
    )


def run_g355_offline(workdir: Path) -> GoldenEvidence:
    workdir.mkdir(parents=True, exist_ok=True)
    fixture = Path(__file__).resolve().parents[1] / "mcp_fixture_server.py"
    pid_file = workdir / "available.pid"
    available = MCPServerConfig(
        command=sys.executable,
        args=[str(fixture)],
        env={
            "FORGE_TEST_MCP_NAME": "available",
            "FORGE_TEST_MCP_MODE": "normal",
            "FORGE_TEST_MCP_PID_FILE": str(pid_file),
        },
    )
    unavailable = MCPServerConfig(command=str(workdir / "missing-optional-server"))
    manager = MCPManager(
        {"available": available, "optional": unavailable},
        connect_timeout=5.0,
        shutdown_timeout=3.0,
        thread_join_timeout=1.0,
    )
    console = Console(file=io.StringIO(), record=True, width=160)
    rendered = ""
    pid = 0
    try:
        manager.connect()
        require(pid_file.exists(), "G355 available fixture did not publish its PID")
        pid = int(pid_file.read_text(encoding="utf-8"))
        from forgeagent.cli import _handle_mcp_slash

        _handle_mcp_slash("/mcp", manager, console)
        _handle_mcp_slash("/mcp status", manager, console)
        rendered = console.export_text()
    finally:
        manager.close()

    deadline = time.monotonic() + 1.0
    while pid and _process_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    pid_reaped = bool(pid) and not _process_exists(pid)
    require("Status: available" in rendered, "G355 output lacks available status")
    require(
        "Status: unavailable: startup_failed" in rendered,
        "G355 output lacks optional failure status",
    )
    require("Reason: MCP server failed to start" in rendered, "G355 output lacks reason")
    require("Impact: Configured tools are disabled" in rendered, "G355 output lacks impact")
    require(
        "Action: Check the server configuration and try again" in rendered,
        "G355 output lacks action",
    )
    require(
        "available:echo" in rendered and "Echo the given text" in rendered,
        "G355 output lacks available echo tool description",
    )
    require(
        "available:add" in rendered and "Add two integers" in rendered,
        "G355 output lacks available add tool description",
    )
    tool_labels = {
        label
        for line in rendered.splitlines()
        for label in [line.strip().split(" ", maxsplit=1)[0]]
        if line.startswith("  ") and label.partition(":")[2]
    }
    require(
        tool_labels == {"available:echo", "available:add"},
        "G355 rendered tool labels differ",
    )
    require(manager._loop is None and manager._thread is None, "G355 manager did not close")
    require(pid_reaped, "G355 fixture process survived manager close")
    return _evidence(
        detail="MCP slash output showed optional degradation and available tools",
        evidence={
            "available_status": True,
            "unavailable_status": True,
            "available_tools": ["add", "echo"],
            "unavailable_tools": [],
            "pid_reaped": True,
        },
    )
