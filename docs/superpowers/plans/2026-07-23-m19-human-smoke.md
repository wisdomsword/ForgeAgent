# M19 Local Human Smoke Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one key-free command that drives the production REPL through deterministic Skill V1/V2 snapshots and combines automatic checks with explicit human confirmation of completion and history UX.

**Architecture:** One standalone script owns a temporary HOME/project fixture, a two-round `ModelClient`, and the final check matrix. It calls the production `repl()` without injecting a reader, so prompt-toolkit, project-Skill confirmation, `/reload`, Task/Step, and the Skill tool remain the real implementation under test; only the remote model is replaced.

**Tech Stack:** Python 3.11, ForgeAgent `ModelClient`, pytest, prompt-toolkit, Rich, uv, ruff.

## Global Constraints

- Do not read or mutate real ForgeAgent configuration or project Skills. Do not resolve, use,
  print, or transmit API keys; hide inherited secret-named variables from the production path
  and restore their exact original mapping afterward.
- Do not open sockets, add dependencies, add a product CLI command, or persist REPL history.
- The default entry requires both stdin and stdout to be TTYs and must fail closed otherwise.
- Human completion/history observations default to failure until explicitly answered `y`.
- Cleanup must restore HOME and cwd and remove the temporary fixture on success, failure, or Ctrl-C.
- Preserve all unrelated dirty-worktree files and commit only files named by this plan.

## Planned File Structure

| File | Responsibility |
| --- | --- |
| `scripts/m19-skills-human-smoke.py` | Temporary fixture, deterministic client, production REPL launch, trust validation, human prompts, PASS/FAIL summary. |
| `tests/test_m19_skills_human_smoke.py` | Unit coverage for fixture isolation, two-round marker inspection, single V2 upgrade, check matrix, and non-TTY rejection. |
| `README.md` | One-command human acceptance entry and scope. |
| `docs/superpowers/specs/2026-07-23-m19-human-smoke-design.md` | Mark the approved design final. |

---

### Task 1: Build the deterministic fixture and client with TDD

**Files:**
- Create: `scripts/m19-skills-human-smoke.py`
- Create: `tests/test_m19_skills_human_smoke.py`

**Interfaces:**
- Produces: `SmokeFixture`, `SmokeState`, `create_fixture(root: Path)`, `SmokeClientFactory`, `evaluate_checks(...)`, and `trust_record_matches_v2(...)` for Task 2.
- Consumes: production `ModelClient`, `AssistantMessage`, `Message`, `TokenUsage`, `SkillRegistry`, and text ToolCall/task-status protocol.

- [x] **Step 1: Write failing fixture, client, and final-matrix tests**

Load the hyphenated script without running `main()` and assert the public harness helpers:

```python
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from forgeagent.models import Message


def _load_smoke_module():
    path = Path(__file__).parents[1] / "scripts" / "m19-skills-human-smoke.py"
    spec = importlib.util.spec_from_file_location("m19_skills_human_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fixture_isolated_user_and_project_skills(tmp_path):
    smoke = _load_smoke_module()
    fixture = smoke.create_fixture(tmp_path)
    assert "USER_SKILL" in fixture.user_skill.read_text()
    assert "PROJECT_SKILL_V1" in fixture.project_skill.read_text()
    assert fixture.home.is_relative_to(tmp_path)
    assert fixture.project.is_relative_to(tmp_path)


def test_client_reads_skill_then_accepts_expected_feedback(tmp_path):
    smoke = _load_smoke_module()
    state = smoke.SmokeState()
    client = smoke.DeterministicSkillClient("PROJECT_SKILL_V1", state)
    first = client.complete([Message(role="user", content="review")])
    assert '"name": "Skill"' in first.content
    second = client.complete(
        [Message(role="system", content="[Skill None]\nPROJECT_SKILL_V1")]
    )
    assert "PASS progressive loading: PROJECT_SKILL_V1" in second.content
    assert state.observed_markers == ["PROJECT_SKILL_V1"]


def test_factory_keeps_v1_until_v2_is_trusted(tmp_path):
    smoke = _load_smoke_module()
    fixture = smoke.create_fixture(tmp_path)
    state = smoke.SmokeState()
    SkillRegistry.load(
        home=str(fixture.home),
        allowed_root=str(fixture.project),
        confirmer=lambda _request: True,
    )
    factory = smoke.SmokeClientFactory(fixture, state)
    first = factory("mock")
    extra_before_reload = factory("mock")
    SkillRegistry.load(
        home=str(fixture.home),
        allowed_root=str(fixture.project),
        confirmer=lambda _request: True,
    )
    after_reload = factory("mock")
    assert first.expected_marker == "PROJECT_SKILL_V1"
    assert extra_before_reload.expected_marker == "PROJECT_SKILL_V1"
    assert after_reload.expected_marker == "PROJECT_SKILL_V2"
    assert "PROJECT_SKILL_V2" in fixture.project_skill.read_text()


def test_check_matrix_fails_closed_until_human_checks_pass():
    smoke = _load_smoke_module()
    state = smoke.SmokeState(observed_markers=["PROJECT_SKILL_V1", "PROJECT_SKILL_V2"])
    checks = smoke.evaluate_checks(
        state, trust_matches=True, completion_ok=False, history_ok=False
    )
    assert checks["progressive V1"] is True
    assert checks["reload V2"] is True
    assert checks["slash completion"] is False
    assert checks["arrow history"] is False
```

