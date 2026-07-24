---
change: eval-evaluator
design-doc: docs/superpowers/specs/2026-07-24-eval-evaluator-design.md
base-ref: b114f0c21ca8c60e591a6105314aed14e6170da0
---

# M20 Eval-Evaluator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变普通 Task、HTTP、M19 Skills 或 20 项可信 golden core 的前提下，提供离线评估记录/趋势和显式 opt-in 的隔离 Evaluator。

**Architecture:** 新建 `forgeagent.evaluation` 作为窄的、纯 Python 的证据边界：它只接受 golden v1 mapping、审计事件 projection 和明确的 `TaskOutcomeProjection`，产生受严格 schema 限制的 evaluation v1 record。golden manifest 通过提交内 baseline 的有序 SHA-256 fingerprint 在 runner preflight 中防漂移。独立 Evaluator 位于 `forgeagent.evaluator`，由 CLI `evaluate` 子命令显式调用；它先完成模型凭证与 artifact manifest preflight，随后以没有 Generator state、Memory、Skills、MCP 或 audit sink 的新 `Task` 执行。

**Tech Stack:** Python >=3.11、Pydantic v2、标准库 `json`/`hashlib`/`math`/`os`/`tempfile`/`pathlib`、现有 pytest、ruff、现有 `ModelClient`/`Task`/FileRead/FileList 工具；不新增依赖、服务、数据库或 HTTP 路由。

## Global Constraints

- 基线提交为 `b114f0c21ca8c60e591a6105314aed14e6170da0`；实施前确认工作树的既有变更不被回退或混入。
- 所有基础 CI 必须无 API key、无网络；真实模型 Evaluator 只能由显式 `evaluate --model MODEL_ID` 调用。
- 保持既有 M19 Skills 权限和启动输出、普通 `run`/REPL/`serve` 行为、HTTP schema 与 20 项 approved core 的 ID/title/real eligibility 不变。
- `first_pass_correctness`、`correction_rounds`、`cache_hit_rate` 的缺失或无效证据必须是 JSON `null`，不得伪造 `0`、`100` 或 NaN/Infinity。
- record、trend、CLI 输出和 evaluator feedback 不得保存/显示 prompt、model messages、原始 tool args、完整 audit parameters、secret、绝对路径或未受限内容。
- Evaluator artifact 必须是 evaluation root 下的相对文件，单项和总数均有固定上限；artifact 内容一律按不可信数据处理，而非指令。
- 继续使用默认 `restricted` sandbox；Evaluator 不注入 Generator conversation、Memory、`SkillRegistry`、MCP 或 Generator audit sink，也不扩大工具权限。
- 不新增第三方依赖、常驻服务、scheduler、数据库、HTTP endpoint、Planner 角色或 manifest baseline 自动更新机制。
- 每个任务先写失败测试，再实现最小代码；完成前运行本任务测试和对应 ruff 检查。

---

## File Structure

