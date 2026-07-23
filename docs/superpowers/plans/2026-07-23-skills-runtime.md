---
change: skills-runtime
design-doc: docs/superpowers/specs/2026-07-23-skills-runtime-design.md
base-ref: ff7686d79df0b749ef9de76db5b361934beafe47
---

# M19 Skills Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a validated, trusted, progressively loaded SKILL.md runtime and improve the interactive REPL command reader without changing existing execution or authorization semantics.

**Architecture:** `SkillRegistry` is an immutable per-session snapshot that discovers and validates user Skills, then conditionally overlays a trusted project snapshot. `Task` exposes only its bounded catalog in the first system prompt; the existing protocol/Step feedback loop supplies full content after the read-only `Skill` tool is called. CLI and HTTP create snapshots at their existing composition boundaries, while prompt_toolkit is confined to the default interactive REPL reader.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, Rich, prompt-toolkit 3.x, uv, ruff, OpenSpec.

## Global Constraints

- Preserve the existing default sandbox, confirmation, audit, context-budget, two-phase completion, and tool feedback behaviour.
- Do not implement Skill generation, package resolution, remote download, a Skill management slash command, a workflow VM, or persistent REPL history.
- Use only `prompt-toolkit>=3.0,<4` as the new runtime dependency; update `uv.lock` with `uv lock`.
- Treat user Skills as local user configuration and project Skills as untrusted project input until their independent `skills-trust.json` double digest is approved.
- Never expose unmasked Skill content, absolute paths, raw filesystem exceptions, or untrusted candidate names in model-visible diagnostics, confirmations, or audit events.
- Keep source identifiers and user-facing runtime diagnostics in English; write repository documentation in the prevailing zh-CN style.
- Keep the verified golden-core manifest at 20 entries and its standards unchanged.

## Planned File Structure

| File | Responsibility |
| --- | --- |
| `src/forgeagent/skills.py` | Frozen Skill definitions; secure discovery, validation, masking, catalog generation, and lookup. |
| `src/forgeagent/identity.py` | Generic content-trust resolution reused by identity and Skills, preserving the v1 trust-record format. |
| `src/forgeagent/protocol.py` | Pydantic schema for the read-only `Skill` protocol call. |
| `src/forgeagent/tools.py` | `SkillTool` and conditional built-in registry registration. |
| `src/forgeagent/task.py`, `src/forgeagent/step.py` | Stable catalog prompt composition and immutable registry propagation into tool dispatch. |
| `src/forgeagent/cli.py` | CLI/REPL/HTTP snapshot assembly, project-Skill confirmation, atomic reload, and enhanced default reader. |
| `pyproject.toml`, `uv.lock` | Bounded prompt_toolkit dependency. |
| `tests/test_skills.py` | Registry, validation, containment, limits, masking, and Skill trust coverage. |
| `tests/test_identity.py`, `tests/test_protocol.py`, `tests/test_tools.py`, `tests/test_task.py`, `tests/test_step.py`, `tests/test_cli.py` | Focused regression and integration coverage at each existing extension boundary. |
| `tests/test_golden_candidates_skills.py`, `tests/golden/cases.py` | Offline progressive-loading golden candidate without changing the verified-core set. |
| `README.md`, `docs/text-protocol-spec.md`, `docs/threat-model.md`, `ACTION_PLAN.md` | Public contract, threat boundary, and M19 status documentation. |

---

### Task 1: Build the immutable Skill parser and deterministic discovery snapshot

**Files:**
- Create: `src/forgeagent/skills.py`
- Create: `tests/test_skills.py`

**Interfaces:**
- Consumes: `forgeagent.secret_policy.mask_secrets(text, sensitive_env_values())`; `IdentityConfirmer` is imported only under `TYPE_CHECKING` until Task 2 wires project trust.
- Produces: `SkillDefinition`, `SkillRegistry.load` with `home` and `allowed_root`, `SkillRegistry.catalog_prompt()`, and `SkillRegistry.read(name, section="full")` for Tasks 2-5.

- [x] **Step 1: Write the failing validation, containment, ordering, masking, and limit tests**