- [x] **Step 2: Run the new tests and verify RED**

Run: `uv run pytest tests/test_m19_skills_human_smoke.py -v`

Expected: FAIL because `scripts/m19-skills-human-smoke.py` does not exist.

- [x] **Step 3: Implement the minimum fixture, state machine, and check matrix**

Implement these exact shapes in the new script:

```python
@dataclass(frozen=True)
class SmokeFixture:
    home: Path
    project: Path
    user_skill: Path
    project_skill: Path


@dataclass
class SmokeState:
    observed_markers: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def create_fixture(root: Path) -> SmokeFixture:
    home = root / "home"
    project = root / "project"
    user_skill = home / ".forgeagent" / "skills" / "review-python" / "SKILL.md"
    project_skill = project / ".forgeagent" / "skills" / "review-python" / "SKILL.md"
    _write_skill(user_skill, "USER_SKILL", "Use the user review procedure.")
    _write_skill(project_skill, "PROJECT_SKILL_V1", "Use the project review procedure.")
    return SmokeFixture(home, project, user_skill, project_skill)


class DeterministicSkillClient(ModelClient):
    def __init__(self, expected_marker: str, state: SmokeState) -> None:
        self.expected_marker = expected_marker
        self._state = state
        self._round = 0
        self._capability = ModelCapability(
            model_id="mock", context_window=100_000, max_output_tokens=4_096,
            supports_thinking=False, thinking_always_on=False,
            supports_effort=False, client_kind="anthropic",
        )

    def complete(self, messages, params=None):
        self._round += 1
        if self._round == 1:
            return _reply(_skill_call())
        visible = "\n".join(
            item.content for item in messages if isinstance(item.content, str)
        )
        if self.expected_marker in visible:
            self._state.observed_markers.append(self.expected_marker)
            return _reply(_done(f"PASS progressive loading: {self.expected_marker}"))
        self._state.failures.append(f"missing feedback marker: {self.expected_marker}")
        return _reply(_failed(f"FAIL missing feedback marker: {self.expected_marker}"))

    @property
    def capability(self):
        return self._capability


class SmokeClientFactory:
    def __call__(self, _model: str) -> ModelClient:
        task_index = self._task_count
        self._task_count += 1
        if task_index == 0:
            _write_skill(
                self._fixture.project_skill,
                "PROJECT_SKILL_V2",
                "Use the reloaded project review procedure.",
            )
        marker = (
            "PROJECT_SKILL_V2"
            if trust_record_matches_v2(self._fixture)
            else "PROJECT_SKILL_V1"
        )
        return DeterministicSkillClient(marker, self._state)
```

Render the fixed five-part Skill document, JSON ToolCall, completed/failed front matter,
and a stable ordered `evaluate_checks()` mapping. Implement `trust_record_matches_v2()` by
loading `SkillRegistry` with `confirmer=None` and checking its full rendered Skill for
`PROJECT_SKILL_V2`; do not parse or duplicate private trust-record internals.

- [x] **Step 4: Run focused tests and static checks for GREEN**

Run separately:

- `uv run pytest tests/test_m19_skills_human_smoke.py -v`
- `uv run ruff check scripts/m19-skills-human-smoke.py tests/test_m19_skills_human_smoke.py`
- `uv run ruff format --check scripts/m19-skills-human-smoke.py tests/test_m19_skills_human_smoke.py`

Expected: all focused tests pass and Ruff reports no changes or diagnostics.

- [x] **Step 5: Commit the independently testable deterministic core**

```bash
git add scripts/m19-skills-human-smoke.py tests/test_m19_skills_human_smoke.py
git commit -m "test: add deterministic M19 smoke harness"
```

### Task 2: Add the real-TTY one-command flow and public instructions

**Files:**
- Modify: `scripts/m19-skills-human-smoke.py`
- Modify: `tests/test_m19_skills_human_smoke.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-23-m19-human-smoke-design.md`

**Interfaces:**
- Consumes: Task 1's fixture, client factory, trust validation, and check matrix.
- Produces: `main() -> int` and the documented command `uv run --offline python scripts/m19-skills-human-smoke.py`.

- [x] **Step 1: Write failing tests for TTY rejection and cleanup-safe environment restoration**

