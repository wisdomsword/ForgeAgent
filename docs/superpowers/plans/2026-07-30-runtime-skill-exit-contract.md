# Runtime Skill Exit Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a versioned runtime Skill contract that fail-closed validates five bounded exit classes while preserving legacy Skill compatibility.

**Architecture:** Extend `src/forgeagent/skills.py` with version-aware parsing and immutable exit metadata. Keep the existing discovery/trust pipeline, append governed exits only to version 2 rendering, and expose them through the existing read-only Skill tool. Use focused regression tests before implementation, then update the canonical spec and governance docs after behavior is verified.

**Tech Stack:** Python 3.11+, PyYAML, dataclasses, pytest, uv, ruff, OpenSpec/Comet.

## Global Constraints

- Do not migrate existing legacy `SKILL.md` files; only explicit `format_version: 2` requires exits.
- Do not add dependencies, remote Skill distribution, execution permissions, sandbox changes, PyPI upload, tag, or push.
- Preserve secret masking, deterministic ordering, bounded diagnostics, project double-digest trust, and legacy full-read output.
- Production code is written only after a failing test has been observed.

---

### Task 1: Add Failing Versioned Contract Tests

**Files:**
- Modify: `tests/test_skills.py`
- Test: `tests/test_skills.py`

**Interfaces:**
- Consumes: Existing `_skill_document`, `_write_raw_skill`, and `SkillRegistry.load` helpers.
- Produces: Failing behavior tests that define `format_version: 2`, `exit_conditions`, version exposure, and section reads.

- [ ] **Step 1: Write the failing tests**

Add fixtures and tests for:

```python
_GOVERNED_SKILL = """---
name: review-python
trigger: Use when reviewing Python.
format_version: 2
exit_conditions:
  success:
    condition: Review report exists and names each finding.
    verifier: reviewer checks the saved report and finding count.
  failure:
    condition: A required source file cannot be read.
    verifier: tool result records the read error.
  blocked:
    condition: Required approval is unavailable.
    verifier: approval gate records the missing approver.
  needs_input:
    condition: The task lacks a target branch.
    verifier: user response records the branch name.
  timeout_or_budget:
    condition: The loop reaches its configured round budget.
    verifier: loop checkpoint records the budget stop.
---

## Steps

1. Read the changed code.

## Failure Branches

- Ask for the missing context.

## Completion Criteria

- Report the findings.
"""

def test_registry_accepts_governed_skill_and_reads_exit_conditions(tmp_path):
    _write_raw_skill(tmp_path / "home", "review-python", _GOVERNED_SKILL)
    registry = SkillRegistry.load(
        home=str(tmp_path / "home"),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
    )
    definition = registry._definitions["review-python"]
    assert definition.format_version == 2
    assert "success" in definition.exit_conditions
    assert "## Exit Conditions" in registry.read("review-python")
    assert "round budget" in registry.read("review-python", "exit_conditions")
```

Also add tests for missing exit class, unsupported version, overlong condition, and pure absolute condition; each must yield no registry entry and exactly one bounded diagnostic.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_skills.py -q`

Expected: FAIL because `SkillDefinition` has no `format_version`/`exit_conditions` and version 2 documents are currently rejected as invalid format.

### Task 2: Implement Minimal Version-Aware Parsing

**Files:**
- Modify: `src/forgeagent/skills.py`
- Test: `tests/test_skills.py`

**Interfaces:**
- Consumes: Task 1 failing tests and existing `_parse_document`, `_parse_sections`, `_render_full_skill`.
- Produces: `SkillDefinition.format_version: int`, immutable `exit_conditions`, and deterministic parser validation.

- [ ] **Step 1: Add bounded parsing constants and immutable data shape**

Use a fixed tuple of exit names and a frozen dataclass for one exit pair; store a `MappingProxyType` in `SkillDefinition` so callers cannot mutate the registry snapshot.

- [ ] **Step 2: Extend front-matter validation**

Keep the exact legacy key set for version 1. For version 2, require only `name`, `trigger`, `format_version`, and `exit_conditions`; reject duplicate/unknown keys, unsupported versions, missing classes, wrong types, empty strings, strings over 512 UTF-8 bytes, and pure absolute conditions with `ValueError("invalid exit contract")`.

- [ ] **Step 3: Run focused tests to verify they pass**

Run: `uv run pytest tests/test_skills.py -q`

Expected: PASS for governed/legacy parsing and all rejection cases.

### Task 3: Render and Expose Governed Exits

**Files:**
- Modify: `src/forgeagent/skills.py`
- Modify: `src/forgeagent/tools.py` only if the existing SkillTool section allow-list needs the new section.
- Test: `tests/test_skills.py`, `tests/test_tools.py`

**Interfaces:**
- Consumes: Task 2 `SkillDefinition.exit_conditions`.
- Produces: Governed full rendering, `read(name, "exit_conditions")`, masking, and unchanged legacy output.

- [ ] **Step 1: Add failing rendering/tool tests**

Assert legacy `registry.read(name)` remains exactly the original fixture, governed full reads include a fixed `## Exit Conditions` section, and SkillTool accepts `section="exit_conditions"` for governed definitions while returning deterministic failure for legacy/unknown requests.