```python
def test_registry_accepts_only_the_fixed_five_part_document(tmp_path):
    home, root = tmp_path / "home", tmp_path / "project"
    _write_skill(home, "review-python", trigger="Use when reviewing Python.")
    registry = SkillRegistry.load(home=str(home), allowed_root=str(root), allow_project=False)
    assert registry.read("review-python") == _FULL_REVIEW_SKILL
    assert "review-python" in registry.catalog_prompt()


@pytest.mark.parametrize("document, reason", [
    (_missing_front_matter(), "invalid format"),
    (_unknown_front_matter_key(), "invalid format"),
    (_out_of_order_sections(), "invalid format"),
    (_empty_failure_branches(), "invalid format"),
    (_skill_document(name="wrong-name"), "invalid name"),
    (_skill_document(trigger="line one\\nline two"), "invalid trigger"),
])
def test_registry_ignores_invalid_document_with_bounded_diagnostic(tmp_path, document, reason):
    diagnostics: list[str] = []
    _write_raw_skill(tmp_path / "home", "review-python", document)
    registry = SkillRegistry.load(
        home=str(tmp_path / "home"), allowed_root=str(tmp_path / "root"),
        allow_project=False, diagnostic=diagnostics.append,
    )
    assert registry.catalog_prompt() == ""
    assert diagnostics == [f"skill ignored: {reason} (review-python)"]


def test_registry_rejects_project_symlink_escape_and_masks_catalog(tmp_path, monkeypatch):
    home, root, outside = tmp_path / "home", tmp_path / "root", tmp_path / "outside"
    _write_skill(home, "review-python", trigger="Use $TOKEN before release.")
    _write_skill(outside, "escaped", trigger="do not disclose")
    (root / ".forgeagent" / "skills").mkdir(parents=True)
    os.symlink(outside / ".forgeagent" / "skills" / "escaped", root / ".forgeagent" / "skills" / "escaped")
    monkeypatch.setenv("TOKEN", "secret-value")
    registry = SkillRegistry.load(home=str(home), allowed_root=str(root), allow_project=False)
    assert "secret-value" not in registry.catalog_prompt()
    assert registry.read("escaped") is None


def test_catalog_uses_sorted_prefix_when_count_or_bytes_exceed_limit(tmp_path):
    home = tmp_path / "home"
    for index in range(65):
        _write_skill(home, f"skill-{index:02d}", trigger="x" * 240)
    diagnostics: list[str] = []
    registry = SkillRegistry.load(home=str(home), allowed_root=str(tmp_path / "root"), allow_project=False, diagnostic=diagnostics.append)
    names = [line.split(" — ")[0][2:] for line in registry.catalog_prompt().splitlines()[3:]]
    assert names == sorted(names)
    assert len(names) <= 64
    assert len(registry.catalog_prompt().encode()) <= 16 * 1024
    assert diagnostics.count("skill catalog truncated") == 1
```

- [x] **Step 2: Run the new registry tests and verify RED**

Run: `uv run pytest tests/test_skills.py -v`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'forgeagent.skills'`.

- [x] **Step 3: Implement the smallest frozen parser and secure user-level discovery**

```python
@dataclass(frozen=True)
class SkillDefinition:
    name: str
    trigger: str
    steps: str
    failure_branches: str
    completion_criteria: str
    source: Literal["user", "project"]


class SkillRegistry:
    def __init__(self, definitions: Mapping[str, SkillDefinition]) -> None:
        self._definitions = MappingProxyType(dict(definitions))

    @classmethod
    def load(
        cls, *, home: str, allowed_root: str, confirmer: IdentityConfirmer | None = None,
        allow_project: bool = True, trust_record_path: str | None = None,
        diagnostic: Callable[[str], None] | None = None,
    ) -> SkillRegistry:
        user = _discover(Path(home) / ".forgeagent" / "skills", source="user", diagnostic=diagnostic)
        return cls(_bounded_catalog(user, diagnostic=diagnostic))

    def catalog_prompt(self) -> str:
        if not self._definitions:
            return ""
        lines = ["## Available Skills", "", "Choose a skill when its trigger matches the task. Read it with the Skill tool before following it."]
        lines.extend(f"- {skill.name} — {skill.trigger}" for skill in self._definitions.values())
        return "\n".join(lines)

    def read(self, name: str, section: str = "full") -> str | None:
        skill = self._definitions.get(name)
        if skill is None:
            return None
        sections = {"steps": skill.steps, "failure_branches": skill.failure_branches, "completion_criteria": skill.completion_criteria}
        if section in sections:
            return sections[section]
        if section != "full":
            return None
        return _render_full_skill(skill)
```

Implement `_discover()` with `lstat`, `realpath`, and `commonpath` checks for the root, each direct child, and its `SKILL.md`; reject dangling links, non-directories, non-regular files, and containment escapes. Parse only YAML front matter whose key set is exactly `{name, trigger}`, validate the name regex and single-line trigger, require the three exact ordered H2 headings exactly once with non-empty bodies, enforce 32 KiB per raw file, mask every retained field before constructing `SkillDefinition`, and emit only the bounded diagnostic grammar asserted by the tests. Sort directory names and make the 64-entry/16-KiB catalog truncation a stable prefix.

- [x] **Step 4: Run focused registry tests and static checks for GREEN**

Run separately:

- `uv run pytest tests/test_skills.py -v`
- `uv run ruff check src/forgeagent/skills.py tests/test_skills.py`
- `uv run ruff format --check src/forgeagent/skills.py tests/test_skills.py`

Expected: all `tests/test_skills.py` cases PASS; ruff reports no diagnostics and no formatting changes.

- [x] **Step 5: Commit the independently usable user-Skill snapshot**

```bash
git add src/forgeagent/skills.py tests/test_skills.py
git commit -m "feat: add validated user skill registry"
```

### Task 2: Reuse content trust for the trusted project-Skill overlay

**Files:**
- Modify: `src/forgeagent/identity.py`
- Modify: `src/forgeagent/skills.py`
- Modify: `tests/test_identity.py`
- Modify: `tests/test_skills.py`

**Interfaces:**
- Consumes: `SkillRegistry.load` with its `home`, `allowed_root`, `confirmer`, `allow_project`, `trust_record_path`, and `diagnostic` keyword parameters from Task 1, plus existing `canonical_project_id_digest`, `_load_trust_record`, and `_record_approval` internals.
- Produces: `resolve_project_content_trust` with `allowed_root`, `raw_content_digest`, `effective_input_digest`, `trust_record_path`, `confirmer`, `summary`, `diagnostic`, and `diagnostic_prefix` keyword parameters; it returns `bool` and permits a Registry to overlay trusted project definitions without mutating either snapshot.

- [ ] **Step 1: Lock existing identity behaviour and write failing project-Skill trust tests**

```python
def test_resolve_project_content_trust_matches_existing_record_without_confirming(tmp_path):
    common = dict(
        allowed_root=str(tmp_path / "root"), raw_content_digest="a" * 64,
        effective_input_digest="b" * 64, trust_record_path=str(tmp_path / "trust.json"),
        summary="review-python — Use when reviewing Python.", diagnostic=None,
        diagnostic_prefix="skill",
    )
    assert identity_module.resolve_project_content_trust(
        **common, confirmer=lambda _: True
    ) is True
    assert identity_module.resolve_project_content_trust(
        **common, confirmer=lambda _: pytest.fail("already-approved content must not prompt")
    ) is True