- Create: `src/forgeagent/evaluation.py` — `forgeagent.evaluation.v1` schema、安全 audit projection、指标聚合、record 原子读写、bounded trend 与 delta。
- Create: `src/forgeagent/evaluator.py` — 有界 artifact manifest、隔离 evaluator request/prompt、Task 调用和安全 result projection。
- Create: `tests/test_evaluation.py` — evaluation schema、投影、指标、持久化和 trend 的离线表驱动合同。
- Create: `tests/test_evaluator.py` — artifact containment/size、session isolation、known-fail 注入、凭证 preflight 和安全结果合同。
- Create: `tests/golden/manifest_baseline.json` — 只读 approved 20 scenario 的有序 `(scenario_id, title, run_real)` 表和 SHA-256 fingerprint。
- Modify: `tests/golden/manifest.py` — 导出稳定的 `manifest_fingerprint()` 和 baseline 载入辅助，不修改 `GOLDEN_SCENARIOS`。
- Modify: `tests/golden/runner.py` — 在原有 ID/catalog preflight 前验证 canonical baseline；保留既有离线/real 运行和报告 schema。
- Modify: `tests/test_golden_runner.py` — 表驱动验证删除、替换、标题、eligibility、顺序漂移以及匹配 baseline。
- Modify: `src/forgeagent/cli.py` — 增加显式 `evaluate` facade 与 evaluation report/trend 输出；普通路径不初始化 evaluator。
- Modify: `tests/test_cli.py` — `evaluate` 的 parser、preflight、隔离装配、输出与 persistence error 合同。
- Modify: `README.md` — 记录 evaluate 的 opt-in 成本、artifact contract、离线 golden/evaluation 使用方法和不进入 CI 的界限。
- Modify: `docs/threat-model.md` — 新增 evaluator artifact prompt-injection、路径/大小、会话隔离、敏感数据投影及残余风险说明。
- Modify: `docs/text-protocol-spec.md` — 说明 evaluator 结构化终止结果的专用文本协议，且不改变 Generator 两阶段完成语义。
- Modify: `ACTION_PLAN.md` — 更新 M20 的交付、验证和状态证据，不更新后续里程碑范围。
- Create: `milestones/milestone_020.md` — 仅在所有 M20 验证和三评审完成后，依 `MILESTONE_GUIDE.md` 记录收尾证据。
- Modify: `milestones/latest` — 仅在 `milestone_020.md` 完成后，写入唯一一行 `milestone_020.md`。

## Task 1: Protect the trusted golden manifest

**Files:**
- Create: `tests/golden/manifest_baseline.json`
- Modify: `tests/golden/manifest.py:1-49`
- Modify: `tests/golden/runner.py:129-160`
- Modify: `tests/test_golden_runner.py:402-430,956-1027`

**Interfaces:**
- Consumes: `GOLDEN_SCENARIOS: tuple[GoldenScenario, ...]` and its existing ordered `scenario_id`, `title`, `run_real` fields.
- Produces: `manifest_fingerprint(scenarios: Sequence[GoldenScenario] = GOLDEN_SCENARIOS) -> str`; `load_manifest_baseline(path: Path | None = None) -> tuple[tuple[str, str, bool], ...]`; `validate_manifest()` rejects any baseline mismatch before catalog or output-directory work.

- [ ] **Step 1: Write the failing baseline contract tests**

```python
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
```

Import `replace` from `dataclasses`. Add a success case proving the unmodified tuple still validates and a malformed/mismatched baseline fixture case that raises the same safe `GoldenPreflightError` without creating an output directory.

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `uv run pytest tests/test_golden_runner.py -k 'baseline or manifest_fingerprint' -v`

Expected: FAIL because `manifest_fingerprint`/baseline validation do not yet exist, while unrelated current golden tests remain untouched.

- [ ] **Step 3: Add the fixed baseline and minimal fingerprint implementation**

Create `tests/golden/manifest_baseline.json` with this exact canonical payload shape and the actual digest calculated from the compact ASCII JSON encoding of `scenarios` in listed order:

```json
{
  "schema": "forgeagent.golden-manifest.v1",
  "scenarios": [
    {"scenario_id": "G01", "title": "CSV summary", "run_real": true}
  ],
  "fingerprint": "<64 lowercase SHA-256 hex characters>"
}
```

Populate all twenty existing scenarios exactly once in their current `GOLDEN_SCENARIOS` order; do not use a placeholder digest. In `tests/golden/manifest.py`, implement a canonical tuple projection and hash only the three approved fields:

```python
def manifest_fingerprint(scenarios: Sequence[GoldenScenario] = GOLDEN_SCENARIOS) -> str:
    payload = [
        {"scenario_id": item.scenario_id, "title": item.title, "run_real": item.run_real is not None}
        for item in scenarios
    ]
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
```

Load the baseline through a repository-relative `Path(__file__).with_name("manifest_baseline.json")`; require exactly schema string, a list of 20 scalar rows, and a 64-character lowercase hex fingerprint. Recompute the baseline payload fingerprint before comparing it with `manifest_fingerprint(scenarios)`. In `runner.validate_manifest()`, call this validation first and raise only `GoldenPreflightError("golden manifest canonical baseline mismatch")` for malformed baseline or any mismatch. Keep the existing ID/real-ID/catalog checks afterward as defense in depth.

