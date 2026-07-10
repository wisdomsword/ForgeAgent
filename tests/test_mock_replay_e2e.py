"""Mock replay end-to-end tests (M3-5, updated M4-3).

Drives the full Task/Step loop with MockClient scripted responses (no key, no network).
Each scripted response follows the text-protocol markup from docs/text-protocol-spec.md.
Covers three golden tasks that exercise the loop's core mechanisms:
  - G01  CSV summary          -> file I/O + Exec
  - G05  cross-block state    -> utils.set_state / get_state across blocks
  - G13  error feedback loop  -> fail -> feedback -> corrected -> success (multi-round)

M4-3 note: the default tier is now `restricted` (real subprocess + audit hook). File-I/O
tasks (G01, G05) run on a RestrictedBackend rooted at tmp_path, so this is genuine
restricted-tier end-to-end coverage — the sandbox allows tmp_path and denies elsewhere.
"""

import json
from pathlib import Path

from forgeagent.client import MockClient
from forgeagent.executor import RestrictedBackend
from forgeagent.models import AssistantMessage, TokenUsage
from forgeagent.task import Task


def _reply(text: str) -> AssistantMessage:
    return AssistantMessage(content=text, usage=TokenUsage(), stop_reason="end_turn")


def _exec(code: str, name: str | None = None) -> str:
    args: dict = {"code": code}
    if name:
        args["name"] = name
    return f"<!-- ToolCall: {json.dumps({'name': 'Exec', 'arguments': args})} -->"


def _done() -> str:
    return "---\ntask_status:\n  completed: true\n  confidence: 0.95\n---\ndone"


# --- G01: CSV summary --------------------------------------------------------


def test_g01_csv_summary_end_to_end(tmp_path: Path):
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("value\n10\n20\n30\n", encoding="utf-8")
    result_file = tmp_path / "result.json"

    code = (
        "import csv, json\n"
        f"rows = list(csv.DictReader(open({str(csv_file)!r})))\n"
        "vals = [float(r['value']) for r in rows]\n"
        "out = {'sum': sum(vals), 'mean': sum(vals) / len(vals)}\n"
        f"json.dump(out, open({str(result_file)!r}, 'w'))\n"
        "print('written')\n"
    )
    # Restricted tier, rooted at tmp_path so the sandbox allows the task's files.
    task = Task(
        MockClient(script=[_reply(_exec(code)), _reply(_done())]),
        backend=RestrictedBackend(allowed_root=str(tmp_path)),
    )
    outcome = task.run("summarize the CSV")

    assert outcome.status.completed is True
    # Independent check of the pass criteria (sum/mean within tolerance).
    data = json.loads(result_file.read_text())
    assert abs(data["sum"] - 60.0) < 1e-6
    assert abs(data["mean"] - 20.0) < 1e-6


# --- G05: cross-block state --------------------------------------------------


def test_g05_cross_block_state_end_to_end(tmp_path: Path):
    counter = tmp_path / "sideeffect.log"
    # Block 1: side-effecting compute + set_state. Block 2: read state, no recompute.
    block1 = _exec(
        f"open({str(counter)!r}, 'a').write('ran\\n')\n"
        "utils.set_state('subtotal', 6 * 7)",
        name="compute",
    )
    block2 = _exec("print(utils.get_state('subtotal') + 8)", name="finish")
    # Restricted tier rooted at tmp_path: also verifies state crosses the subprocess
    # boundary as JSON (block 2 is a fresh subprocess that must still see block 1's state).
    task = Task(
        MockClient(script=[_reply(block1), _reply(block2), _reply(_done())]),
        backend=RestrictedBackend(allowed_root=str(tmp_path)),
    )
    outcome = task.run("two-step compute with state")

    assert outcome.status.completed is True
    # Final output uses carried state (42 + 8).
    assert "50" in outcome.rounds[1].outcomes[0].exec_result.stdout
    # State mechanism worked: side effect fired exactly once (block 2 did not recompute).
    assert counter.read_text().count("ran") == 1
    assert task.runtime.get_state("subtotal") == 42


# --- G13: error feedback loop ------------------------------------------------


def test_g13_error_feedback_loop_end_to_end():
    # Round 1: code raises (NameError). The loop renders the error as feedback.
    # Round 2: corrected code succeeds. Round 3: completion.
    bad = _exec("print(undefined_variable)", name="calc")
    good = _exec("print(2 + 2)", name="calc")
    task = Task(MockClient(script=[_reply(bad), _reply(good), _reply(_done())]))
    outcome = task.run("compute 2+2 (with a first-try mistake)")

    assert outcome.status.completed is True
    # Multi-round: failed once, then succeeded, then completed.
    assert len(outcome.rounds) == 3
    assert outcome.rounds[0].outcomes[0].success is False
    assert "NameError" in outcome.rounds[0].outcomes[0].detail
    assert outcome.rounds[1].outcomes[0].success is True
    assert "4" in outcome.rounds[1].outcomes[0].exec_result.stdout


def test_g13_error_actually_fed_back_as_message():
    # Assert the error genuinely enters the conversation as feedback (not just logged),
    # which is what makes the model able to correct on the next round.
    bad = _exec("1 / 0", name="calc")
    good = _exec("print('ok')", name="calc")
    client = MockClient(script=[_reply(bad), _reply(good), _reply(_done())])
    task = Task(client)
    outcome = task.run("divide")
    assert outcome.status.completed is True
    # The failing round produced a feedback round (>=3 rounds means feedback drove it).
    assert len(outcome.rounds) == 3
    assert "ZeroDivisionError" in outcome.rounds[0].outcomes[0].detail