def test_project_skill_overrides_only_after_approval_and_reuses_double_digest(tmp_path):
    home, root = tmp_path / "home", tmp_path / "root"
    _write_skill(home, "review-python", trigger="user trigger")
    _write_project_skill(root, "review-python", trigger="project trigger")
    approvals = []
    registry = SkillRegistry.load(
        home=str(home), allowed_root=str(root), confirmer=lambda request: approvals.append(request) or True,
        trust_record_path=str(tmp_path / "skills-trust.json"),
    )
    assert registry.catalog_prompt().endswith("review-python — project trigger")
    assert len(approvals) == 1
    unchanged = SkillRegistry.load(home=str(home), allowed_root=str(root), confirmer=None, trust_record_path=str(tmp_path / "skills-trust.json"))
    assert unchanged.read("review-python") == registry.read("review-python")


def test_unapproved_or_unwritable_project_skill_keeps_user_definition(tmp_path, monkeypatch):
    home, root = tmp_path / "home", tmp_path / "root"
    _write_skill(home, "review-python", trigger="user trigger")
    _write_project_skill(root, "review-python", trigger="project trigger")
    registry = SkillRegistry.load(home=str(home), allowed_root=str(root), confirmer=None)
    assert registry.catalog_prompt().endswith("review-python — user trigger")
```

- [ ] **Step 2: Run trust-focused tests and verify RED**

Run: `uv run pytest tests/test_identity.py tests/test_skills.py -k 'content_trust or project_skill or resolve_project_trust' -v`

Expected: FAIL because `resolve_project_content_trust` does not exist and project definitions are not discovered.

- [ ] **Step 3: Extract the generic trust decision and add the project overlay**

```python
def resolve_project_content_trust(
    *, allowed_root: str, raw_content_digest: str, effective_input_digest: str,
    trust_record_path: str, confirmer: IdentityConfirmer | None, summary: str,
    diagnostic: IdentityDiagnostic | None, diagnostic_prefix: str,
) -> bool:
    project_id = canonical_project_id_digest(allowed_root)
    record_was_unusable = False
    try:
        record = _load_trust_record(trust_record_path)
    except _UnusableTrustRecordError as exc:
        record = None
        record_was_unusable = True
        if diagnostic is not None:
            diagnostic(f"{diagnostic_prefix} trust record ignored: {type(exc).__name__}")
    existing = record["projects"].get(project_id) if record is not None else None
    if (
        existing is not None
        and existing.get("raw_content_digest") == raw_content_digest
        and existing.get("effective_input_digest") == effective_input_digest
    ):
        return True
    if confirmer is None or not confirmer(IdentityTrustRequest(project_label=_project_label(allowed_root), summary=summary)):
        return False
    if not record_was_unusable and not _record_approval(
        trust_record_path, project_id, raw_content_digest, effective_input_digest
    ):
        if diagnostic is not None:
            diagnostic(f"{diagnostic_prefix} trust record unavailable")
    return True
