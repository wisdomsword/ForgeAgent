"""Static contracts for the M21 Loop documentation and safe example."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_readme_documents_new_and_resume_loop_commands() -> None:
    text = _text("README.md")

    assert "forgeagent loop" in text
    assert "--token-budget" in text
    assert "forgeagent loop --resume" in text
    assert "Checkpoint" in text
    assert "commit" in text
    assert "replay" in text


def test_protocol_documents_loop_schema_checkpoint_and_stable_stop_reasons() -> None:
    text = _text("docs/text-protocol-spec.md")

    assert "forgeagent.loop.v1" in text
    assert "Loop 专用" in text
    for reason in (
        "completed",
        "cancelled",
        "wall_clock",
        "token_usage_unavailable",
        "token_budget",
        "max_rounds",
        "consecutive_failures",
        "unrecoverable_failure",
        "checkpoint_error",
    ):
        assert f"`{reason}`" in text


def test_threat_model_covers_loop_checkpoint_injection_path_race_and_replay() -> None:
    text = _text("docs/threat-model.md")

    assert "checkpoint" in text.lower()
    assert "injection" in text.lower()
    assert "replay" in text.lower()
    assert "symlink" in text.lower()
    assert "race" in text.lower()


def test_golden_seed_marks_loop_acceptance_as_offline_and_evaluator_exclusion() -> None:
    text = _text("docs/golden-tasks-seed.md")

    assert "M21" in text
    assert "checkpoint" in text.lower()
    assert "offline" in text.lower()
    assert "Evaluator" in text
    assert "M22" in text


def test_action_plan_marks_m21_as_in_progress_without_final_counts() -> None:
    text = _text("ACTION_PLAN.md")

    assert "**M21**" in text
    assert "进行中" in text
    assert "checkpoint 中断-恢复端到端测试" in text


def test_loop_examples_avoid_daemon_and_dependency_mutations() -> None:
    index = _text("examples/loop/README.md")
    example = _text("examples/loop/dependency-report.md")
    combined = f"{index}\n{example}".lower()

    assert "cron" in index
    assert "launchd" in index
    assert "systemd" in index
    assert "user-installed" in index
    assert "daemon" in index
    assert "not" in index.lower()
    assert "[Unit]" in index
    assert "[Service]" in index
    assert "WorkingDirectory=" in index
    assert "ExecStart=" in index
    assert "[Timer]" in index
    assert "OnCalendar=" in index or "OnUnitActiveSec=" in index
    assert "Persistent=true" in index
    assert "WantedBy=timers.target" in index
    assert "systemctl --user enable --now" in index
    assert ".timer" in index
    for prohibited in ("pip install", "uv add", "update", "git commit", "git push", "pull request"):
        assert prohibited not in combined