- [ ] **Step 4: Run focused manifest regression tests**

Run: `uv run pytest tests/test_golden_runner.py -k 'baseline or manifest or preflight' -v`

Expected: PASS; the approved tuple validates, each mutation fails preflight, and no case writes a successful report.

- [ ] **Step 5: Run the offline trusted core**

Run: `uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-m20-manifest-golden`

Expected: exit `0` and `20/20` in `report.md`; this proves baseline preflight preserved the current approved core.

- [ ] **Step 6: Commit the coherent manifest guard**

```bash
git add tests/golden/manifest.py tests/golden/manifest_baseline.json tests/golden/runner.py tests/test_golden_runner.py
git commit -m "feat: protect golden manifest baseline"
```

## Task 2: Define safe evaluation records and metric aggregation

**Files:**
- Create: `src/forgeagent/evaluation.py`
- Create: `tests/test_evaluation.py`

**Interfaces:**
- Consumes: golden report mapping with `schema == "forgeagent.golden.v1"`, `total`, `passed`, `results`; `AuditEvent | Mapping[str, object]`; `TaskOutcomeProjection(completed: bool, round_count: int)`.
- Produces: `EVALUATION_SCHEMA = "forgeagent.evaluation.v1"`; frozen `TaskOutcomeProjection`; frozen `EvaluationMetrics`; frozen `EvaluationRecord`; `project_audit_event(event: AuditEvent | Mapping[str, object]) -> dict[str, object] | None`; `aggregate_metrics(golden_report: Mapping[str, object], audit_events: Iterable[AuditEvent | Mapping[str, object]] = (), task_outcomes: Iterable[TaskOutcomeProjection] | None = None) -> EvaluationRecord`.

- [x] **Step 1: Write table-driven failing metric and projection tests**

```python
@pytest.mark.parametrize(
    ("audit_events", "outcomes", "expected"),
    [
        ([valid_outcome(cached=20, prompt=100)], [TaskOutcomeProjection(True, 1)], (100.0, 1.0, 0.0, 0.2)),
        ([], None, (100.0, None, None, None)),
        ([valid_outcome(cached=11, prompt=10)], [TaskOutcomeProjection(True, 2)], (100.0, 0.0, 1.0, None)),
    ],
)
def test_aggregate_metrics_never_fabricates_missing_values(audit_events, outcomes, expected):
    record = aggregate_metrics(valid_golden_report(), audit_events, task_outcomes=outcomes)
    assert record.metrics.model_dump() == dict(zip(METRIC_NAMES, expected, strict=True))


def test_project_audit_event_drops_unknown_and_sensitive_parameters():
    projected = project_audit_event(
        AuditEvent(event_type="llm.outcome", task_id="task-1", attempt=1,
                   result_status="success", duration_ms=7,
                   parameters={"usage": {"cached_tokens": 2, "total_prompt_tokens": 10},
                               "cache_hit_rate": 0.2, "prompt": "secret", "arbitrary": "drop"})
    )
    assert projected == {
        "event_type": "llm.outcome", "task_id": "task-1", "attempt": 1,
        "result_status": "success", "duration_ms": 7,
        "usage": {"cached_tokens": 2, "total_prompt_tokens": 10}, "cache_hit_rate": 0.2,
    }
```

Cover invalid golden schema/total/passed/result types, `passed > total`, NaN/Infinity, malformed audit mapping, duplicate/non-success attempts, zero/negative/over-cached denominators, no completed outcomes, and completed outcome with `round_count < 1`. Assert diagnostics are fixed identifiers/counts, never raw event text.

- [x] **Step 2: Run focused tests to verify failure**

Run: `uv run pytest tests/test_evaluation.py -k 'aggregate or project' -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'forgeagent.evaluation'`.

- [x] **Step 3: Implement the strict, frozen v1 models and pure functions**

Use Pydantic `ConfigDict(frozen=True, extra="forbid")`; require JSON-safe finite values before constructing any record. Give `EvaluationMetrics` exactly `golden_pass_rate`, `first_pass_correctness`, `correction_rounds`, and `cache_hit_rate`, all `float | None`. Give `EvaluationRecord` exactly `schema`, `run_id`, `created_at`, `source_schema`, `metrics`, and bounded `diagnostics` (fixed strings/counters only).