- [ ] **Step 2: Run the new tests to verify failure**

Run: `uv run pytest tests/test_skills.py tests/test_tools.py -q`

Expected: FAIL because the new section is not rendered or accepted yet.

- [ ] **Step 3: Implement minimal rendering/allow-list changes**

Add fixed-order output and route all values through the existing secret masking path. Do not alter SkillTool protocol outside the section allow-list.

- [ ] **Step 4: Run focused tests to verify pass**

Run: `uv run pytest tests/test_skills.py tests/test_tools.py -q`

Expected: PASS with legacy byte-for-byte read preserved.

### Task 4: Verify Trust, Reload, and Regression Boundaries

**Files:**
- Modify: `tests/test_skills.py`, `tests/test_task.py`, or existing reload test file only where a regression assertion is needed.
- Modify: `docs/agent-governance-gates.md` if runtime enforcement wording needs alignment.

**Interfaces:**
- Consumes: Governed rendering from Task 3 and existing project trust/reload paths.
- Produces: Regression evidence that exit-only project changes invalidate effective trust and reload atomically replaces snapshots.

- [ ] **Step 1: Add failing trust/reload assertions**

Change only one governed exit verifier between two loads and assert the confirmer is invoked again; load a corrected document and assert a fresh registry sees it while the previous snapshot remains unchanged.

- [ ] **Step 2: Run the tests to verify failure**

Run: `uv run pytest tests/test_skills.py tests/test_task.py -q`

Expected: FAIL before the effective digest includes governed rendering and before the reload assertion can observe the new section.

- [ ] **Step 3: Apply the smallest digest/reload integration adjustment**

Reuse `_render_full_skill` in the existing digest path; do not add a second trust mechanism or mutable global registry.

- [ ] **Step 4: Run the tests to verify pass**

Run: `uv run pytest tests/test_skills.py tests/test_task.py -q`

Expected: PASS.

### Task 5: Update Canonical Specs and Complete Verification

**Files:**
- Modify: `openspec/specs/skills-runtime/spec.md`
- Modify: `docs/reviews/2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md`
- Modify: `docs/reviews/2026-07-30-agent开发指南评审-借鉴清单.md`
- Create: `docs/superpowers/reports/2026-07-30-runtime-skill-exit-contract-verify.md`

**Interfaces:**
- Consumes: Verified runtime behavior and change delta specs.
- Produces: Canonical documentation, evidence report, and complete Comet change artifacts.

- [ ] **Step 1: Update the canonical Skill spec**

Replace the archived `Purpose: TBD` with the actual runtime Skill purpose and add version 2 exit-contract and legacy-compatibility scenarios without deleting existing requirements.

- [ ] **Step 2: Mark the governance checklist runtime enforcement as delivered**

Change only the status sentence for the runtime auto-reject item; keep Memory migration, Rewrite/dependency, remote Skills, and PyPI freeze unchanged.

- [ ] **Step 3: Run the full verification matrix**

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
git diff --check
openspec validate --all --strict --no-interactive
uv build
```

Expected: all commands exit 0; `uv build` only creates local artifacts and performs no upload/tag/push.

- [ ] **Step 4: Write exact evidence and check all tasks**

Record command outputs/counts and any skipped tests in the verification report, then mark every task checkbox complete and run the Comet build/verify guards.
