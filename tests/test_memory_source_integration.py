from rich.console import Console

from forgeagent.cli import _handle_remember_command
from forgeagent.client import MockClient
from forgeagent.memory import MemoryManager, MemoryResult
from forgeagent.models import AssistantMessage, TokenUsage
from forgeagent.task import Task


def _done_with_project_memory() -> str:
    return (
        "---\ntask_status:\n  completed: true\n  confidence: 0.9\n---\ndone\n"
        '<!-- Memory: {"scope":"project","kind":"fact",'
        '"key":"editor","content":"nvim"} -->'
    )


class _RecordingMemoryManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def render(self) -> str:
        return ""

    def apply(self, candidate, task_id=None, *, source="host_api") -> MemoryResult:
        self.calls.append((source, task_id))
        return MemoryResult("accepted", candidate.scope, candidate.kind, candidate.key)


def test_task_projects_model_candidate_source():
    manager = _RecordingMemoryManager()
    client = MockClient(
        script=[
            AssistantMessage(
                content=_done_with_project_memory(),
                usage=TokenUsage(),
                stop_reason="end_turn",
            )
        ]
    )

    outcome = Task(client, memory_manager=manager, task_id="task-42").run("remember editor")

    assert outcome.status.completed is True
    assert manager.calls == [("model_candidate", "task-42")]


def test_remember_command_projects_user_command_source():
    manager = _RecordingMemoryManager()
    console = Console(record=True, force_terminal=False)

    _handle_remember_command("/remember project editor=nvim", manager, console)

    assert manager.calls == [("user_command", None)]
    assert "memory accepted" in console.export_text()


def _write_v1(root) -> bytes:
    raw = b"<!-- forgeagent-memory-v1 -->\n- editor: vim\n"
    path = root / ".forgeagent" / "MEMORY.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    return raw


def test_task_exposes_v1_migration_required_without_overwriting(tmp_path):
    original = _write_v1(tmp_path)
    manager = MemoryManager(str(tmp_path))
    manager.load()
    client = MockClient(
        script=[
            AssistantMessage(
                content=_done_with_project_memory(),
                usage=TokenUsage(),
                stop_reason="end_turn",
            )
        ]
    )

    outcome = Task(client, memory_manager=manager).run("remember editor")

    assert (outcome.memory_results[0].status, outcome.memory_results[0].reason) == (
        "rejected",
        "migration_required",
    )
    assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original


def test_remember_command_exposes_v1_migration_required_without_overwriting(tmp_path):
    original = _write_v1(tmp_path)
    manager = MemoryManager(str(tmp_path))
    manager.load()
    console = Console(record=True, force_terminal=False)

    _handle_remember_command("/remember project editor=nvim", manager, console)

    assert "migration_required" in console.export_text()
    assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original