Implement the formulas without consulting prose or arbitrary audit parameters:

```python
golden_pass_rate = passed * 100.0 / total
first_pass_correctness = 100.0 * sum(item.completed and item.round_count == 1 for item in outcomes) / len(outcomes)
correction_rounds = sum(item.round_count - 1 for item in outcomes if item.completed) / completed_count
cache_hit_rate = sum(cached_tokens) / sum(total_prompt_tokens)
```

For each formula, return `None` when its complete required evidence is missing or invalid. `first_pass_correctness` and `correction_rounds` use only supplied `TaskOutcomeProjection` items; an absent projection yields two nulls even when golden results exist. Cache aggregation accepts only projected `llm.outcome` records with `result_status == "success"`; every selected event must have finite integer `0 <= cached_tokens <= total_prompt_tokens` and `total_prompt_tokens > 0`, otherwise cache is null. Do not serialize raw `AuditEvent.parameters`.

- [x] **Step 4: Run the evaluation unit tests**

Run: `uv run pytest tests/test_evaluation.py -k 'aggregate or project' -v`

Expected: PASS, including null behavior and no sensitive/unknown projection fields.

- [x] **Step 5: Commit the evaluation evidence boundary**

```bash
git add src/forgeagent/evaluation.py tests/test_evaluation.py
git commit -m "feat: add safe evaluation metrics"
```

## Task 3: Persist records atomically and compare bounded trends

**Files:**
- Modify: `src/forgeagent/evaluation.py`
- Modify: `tests/test_evaluation.py`

**Interfaces:**
- Consumes: a validated `EvaluationRecord`, caller-supplied absolute record path/directory, and `limit: int`.
- Produces: `write_record(path: Path, record: EvaluationRecord) -> Path`; `read_record(path: Path) -> EvaluationRecord`; `append_trend(record_dir: Path, record: EvaluationRecord, limit: int = 20) -> TrendAppendResult`; `compare_latest(record_dir: Path, record: EvaluationRecord) -> TrendComparison` with nullable per-metric deltas and current/prior run IDs.

- [x] **Step 1: Write failing atomic-storage and trend tests**

```python
def test_append_trend_compares_latest_compatible_record_and_bounds_index(tmp_path):
    old = record(run_id="20260724-old", golden_pass_rate=90.0)
    new = record(run_id="20260724-new", golden_pass_rate=95.0)
    append_trend(tmp_path, old, limit=1)
    appended = append_trend(tmp_path, new, limit=1)
    assert appended.comparison.prior_run_id == "20260724-old"
    assert appended.comparison.deltas["golden_pass_rate"] == 5.0
    assert read_index(tmp_path)["run_ids"] == ["20260724-new"]


def test_corrupt_or_incompatible_history_is_ignored_with_fixed_diagnostic(tmp_path):
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    result = append_trend(tmp_path, record(run_id="current"))
    assert result.diagnostics == ("ignored_invalid_history:1",)
```

Also test: `write_record` leaves no temporary file on replace success/failure; `read_record` rejects unknown schema/extra key/non-finite JSON; non-absolute caller path is rejected; invalid `limit`; duplicate run ID; retention removes only named record files listed by the index; and storage write failure does not mutate a previously valid index.

- [x] **Step 2: Run the storage tests to verify failure**

Run: `uv run pytest tests/test_evaluation.py -k 'record or trend or atomic' -v`

Expected: FAIL because persistence/trend APIs are absent.

- [x] **Step 3: Implement atomic write, strict read, and bounded index**

Use an explicit `record_dir.resolve()` supplied by the caller; reject a relative input before I/O. Write JSON with `ensure_ascii=True`, `allow_nan=False`, and a same-directory `NamedTemporaryFile`, then `os.replace()` exactly as golden runner `_atomic_write()` does. Use an index named `index.json` with schema `forgeagent.evaluation-trend.v1` and only `run_ids: list[str]`; each record lives at `record_dir / f"{run_id}.json"` after rejecting any run ID not matching `^[A-Za-z0-9_-]{1,64}$`.