```

Refactor `resolve_project_trust()` to delegate to this helper while retaining its identity-specific summary, empty-content fast path, return contract, confirmation wording, and `identity-trust.json` path. In `skills.py`, discover the project candidate fully before building a length-prefixed `name + NUL + raw bytes` raw digest and the corresponding masked-content effective digest under Skills-specific domain separators. Build the confirmation summary from valid `name — trigger` lines, truncate the display at 8 KiB with an explicit truncation marker, use `<home>/.forgeagent/skills-trust.json` by default, and overlay the complete project mapping only when the helper returns true. If record parsing/writing fails after an approved confirmation, retain only the process-local project snapshot and never overwrite the unusable record.

- [ ] **Step 4: Run identity and Skills regression tests for GREEN**

Run: `uv run pytest tests/test_identity.py tests/test_skills.py -v`

Expected: PASS, including unchanged identity trust-record tests, first approval, no-prompt digest reuse, changed digest rejection, denial, no-confirmer fallback, and atomic-record persistence tests.

- [ ] **Step 5: Commit the trust-bound project overlay**

```bash
git add src/forgeagent/identity.py src/forgeagent/skills.py tests/test_identity.py tests/test_skills.py
git commit -m "feat: trust project skills by content digest"
```

### Task 3: Add the read-only Skill protocol and conditional tool registration

**Files:**
- Modify: `src/forgeagent/protocol.py`
- Modify: `src/forgeagent/tools.py`
- Modify: `tests/test_protocol.py`
- Modify: `tests/test_tools.py`

**Interfaces:**
- Consumes: immutable `SkillRegistry.read(name, section)` from Task 1 and `ToolOutcome` bounded-feedback fields already used by File tools.
- Produces: `SkillArgs`, `SkillTool`, and `default_registry(with_mcp=False, skills=None)` for Task 4.

- [ ] **Step 1: Write failing schema, tool, unknown-name, and continuation tests**

```python
def test_skill_args_accepts_catalog_name_and_declared_section():
    assert SkillArgs(name="review-python").section == "full"
    assert SkillArgs(name="review-python", section="failure_branches").section == "failure_branches"
    with pytest.raises(ValidationError):
        SkillArgs(name="../review-python")


def test_skill_tool_returns_requested_section_without_a_confirmer(tmp_path):
    registry = _registry_with_skill(tmp_path, name="review-python")
    outcome = SkillTool(registry).run(
        SkillArgs(name="review-python", section="steps"), _survey_ctx()
    )
    assert outcome.success is True
    assert outcome.detail == "1. Inspect the diff."
    assert outcome.truncation_mode == "head"


def test_skill_tool_unknown_name_is_recoverable_and_registry_is_conditional(tmp_path):
    registry = _registry_with_skill(tmp_path, name="review-python")
    outcome = SkillTool(registry).run(SkillArgs(name="missing-skill"), _survey_ctx())
    assert (outcome.success, outcome.detail) == (False, "Skill is unavailable")
    assert "Skill" not in default_registry().arg_schemas()
    assert "Skill" in default_registry(skills=registry).arg_schemas()
```

- [ ] **Step 2: Run protocol and tool tests and verify RED**

Run: `uv run pytest tests/test_protocol.py tests/test_tools.py -k skill -v`

Expected: FAIL with import errors for `SkillArgs` and `SkillTool`.

- [ ] **Step 3: Implement the schema, tool, and registry hook**

```python
class SkillArgs(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    section: Literal["full", "steps", "failure_branches", "completion_criteria"] = "full"


class SkillTool(Tool):
    name = "Skill"
    args_model = SkillArgs
    risk_level = "low"

    def __init__(self, skills: SkillRegistry) -> None:
        self._skills = skills

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, SkillArgs)
        detail = self._skills.read(args.name, args.section)
        if detail is None:
            return ToolOutcome(tool=self.name, success=False, detail="Skill is unavailable")
        continuation = "Skill result truncated; read steps, failure_branches, or completion_criteria by name."
        return ToolOutcome(tool=self.name, success=True, detail=detail, continuation=continuation, truncation_mode="head")


def default_registry(*, with_mcp: bool = False, skills: SkillRegistry | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ExecTool())
    registry.register(EditTool())
    registry.register(SurveyTool())
    registry.register(WebFetchTool())
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    registry.register(FileListTool())
    if skills is not None and skills.catalog_prompt():
        registry.register(SkillTool(skills))
    if with_mcp:
        registry.register(MCPTool())
    return registry
```

Import `Literal` where needed. Do not add path arguments, filesystem operations, confirmation handling, audit content fields, or a special parser branch: the existing dynamic `arg_schemas()` mechanism must validate this tool only when it is actually registered.

- [ ] **Step 4: Run focused protocol/tool tests for GREEN**

Run separately:

- `uv run pytest tests/test_protocol.py tests/test_tools.py -k skill -v`
- `uv run ruff check src/forgeagent/protocol.py src/forgeagent/tools.py tests/test_protocol.py tests/test_tools.py`

Expected: PASS; malformed names fail Pydantic validation, unknown valid names return `success=False`, and no-Skills registries do not advertise `Skill`.

- [ ] **Step 5: Commit the protocol-compatible read-only tool**

```bash
git add src/forgeagent/protocol.py src/forgeagent/tools.py tests/test_protocol.py tests/test_tools.py
git commit -m "feat: add read-only skill tool"
```

### Task 4: Thread the snapshot through Task and Step for progressive loading

**Files:**
- Modify: `src/forgeagent/task.py`
- Modify: `src/forgeagent/step.py`
- Modify: `tests/test_task.py`
- Modify: `tests/test_step.py`

**Interfaces:**
- Consumes: `SkillRegistry.catalog_prompt()` and `default_registry(skills=registry)` from Tasks 1 and 3.
- Produces: the `skills: SkillRegistry | None = None` keyword parameter on both `Task` and `Step`, used by Task 5.

- [ ] **Step 1: Write failing prompt-order and feedback-loop tests**

```python
def test_task_catalog_is_after_identity_before_mcp_and_omits_skill_body(tmp_path):
    skills = _registry_with_unique_skill(tmp_path, marker="SKILL-BODY-UNIQUE")
    task = Task(MockClient(script=[_reply(_done())]), identity=_identity_with_memory(), skills=skills, mcp=_mcp_with_prompt("## MCP Tools"))
    prompt = task._build_system_prompt()
    assert "review-python — Use when reviewing Python." in prompt
    assert "SKILL-BODY-UNIQUE" not in prompt
    assert prompt.index("## Project Memory") < prompt.index("## Available Skills") < prompt.index("## MCP Tools")