```python
def test_main_rejects_non_tty_without_creating_fixture(monkeypatch, capsys):
    smoke = _load_smoke_module()
    monkeypatch.setattr(smoke.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(smoke.sys.stdout, "isatty", lambda: True)
    assert smoke.main() == 2
    assert "real interactive terminal" in capsys.readouterr().err


def test_temporary_environment_restores_home_and_cwd(tmp_path, monkeypatch):
    smoke = _load_smoke_module()
    original_home = str(tmp_path / "original-home")
    original_cwd = Path.cwd()
    monkeypatch.setenv("HOME", original_home)
    with smoke.temporary_smoke_environment(tmp_path) as fixture:
        assert Path.home() == fixture.home
        assert Path.cwd() == fixture.project
    assert os.environ["HOME"] == original_home
    assert Path.cwd() == original_cwd
```

- [x] **Step 2: Run the new tests and verify RED**

Run: `uv run pytest tests/test_m19_skills_human_smoke.py -k 'non_tty or temporary_environment' -v`

Expected: FAIL because `main()` and `temporary_smoke_environment()` are not implemented.

- [x] **Step 3: Implement the human workflow and summary**

Implement `temporary_smoke_environment()` as a context manager that restores HOME and cwd
in `finally`, isolates import-time user config paths, and temporarily hides secret-named
environment variables. Wrap the production prompt-toolkit reader so a `KeyboardInterrupt`
swallowed by `repl()` still makes the harness return 130. Implement `main()` with this order:

```python
def main() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("M19 human smoke requires a real interactive terminal.", file=sys.stderr)
        return 2
    state = SmokeState()
    with TemporaryDirectory(prefix="forgeagent-m19-human-") as raw_root:
        with temporary_smoke_environment(Path(raw_root)) as fixture:
            _print_instructions()
            repl(
                tier="restricted",
                model="mock",
                client_factory=SmokeClientFactory(fixture, state),
                use_registry_snapshot=False,
            )
            completion_ok = _ask_yes("Did slash candidates filter while typing?")
            history_ok = _ask_yes("Did Up/Down replay and restore input history?")
            trust_matches = trust_record_matches_v2(fixture)
            checks = evaluate_checks(
                state,
                trust_matches=trust_matches,
                completion_ok=completion_ok,
                history_ok=history_ok,
            )
            return _print_summary(checks, state.failures)
```

Catch `KeyboardInterrupt` only at the outer workflow boundary, print `M19 human smoke CANCELLED`,
and return 130. `_ask_yes()` accepts only `y` or `yes`; blank and all other values are false.
The summary prints every check with `PASS`/`FAIL`, then exactly one final line:
`M19 HUMAN SMOKE: PASS` or `M19 HUMAN SMOKE: FAIL`.

- [x] **Step 4: Document the one-command acceptance path and finalize the design status**

Add this short block after the README Skills runtime description:

````markdown
### M19 本地人类验收

不配置 API Key、也不访问网络即可验证项目 Skill 信任、渐进加载、`/reload`、斜杠
候选和当前会话方向键历史：

```bash
uv run --offline python scripts/m19-skills-human-smoke.py
```

该命令必须在真实交互终端运行；它使用临时 HOME/项目和确定性客户端，退出后自动清理，
不会读取或修改真实 `~/.forgeagent`。
````

Change the design front matter from `status: proposed` to `status: final`.

- [x] **Step 5: Run the full automated gate**

Run separately:

- `uv run pytest tests/test_m19_skills_human_smoke.py -v`
- `uv run pytest -q`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `git diff --check`

Expected: focused and full pytest pass; Ruff and diff checks are clean.

- [x] **Step 6: Run the real PTY success and failure paths**

Success path: run `uv run --offline python scripts/m19-skills-human-smoke.py` in a PTY, follow the seven
printed steps, answer both final questions `y`, and verify final line `M19 HUMAN SMOKE: PASS`
with exit code 0.

Failure path: run it again, exit before the two normal goals or answer one final question `n`,
and verify final line `M19 HUMAN SMOKE: FAIL` with a nonzero exit code. After each run, verify no
`forgeagent-m19-human-*` directory remains in the system temporary directory.

- [x] **Step 7: Perform two final self-review passes and commit**

First pass: compare every design acceptance item with a test, PTY observation, or final check row.
Second pass: inspect HOME/cwd restoration, no key/network reads, trust-record verification, exact
V1-before-reload/V2-after-reload order, and unrelated dirty-worktree preservation. Fix any finding
with a failing test, rerun the focused and full gates, then commit:

```bash
git add README.md scripts/m19-skills-human-smoke.py tests/test_m19_skills_human_smoke.py \
  docs/superpowers/specs/2026-07-23-m19-human-smoke-design.md \
  docs/superpowers/plans/2026-07-23-m19-human-smoke.md
git commit -m "docs: add M19 one-command human acceptance"
```

## Plan Self-Review

- Spec coverage: fixture isolation, project trust, progressive V1, reload V2, live completion,
  arrow history, automatic trust verification, human fail-closed answers, cleanup, docs, success
  and failure PTY paths all map to explicit steps.
- Placeholder scan: no TBD/TODO/later-only implementation steps remain.
- Type consistency: `SmokeFixture`, `SmokeState`, `DeterministicSkillClient`,
  `SmokeClientFactory`, `evaluate_checks`, `trust_record_matches_v2`, and `main` retain the same
  names and contracts across both tasks and tests.