`append_trend()` must read the previous compatible record before changing files, compare only `schema == EVALUATION_SCHEMA` records, ignore corrupt/incompatible history using count-only diagnostic `ignored_invalid_history:N`, atomically write the current record and new index, then delete evicted record filenames only after the new index exists. `compare_latest()` returns `None` for any delta whose old or new metric is null; it must not subtract incompatible schemas or read paths not named by the index.

- [x] **Step 4: Run all offline evaluation tests and lint**

Run: `uv run pytest tests/test_evaluation.py -v && uv run ruff check src/forgeagent/evaluation.py tests/test_evaluation.py && uv run ruff format --check src/forgeagent/evaluation.py tests/test_evaluation.py`

Expected: all PASS; every persistence assertion uses only temporary directories and no model/network.

- [x] **Step 5: Commit record persistence and trends**

```bash
git add src/forgeagent/evaluation.py tests/test_evaluation.py
git commit -m "feat: persist evaluation trends"
```

## Task 4: Build the isolated evaluator contract

**Files:**
- Create: `src/forgeagent/evaluator.py`
- Create: `tests/test_evaluator.py`

**Interfaces:**
- Consumes: `EvaluationRequest(task_description: str, expected_behavior: str, artifact_root: Path, artifacts: tuple[ArtifactManifestItem, ...])`, a selected `ModelClient`, and existing `Task`.
- Produces: `ArtifactManifestItem(path: str, size_bytes: int)`; `EvaluatorResult(status: Literal["passed", "failed"], observed_evidence: tuple[str, ...], unmet_expectations: tuple[str, ...])`; `validate_artifact_manifest(root: Path, paths: Sequence[str]) -> tuple[ArtifactManifestItem, ...]`; `run_evaluator(client: ModelClient, request: EvaluationRequest) -> EvaluatorResult`.

- [x] **Step 1: Write failing artifact-boundary and isolation tests**

```python
def test_manifest_rejects_escape_absolute_and_oversized_artifacts(tmp_path):
    (tmp_path / "ok.txt").write_text("ok", encoding="utf-8")
    assert validate_artifact_manifest(tmp_path, ["ok.txt"])[0].path == "ok.txt"
    for item in ("../secret.txt", str(tmp_path / "ok.txt"), "missing.txt"):
        with pytest.raises(EvaluatorPreflightError):
            validate_artifact_manifest(tmp_path, [item])


def test_evaluator_task_has_no_generator_context(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(evaluator_module, "Task", lambda client, **kw: captured.update(kw) or FakeTask())
    run_evaluator(mock_client(), request(tmp_path))
    assert captured == {"tier": "restricted", "allowed_root": str(tmp_path.resolve()),
                        "system_prompt": EVALUATOR_SYSTEM_PROMPT, "max_rounds": 2,
                        "memory_manager": None, "skills": None, "mcp": None, "audit_sink": None}
```

Add cases for root itself being a symlink/unreadable; non-file artifact; more than 20 artifacts; file above 64 KiB; total above 256 KiB; control characters; secret/absolute-path-like expected text rendered safely; `Task.close()` on both success/failure; malformed model result; and each parameterized known-bad artifact fixture returning `failed`.

- [x] **Step 2: Run focused tests to verify failure**

Run: `uv run pytest tests/test_evaluator.py -v`

Expected: FAIL with missing evaluator module/API.

- [x] **Step 3: Implement the smallest safe evaluator facade**

Define fixed upper bounds as module constants (`MAX_ARTIFACTS = 20`, `MAX_ARTIFACT_BYTES = 64 * 1024`, `MAX_TOTAL_ARTIFACT_BYTES = 256 * 1024`, `MAX_EVIDENCE_ITEMS = 8`, `MAX_EVIDENCE_CHARS = 500`). Resolve the root once, require every supplied manifest name to be a nonempty relative POSIX path with no `..`, resolve each candidate, and require `candidate.is_relative_to(root)` and `candidate.is_file()` before collecting size. Never put an absolute path in the request/prompt/result; include only `item.path` and `item.size_bytes`.