def test_skill_full_content_arrives_only_as_next_round_feedback(tmp_path):
    skills = _registry_with_unique_skill(tmp_path, marker="SKILL-BODY-UNIQUE")
    client = MockClient(script=[_reply(_tool_call("Skill", {"name": "review-python"})), _reply(_done())])
    outcome = Task(client, skills=skills).run("review this")
    assert "SKILL-BODY-UNIQUE" not in client.requests[0][0].content
    assert "SKILL-BODY-UNIQUE" in client.requests[1][-1].content
    assert outcome.status.completed is True


def test_no_skills_keeps_existing_system_prompt_and_unknown_skill_parse_feedback():
    baseline = Task(MockClient(script=[_reply(_done())]))._build_system_prompt()
    assert Task(MockClient(script=[_reply(_done())]), skills=None)._build_system_prompt() == baseline
```

- [ ] **Step 2: Run prompt and Step feedback tests and verify RED**

Run: `uv run pytest tests/test_task.py tests/test_step.py -k skill -v`

Expected: FAIL because `Task.__init__` and `Step.__init__` do not accept `skills` and the first prompt lacks the catalog.

- [ ] **Step 3: Implement stable prompt composition and propagation without semantic bypasses**

```python
class Task:
    # Add this exact keyword parameter immediately after memory_manager:
    # skills: SkillRegistry | None = None,
    # Then store it with the existing constructor assignments:
    self._skills = skills

    def _build_system_prompt(self) -> str:
        if self._system_prompt is not None:
            base = self._system_prompt
        else:
            identity = self._identity or ApprovedIdentity(
                soul=None, user=None, project_agents=None, memory=None
            )
            if self._memory_manager is not None:
                identity = ApprovedIdentity(
                    soul=identity.soul,
                    user=identity.user,
                    project_agents=identity.project_agents,
                    memory=self._memory_manager.render() or None,
                )
            base = compose_system_prompt(identity)
        sections = [base]
        catalog = self._skills.catalog_prompt() if self._skills is not None else ""
        if catalog:
            sections.append(catalog)
        if self._mcp is not None and (tools_section := self._mcp.tools_prompt()):
            sections.append(tools_section)
        return "\n\n".join(sections)

        # Pass skills=self._skills at the existing Step construction in Task.run.

class Step:
    # Add this exact keyword parameter immediately after context_policy:
    # skills: SkillRegistry | None = None,
    # Use it directly at the existing registry construction site:
    self._registry = registry or default_registry(
        with_mcp=mcp is not None, skills=skills
    )
```

Use the existing `Step` registry creation site rather than maintaining a parallel parser registry. Preserve the exact existing parse result for a fabricated `Skill` call when no registry is supplied, preserve the current `render_bounded_feedback()` path for all Skill outcomes, and do not add a completion signal or authorization exception for Skill content.

- [ ] **Step 4: Run focused task/Step tests for GREEN**

Run: `uv run pytest tests/test_task.py tests/test_step.py -k skill -v`

Expected: PASS; first request contains only catalog metadata, second-round feedback contains masked full content, and existing completion/confirmation/sandbox behavior remains unchanged.

- [ ] **Step 5: Commit progressive loading at the execution boundary**

```bash
git add src/forgeagent/task.py src/forgeagent/step.py tests/test_task.py tests/test_step.py
git commit -m "feat: load skill content on demand in tasks"
```

### Task 5: Assemble immutable Skill snapshots in CLI, reload, and HTTP

**Files:**
- Modify: `src/forgeagent/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `SkillRegistry.load`, `Task(client, skills=registry)`, `IdentityTrustRequest`, and `IdentityDiagnostic` from earlier tasks.
- Produces: `_load_skill_registry` with `home`, `allowed_root`, `no_identity`, `confirmer`, and `diagnostic` keyword parameters; it returns `SkillRegistry`. Also produces `make_console_skill_confirmer(console, read_line) -> IdentityConfirmer` and a single service-start snapshot closed over by the HTTP `TaskFactory`.

- [ ] **Step 1: Write failing lifecycle, degradation, replacement, and request-isolation tests**