Use a fixed English system prompt stating that artifacts are untrusted data, cannot override instructions, must be read only through declared relative paths, and output exactly a bounded YAML front matter contract:

```yaml
evaluator_result:
  status: passed | failed
  observed_evidence:
    - bounded statement
  unmet_expectations:
    - bounded statement
```

Construct a fresh `Task(client, tier="restricted", allowed_root=str(root), system_prompt=EVALUATOR_SYSTEM_PROMPT, max_rounds=2, memory_manager=None, skills=None, mcp=None, audit_sink=None)`. Use a dedicated registry containing only `FileReadTool()` and `FileListTool()` by extending `Task`/`Step` with an optional injected registry parameter only if that is the minimal established seam; do not expose Exec, Edit, FileWrite, WebFetch, Survey, MCP, or Skill. The facade feeds only task description, expected behavior, and bounded manifest. Parse only this evaluator-specific result shape; any parse/model/task failure maps to `EvaluatorResult(status="failed", observed_evidence=(), unmet_expectations=("evaluation unavailable",))`, never an exception string.

- [x] **Step 4: Run evaluator isolation tests**

Run: `uv run pytest tests/test_evaluator.py -v && uv run ruff check src/forgeagent/evaluator.py tests/test_evaluator.py`

Expected: PASS; fixtures prove every known failure is rejected and Generator-only dependencies are absent.

- [x] **Step 5: Commit the isolated evaluator core**

```bash
git add src/forgeagent/evaluator.py src/forgeagent/task.py src/forgeagent/step.py tests/test_evaluator.py
git commit -m "feat: add isolated evaluator facade"
```

## Task 5: Add the explicit CLI facade and evaluation report command

**Files:**
- Modify: `src/forgeagent/cli.py:1699-1860`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_evaluation.py`
- Modify: `tests/test_evaluator.py`

**Interfaces:**
- Consumes: `forgeagent evaluate --model MODEL_ID --artifact-root PATH --task-description TEXT --expected-behavior TEXT --artifact RELATIVE_PATH [--artifact ...] [--golden-report PATH] [--audit-jsonl PATH] [--record-dir ABSOLUTE_PATH]`.
- Produces: exit `0` only for evaluator `passed` and successful requested persistence; exit `1` for evaluator `failed`; exit `2` for credential/model/artifact/record preflight or persistence failure; safe console summary with relative artifact paths and nullable metric/delta values.

- [ ] **Step 1: Write failing CLI contract tests**

```python
def test_evaluate_fails_before_artifact_read_when_model_is_unusable(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli_module, "build_real_client", lambda model: (_ for _ in ()).throw(RegistryError("missing key")))
    assert cli_module.main(["evaluate", "--model", "missing", "--artifact-root", str(tmp_path),
                            "--task-description", "x", "--expected-behavior", "y", "--artifact", "x.txt"]) == 2
    assert "evaluation preflight failed" in capsys.readouterr().err


def test_evaluate_constructs_isolated_facade_and_never_runs_on_golden_offline(monkeypatch, tmp_path):
    # Stub run_evaluator and assert its request has only declared contract/relative artifacts.
    assert cli_module.main([...]) == 0
    assert captured_request.artifacts[0].path == "result.txt"