```python
def test_run_once_threads_supplied_skill_snapshot_to_task(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(cli_module, "Task", lambda client, **kwargs: captured.setdefault("task", _FakeTask(**kwargs)))
    run_once("goal", tier="restricted", model="mock", client_factory=lambda _: MockClient(script=[]), skills=_registry_with_skill(tmp_path))
    assert captured["task"].skills.read("review-python") is not None


def test_repl_reload_swaps_skills_only_after_all_candidates_are_valid(monkeypatch, tmp_path):
    old, new = _registry_with_skill(tmp_path / "old"), _registry_with_skill(tmp_path / "new")
    monkeypatch.setattr(cli_module, "_load_skill_registry", lambda **_: new)
    observed = _run_repl_goals(monkeypatch, ["/reload", "goal", "quit"], skills=old)
    assert observed[0].read("review-python") == new.read("review-python")


# Extend the existing
# test_serve_builds_server_owned_task_factory_and_closes_in_order:
skills = _registry_with_skill(tmp_path / "home", name="user-only")
monkeypatch.setattr(cli_module, "_load_skill_registry", lambda **_: skills)

# After constructing task and other_task from captured["factory"]:
assert task._skills is other_task._skills is skills
assert task._skills.read("project-only") is None
```

- [ ] **Step 2: Run CLI and HTTP lifecycle tests and verify RED**

Run: `uv run pytest tests/test_cli.py -k skill -v`

Expected: FAIL because `run_once`, `repl`, and the HTTP factory have no `skills` argument or loader.

- [ ] **Step 3: Implement the composition-boundary loader and atomic reload**

```python
def make_console_skill_confirmer(console: Console, read_line: Callable[[str], str]) -> IdentityConfirmer:
    def confirm(request: IdentityTrustRequest) -> bool:
        console.print(Text(f"trust project Skills {request.project_label}", style="bold yellow"))
        console.print(request.summary, markup=False)
        try:
            return read_line("load these project Skills? [y/N] ").strip().lower() in {"y", "yes"}
        except EOFError:
            return False
    return confirm


def _load_skill_registry(*, home: str, allowed_root: str, no_identity: bool, confirmer: IdentityConfirmer | None, diagnostic: IdentityDiagnostic) -> SkillRegistry:
    return SkillRegistry.load(
        home=home, allowed_root=allowed_root, allow_project=not no_identity,
        confirmer=None if no_identity else confirmer, diagnostic=diagnostic,
    )
```

Add `skills: SkillRegistry | None = None` to `run_once()` and pass it to `Task`. In `repl()`, create the reader before the confirmer, load one initial snapshot, pass it to every `run_once()`, and on `/reload` construct models, context, identity, memory, and candidate Skills before replacing all current references together. A rejected project candidate is a successful user-Skill-only snapshot; configuration exceptions keep the old snapshot. At HTTP service startup, resolve home/root/no-identity once, call the loader with `confirmer=None`, and close that registry over the existing `TaskFactory`; do not add fields, endpoints, file watchers, or per-request discovery.

- [ ] **Step 4: Run the focused CLI and HTTP regression suite for GREEN**

Run: `uv run pytest tests/test_cli.py -k 'skill or reload or factory' -v`

Expected: PASS; interactive approval uses Skill-specific wording, no-identity skips project discovery, headless startup does not block, reload is all-or-nothing, and each request gets the same immutable snapshot but a fresh Task/Step/Runtime.

- [ ] **Step 5: Commit lifecycle assembly independently of REPL UI changes**

```bash
git add src/forgeagent/cli.py tests/test_cli.py
git commit -m "feat: load skill snapshots in cli and http"
```

### Task 6: Add the bounded interactive REPL reader and current-session history

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/forgeagent/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `_SLASH_COMMAND_USAGE` in `cli.py`; explicit `read_line` injection and current console/TTY behavior.
- Produces: `_make_interactive_reader() -> Callable[[str], str]`, used only when `repl(read_line=None)` has interactive stdin and stdout.

- [ ] **Step 1: Write failing enhanced-reader selection, completion, and history tests**

```python
def test_repl_explicit_reader_never_constructs_prompt_session(monkeypatch):
    monkeypatch.setattr(cli_module, "PromptSession", lambda *args, **kwargs: pytest.fail("must not construct"))
    repl(tier="restricted", model="mock", client_factory=_client_factory, read_line=lambda _: "quit")


def test_default_interactive_reader_uses_command_table_and_memory_history(monkeypatch):
    captured = {}
    class FakeSession:
        def __init__(self, **kwargs): captured.update(kwargs)
        def prompt(self, prompt): return "quit"
    monkeypatch.setattr(cli_module, "PromptSession", FakeSession)
    monkeypatch.setattr(cli_module.sys.stdin, "isatty", lambda: True)
    repl(tier="restricted", model="mock", client_factory=_client_factory, console=_terminal_console(), read_line=None)
    completer = captured["completer"]
    assert {item.text for item in completer.get_completions(Document("/mo"), CompleteEvent())} == {"/model"}
    assert isinstance(captured["history"], InMemoryHistory)
    assert "FileHistory" not in repr(captured)


def test_non_tty_default_reader_uses_builtin_input(monkeypatch):
    monkeypatch.setattr(cli_module.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: "quit")
    repl(tier="restricted", model="mock", client_factory=_client_factory, read_line=None)
```

- [ ] **Step 2: Run reader tests and verify RED**

Run: `uv run pytest tests/test_cli.py -k 'prompt_session or interactive_reader or non_tty' -v`

Expected: FAIL because `repl` defaults to the bound `input` callable and `prompt_toolkit` is not a dependency.