```

Add parser/help tests, a no-network injected-client test, null metric summary test, failed evaluator exit `1`, persistence failure exit `2` after evaluation without claiming pass, and a regression test that `tests.golden.runner.main()` never imports/calls `run_evaluator`.

- [ ] **Step 2: Run focused CLI tests to verify failure**

Run: `uv run pytest tests/test_cli.py -k 'evaluate' -v`

Expected: FAIL because `evaluate` is not a parser command.

- [ ] **Step 3: Implement command parsing, ordered preflight, and safe rendering**

Add only an `evaluate` subparser; do not add evaluator flags to `run`, `serve`, `smoke`, or golden runner. Make `--model`, `--artifact-root`, `--task-description`, `--expected-behavior`, and one-or-more `--artifact` required. Model/client construction occurs before artifact traversal. For an optional golden/audit input, use `aggregate_metrics()` only after strict file JSON/JSONL parsing; missing optional evidence produces null metrics/diagnostics rather than reaching into arbitrary home directories.

Call the evaluator facade with a new client and `artifact_root`; do not call `resolve_cli_identity`, `_make_memory_manager`, `_load_skill_registry`, `build_mcp_manager`, or create `JsonlAuditSink` on this path. If `--record-dir` is present, require an absolute path, assemble the evaluation record from safe projections, then call `append_trend()`. Render status, bounded evidence, unmet expectations, metric values (`n/a` for null), and deltas; never render raw exception/provider messages or absolute root paths.

- [ ] **Step 4: Run CLI and cross-boundary regression tests**

Run: `uv run pytest tests/test_cli.py -k 'evaluate or golden' -v && uv run pytest tests/test_evaluator.py tests/test_evaluation.py -v`

Expected: PASS; ordinary `run`, `serve`, and offline golden tests continue to have no evaluator call path.

- [ ] **Step 5: Commit the opt-in CLI integration**

```bash
git add src/forgeagent/cli.py tests/test_cli.py tests/test_evaluation.py tests/test_evaluator.py
git commit -m "feat: add opt-in evaluation command"
```

## Task 6: Document the capability and update M20 evidence

**Files:**
- Modify: `README.md:1-15,301-325`
- Modify: `docs/threat-model.md:1-60`
- Modify: `docs/text-protocol-spec.md:121-145`
- Modify: `ACTION_PLAN.md:4-5,70`
- Create: `milestones/milestone_020.md`
- Modify: `milestones/latest`

**Interfaces:**
- Consumes: final CLI syntax, `forgeagent.evaluation.v1`, baseline fingerprint behavior, evaluator result contract, and real verification outputs.
- Produces: user-facing Chinese usage/security documentation and, only after all gates pass, M20 milestone evidence linked by `milestones/latest`.

- [ ] **Step 1: Write documentation assertions before prose changes**

```python
def test_readme_documents_evaluate_as_explicit_opt_in():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "forgeagent evaluate" in readme
    assert "不属于基础 CI" in readme
    assert "artifact" in readme
```

Add a text-protocol assertion that standard Task completion still names the existing two-stage semantics and evaluator uses a separate `evaluator_result` contract. Add a threat-model assertion that evaluator artifacts are untrusted and output excludes absolute paths/secrets.

- [ ] **Step 2: Run documentation assertions to verify failure**

Run: `uv run pytest tests/test_evaluator.py -k 'documentation' -v`

Expected: FAIL until the explicit usage/boundary text exists.

- [ ] **Step 3: Write minimal user/security documentation**

In `README.md`, add one M20 section after golden validation showing an explicitly billed, credential-requiring command with a project-relative artifact and an optional absolute record directory:

```bash
uv run forgeagent evaluate --model claude-sonnet-5 --artifact-root ./evaluation-output \
  --task-description "Export summary" --expected-behavior "summary.json contains the total" \
  --artifact summary.json --record-dir /tmp/forgeagent-evaluation
```

State that it is not CI, not invoked by ordinary tasks or offline golden, passes only declared artifacts to a separate session, and stores nullable metrics/trends only when explicitly requested. In the threat model, add a new M20 row explaining prompt-injection treatment, root containment/size limits, no Generator context/Memory/Skills/MCP/audit sink, and residual semantic non-determinism. In the protocol spec, document the dedicated evaluator YAML shape and state it cannot change `TaskStatus` or the Generator's two-stage completed semantics. In `ACTION_PLAN.md`, replace only M20's pending status with factual completed evidence after verification.

Create `milestones/milestone_020.md` from the exact `MILESTONE_GUIDE.md` template only after all following verification is green; include design, implementation, three reviews, unmodified-core evidence, any real-model opt-in status, and remaining evaluator nondeterminism. Then update `milestones/latest` to exactly `milestone_020.md`. Do not claim an opt-in real model call was made if no credentialed run occurred.

- [ ] **Step 4: Run documentation-focused tests**

Run: `uv run pytest tests/test_evaluator.py -k 'documentation' -v`

Expected: PASS with direct, Chinese documentation of the opt-in and security boundaries.

- [ ] **Step 5: Commit M20 documentation and milestone only after evidence exists**

```bash
git add README.md docs/threat-model.md docs/text-protocol-spec.md ACTION_PLAN.md milestones/milestone_020.md milestones/latest tests/test_evaluator.py
git commit -m "docs: record M20 evaluation capability"
```

## Task 7: Execute final regression, validation, and review gates

**Files:**
- Modify only if a failed check identifies a scoped defect; otherwise no files.

**Interfaces:**
- Consumes: all M20 source, test, documentation, manifest baseline, and OpenSpec change artifacts.
- Produces: command outputs for the M20 milestone verification section; no new behavior.

- [ ] **Step 1: Run targeted M20 tests**

Run: `uv run pytest tests/test_evaluation.py tests/test_evaluator.py tests/test_golden_runner.py tests/test_cli.py -v`

Expected: PASS; record all actual pass/skip counts for the milestone, without copying a predicted count.

- [ ] **Step 2: Run the full offline suite and trusted core**

Run: `uv run pytest -q && uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-m20-final-golden`

Expected: pytest exits `0`; golden exits `0` and its report says `20/20`. If either fails, preserve the exact output, apply `systematic-debugging`, and do not proceed to completion/milestone status.

- [ ] **Step 3: Run formatting, lint, packaging, and OpenSpec validation**

Run: `uv run ruff format --check src tests && uv run ruff check src tests && uv build && npx openspec validate eval-evaluator --strict && git diff --check`

Expected: every command exits `0`; `uv build` produces package artifacts but does not introduce a dependency/service. If `npx` cannot run due to unavailable local tooling/network, state that exact limitation and do not falsely mark the OpenSpec gate passed.

- [ ] **Step 4: Perform M20 boundary review before declaring complete**

Verify all of the following by test and diff inspection: offline golden does not import/call evaluator; `run`/REPL/`serve` do not gain evaluator options; `GOLDEN_SCENARIOS` still has twenty original rows; baseline is never written by application code; evaluator receives only relative artifact entries; evaluator `Task` has no Generator context/Memory/Skills/MCP/audit sink and read-only registry; records reject non-finite/unsafe content; persistence failures exit nonzero and do not turn evaluator failure into success.

- [ ] **Step 5: Commit only a scoped final fix when one was required**

If Steps 1-4 required a final source/test correction, stage only the files changed for that correction and commit it using the affected scope, for example:

```bash
git add src/forgeagent/evaluation.py tests/test_evaluation.py
git commit -m "fix: preserve evaluation record boundary"
```

Run `git status --short` afterward. Do not stage or modify pre-existing unrelated files.

## Self-Review

**Spec coverage:** Task 1 covers canonical ordered ID/title/real eligibility baseline and all drift forms. Tasks 2-3 cover v1 aggregation, nullable metrics, safe audit projection, atomic records, bounded trend and compatible deltas. Tasks 4-5 cover explicit opt-in, credential-before-artifact preflight, artifact containment/size bounds, independent Task isolation, known-fail detection, safe results, and no impact to offline golden/normal Task. Task 6 covers README/threat model/protocol/ACTION_PLAN/milestone requirements. Task 7 covers full offline regression, 20/20 golden, ruff, build, OpenSpec strict, diff check, and boundary inspection.

**Placeholder scan:** No implementation task has TBD/TODO/"implement later"/"similar to" placeholders. The baseline digest placeholder shown in Task 1 is explicitly instructional and the task requires replacing it with the calculated 64-character digest before saving; it is not permitted in the produced JSON.

**Type consistency:** `TaskOutcomeProjection` is the only source of first-pass/correction inputs; `EvaluationRecord` uses schema `forgeagent.evaluation.v1`; golden input uses `forgeagent.golden.v1`; `EvaluatorResult.status` is consistently `passed | failed`; CLI persistence uses `append_trend(record_dir, record)`; and the manifest hash names are consistently `manifest_fingerprint`/`load_manifest_baseline`.

Plan complete and saved to `docs/superpowers/plans/2026-07-24-eval-evaluator.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