- [ ] **Step 3: Add the dependency and isolate enhanced input to the default interactive path**

```toml
dependencies = [
    "pydantic>=2.0",
    "anthropic>=0.40",
    "jinja2>=3.1",
    "rich>=13.0",
    "pyyaml>=6.0",
    "openai>=2.24,<3",
    "mcp>=1.28.1",
    "prompt-toolkit>=3.0,<4",
]
```

```python
def _make_interactive_reader() -> Callable[[str], str]:
    completer = WordCompleter(
        list(_SLASH_COMMAND_USAGE), meta_dict=_SLASH_COMMAND_USAGE,
        sentence=True, match_middle=False,
    )
    session = PromptSession(history=InMemoryHistory(), completer=completer, complete_while_typing=True)
    return session.prompt


def repl(
    *,
    tier: Tier,
    model: str,
    client_factory: ClientFactory,
    console: Console | None = None,
    read_line: Callable[[str], str] | None = None,
    confirmation_available: bool | None = None,
    container_image: str | None = None,
    stream: bool = False,
    no_identity: bool = False,
    no_memory: bool = False,
    context_config: ContextConfig | None = None,
    registry: Registry | None = None,
    use_registry_snapshot: bool | None = None,
) -> None:
    console = console or Console()
    if read_line is None:
        read_line = _make_interactive_reader() if console.is_terminal and sys.stdin.isatty() else input
```

Run `uv lock` after editing `pyproject.toml`. Keep the PromptSession local to one REPL invocation, use no custom key bindings, and do not use `FileHistory`; default menu behavior provides candidate navigation with arrows and history navigation when its completion menu is inactive. Retain current handling of EOF, `KeyboardInterrupt`, blank input, `quit`, `exit`, Survey, confirmations, and all explicitly injected readers.

- [ ] **Step 4: Run enhanced reader and all REPL regression tests for GREEN**

Run separately:

- `uv run pytest tests/test_cli.py -k 'repl or prompt_session or interactive_reader' -v`
- `uv run ruff check src/forgeagent/cli.py tests/test_cli.py`
- `uv run ruff format --check src/forgeagent/cli.py tests/test_cli.py`

Expected: PASS; `/`, `/m`, and `/mo` completion candidates derive from `_SLASH_COMMAND_USAGE`, accepted commands remain editable, history is in-memory only, and non-TTY/test readers retain old behavior.

- [ ] **Step 5: Commit the isolated REPL dependency and reader**

```bash
git add pyproject.toml uv.lock src/forgeagent/cli.py tests/test_cli.py
git commit -m "feat: enhance interactive repl command input"
```

### Task 7: Add the offline progressive-loading golden candidate

**Files:**
- Create: `tests/test_golden_candidates_skills.py`
- Modify: `tests/golden/cases.py`
- Modify: `docs/golden-tasks-seed.md`

**Interfaces:**
- Consumes: Task 4's initial-prompt/second-round feedback behavior and the existing offline golden runner abstractions.
- Produces: an M19 candidate test that proves successful use of a Skill and a no-Skill control without editing `tests/golden/manifest.py`.

- [ ] **Step 1: Write the failing deterministic Skill golden candidate tests**

```python
def test_skill_candidate_reads_catalog_then_uses_skill_feedback(tmp_path):
    result = run_skill_candidate(tmp_path)
    assert result.passed is True
    assert "Skill" in result.first_request
    assert "UNIQUE-SKILL-STEP" not in result.first_request
    assert "UNIQUE-SKILL-STEP" in result.second_request


def test_no_skill_control_never_advertises_or_registers_skill(tmp_path):
    result = run_no_skill_control(tmp_path)
    assert result.passed is True
    assert "## Available Skills" not in result.first_request
    assert '"name":"Skill"' not in result.first_request
```

- [ ] **Step 2: Run candidate tests and verify RED**

Run: `uv run pytest tests/test_golden_candidates_skills.py -v`

Expected: FAIL because the M19 candidate helper/case does not exist.

- [ ] **Step 3: Implement deterministic candidate scripts and seed documentation**

```python
def run_skill_candidate(tmp_path: Path) -> CandidateResult:
    skills = _registry_with_skill(tmp_path, marker="UNIQUE-SKILL-STEP")
    client = MockClient(script=[_reply(_skill_call("review-python")), _reply(_completed_after_exec())])
    outcome = Task(client, skills=skills).run("review the change")
    return CandidateResult(
        passed=outcome.status.completed,
        first_request=_system_text(client.requests[0]),
        second_request=_system_text(client.requests[1]),
    )
```

Register the candidate only in the candidate test module or an existing non-verified candidate collection. In the seed document, specify the fixture SKILL.md, first-round `Skill` call, required second-round marker, and no-Skill counterpart. Do not add it to the 20-item core manifest or alter its ID/count assertion.

- [ ] **Step 4: Run the candidate and unchanged verified core for GREEN**

Run separately:

- `uv run pytest tests/test_golden_candidates_skills.py -v`
- `uv run python scripts/run_golden_core.py`

Expected: new candidate tests PASS and the golden core reports exactly `20/20` passing.

- [ ] **Step 5: Commit the M19 golden evidence**

```bash
git add tests/test_golden_candidates_skills.py tests/golden/cases.py docs/golden-tasks-seed.md
git commit -m "test: cover progressive skill loading"
```

### Task 8: Document the contract and complete the full change verification

**Files:**
- Modify: `README.md`
- Modify: `docs/text-protocol-spec.md`
- Modify: `docs/threat-model.md`
- Modify: `ACTION_PLAN.md`

**Interfaces:**
- Consumes: final public contract from Tasks 1-7.
- Produces: user-facing SKILL.md example, `Skill` ToolCall syntax, updated project-input threat model, and M19 implementation status; no executable interface.

- [ ] **Step 1: Add a documentation acceptance checklist before editing prose**

```text
README: shows exact five-part SKILL.md and states user/project roots.
Protocol: documents name and optional section values with an HTML ToolCall example.
Threat model: names project Skills as confirmation-bound project input, secret masking, snapshot lifetime, and unchanged tool authorization.
ACTION_PLAN: records M19 only after all verification commands in this task pass.
```

- [ ] **Step 2: Verify the checklist is currently unmet**

Run: `rg -n 'SKILL.md|"name":"Skill"|skills-trust.json|M19.*已完成' README.md docs/text-protocol-spec.md docs/threat-model.md ACTION_PLAN.md`

Expected: no complete five-part runtime contract and no M19-completed status are present before this task.

- [ ] **Step 3: Write the precise public contract and then run all validation**

```markdown
---
name: review-python
trigger: Use when reviewing Python changes before completion.
---

## Steps

1. Inspect the diff and affected call paths.

## Failure branches

- If focused tests fail, report the exact failure and stop completion.

## Completion criteria

- Findings are resolved or explicitly reported.
```

Document `<home>/.forgeagent/skills/` and `<project>/.forgeagent/skills/`, the independent `skills-trust.json` double-digest approval, the `Skill` arguments `name` and `section`, the bounded catalog/full-content split, and the fact that a Skill cannot grant tool or sandbox permissions. Update `ACTION_PLAN.md` only with the verified implementation summary and exact validation result after Step 4 succeeds.

- [ ] **Step 4: Execute the completion gate and record exact outcomes**

Run separately:

- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run python scripts/run_golden_core.py`
- `openspec validate skills-runtime --strict`
- `uv build`
- `git diff --check`

Expected: full pytest PASS; ruff reports no diagnostics/format changes; golden core is `20/20`; OpenSpec strict validation PASS; `uv build` emits wheel and sdist; `git diff --check` emits no whitespace errors.

- [ ] **Step 5: Perform two whole-change review passes and commit the documentation only when clean**

```bash
git diff --check
git diff -- src/forgeagent/skills.py src/forgeagent/identity.py src/forgeagent/protocol.py src/forgeagent/tools.py src/forgeagent/task.py src/forgeagent/step.py src/forgeagent/cli.py
git add README.md docs/text-protocol-spec.md docs/threat-model.md ACTION_PLAN.md
git commit -m "docs: document skills runtime"
```

First review verifies all delta scenarios have a focused test and no content/absolute-path leak. Second review verifies constructor/signature propagation, Registry immutability, no Skill-specific completion/permission bypass, no persistent history, and no changes to the verified core manifest. If either pass finds a defect, add a focused failing test, correct it in the owning task's files, and rerun that task's focused command plus this task's full completion gate before committing the documentation.

## Requirement Coverage Review

| Delta requirement | Implementing task | Evidence |
| --- | --- | --- |
| Fixed five-part SKILL.md validation and bounded discovery | 1 | `tests/test_skills.py` parser, containment, masking, count, and byte-limit tests |
| Trusted project-overrides-user semantics | 2 | identity reuse and project-overlay double-digest tests |
| Bounded initial catalog only | 1, 4 | catalog limits and unique-body-marker system-prompt test |
| On-demand read-only Skill tool and recoverable unknown name | 3, 4 | schema/tool tests and two-round feedback replay |
| No completion, confirmation, or sandbox bypass | 4 | existing Step dispatch path plus focused completion/feedback regression |
| CLI/HTTP immutable snapshot lifecycle and reload | 5 | `run_once`, REPL reload, and HTTP factory tests |
| Interactive slash completion and nonpersistent history | 6 | injected-reader, TTY, non-TTY, completer, and history tests |
| Golden candidate, documentation, and project status | 7, 8 | candidate/control, golden `20/20`, docs, OpenSpec, build, and diff checks |

## Plan Self-Review

- Spec coverage: every requirement and scenario in both delta specs maps to Tasks 1-8 above; no additional capability is planned.
- Placeholder scan: clean; every implementation step names its exact files, test function, command, expected outcome, and commit boundary.
- Type consistency: `SkillDefinition`, `SkillRegistry`, `SkillArgs`, `SkillTool`, `Task.skills`, `Step.skills`, and `default_registry(skills=registry)` use the same names and compatible optional types throughout.

Plan complete and saved to `docs/superpowers/plans/2026-07-23-skills-runtime.md`. Execution options: use `subagent-driven-development` for one fresh implementer and review gate per task, or `executing-plans` for inline task batches with checkpoints.
