---
change: m25-programming-mode-evaluation
design-doc: docs/superpowers/specs/2026-07-27-m25-programming-mode-evaluation-design.md
base-ref: d7fa30526f829959102b5fb69b4778899d6b1f88
---

# M25 编程模式质量-成本评估 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 ForgeAgent 产品运行时和 M23 历史证据的前提下，交付固定、可续跑、可独立复算的双模型 270-run 编程模式评估及中立报告。

**Architecture:** 在现有 `scripts/m23_mode_evaluation.py` 内保留 M23 v2 类型和序列化字节不变，以 schema 分派新增独立 M25 v1 类型、双模型环境绑定、确定性排程、完整 raw 校验和分层聚合；六个新增 Python 小项目仍内嵌于固定协议并复用既有隔离 workspace 与外部检查路径。真实 provider 批次只在所有离线门禁通过、实现已提交且 tracked source clean 后串行执行，随后由不导入 harness 聚合器的独立脚本复算关键分母和 totals。

**Tech Stack:** Python 3.11+、Pydantic v2、pytest、标准库 `json/hashlib/statistics/pathlib/subprocess`、现有 ForgeAgent Task/Collaboration/Audit API、Ruff、uv、OpenSpec 1.4.1、Markdown/JSON。

## Global Constraints

- OpenSpec delta `openspec/changes/m25-programming-mode-evaluation/specs/collaboration-mode-evaluation/spec.md` 是行为合同事实源，Design Doc 是实现细节事实源。
- 不修改 `src/forgeagent/`、`uv.lock`、依赖、模型注册、credential 语义或产品 CLI；不增加 benchmark 框架、数据库、并发、统计显著性或综合评分。
- `EvaluationProtocol`、`TaskSpec`、`RunSpec`、`EnvironmentManifest`、`RawRecord` 的字段、默认值、alias 和 M23 `model_dump()` 输出保持不变。
- `docs/evaluation/m23/protocol.json` 及 `docs/evaluation/m23/runs/**` 的 tracked 文件集合和字节必须与 base-ref `d7fa30526f829959102b5fb69b4778899d6b1f88` 相同。
- M25 schema 固定为 `forgeagent.m25.mode-evaluation/v1`；模型按固定顺序为 `claude-haiku-4-5`、`gpt-5.4-mini`；任务 9 个、模式 3 个、每模型重复 5 次，共 270 个 run。
- 生成设置固定为 `max_output_tokens=4096`、`temperature=0.0`、`thinking=off`、`effort=null`、`timeout_seconds=120.0`；执行设置固定为 restricted、`max_rounds=10`、`max_rejections=2`、identity/memory/skills/MCP 关闭、plan preauthorize、check timeout 30 秒。
- raw/environment/summary 禁止保存 prompt、goal、messages、reply/body/text、credential、API key、base URL 原文或绝对路径；检查 stdout/stderr 只保存 UTF-8 byte count 和 SHA-256。
- Single 的 first acceptance、rejection、correction 始终为 null/N/A；未知 usage 不得补零，missing rate 按 logical call 加权。
- summary/report 禁止自动排名、推荐或优越性结论；禁止 schema 键 `rank`、`ranking`、`winner`、`best_mode`、`superior`。
- 真实 provider 调用不是 CI；真实 270-run 必须排在 Task 8 离线门禁通过和实现提交之后，且保持串行。
- 每个任务只提交列出的文件；保留用户未跟踪文件，不暂存 `.agent/`、`.agents/`、`.claude/`、`.codex/`、`.superpowers/` 或无关本地 M23 尝试目录。
- 所有 shell 命令必须以 `rtk` 为前缀；uv 命令统一使用 `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache ...`，避免访问工作区外缓存。

## File Structure

- Modify: `scripts/m23_mode_evaluation.py` - 保留 M23 行为并新增 M25 schema、排程、执行、续跑、聚合和报告分派。
- Create: `tests/test_m25_mode_evaluation.py` - M23 不可变门、M25 严格合同、fixture、执行、聚合、报告和证据安全测试。
- Create: `scripts/m25_independent_recompute.py` - 仅用标准库从 M25 protocol/environment/raw 独立重算关键分母、token/call/attempt totals 和 usage missingness，并与 summary 比对。
- Create: `tests/test_m25_independent_recompute.py` - 证明独立复算不导入 harness 聚合器并能检测分母或 totals 篡改。
- Create: `docs/evaluation/m25/protocol.json` - 固定九任务、双模型、五重复协议；前三任务复制 M23 合同并只增加 `family=baseline`。
- Create: `docs/evaluation/m25/README.md` - M25 命令、证据边界、限制和复算入口。
- Create during real batch: `docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/environment.json`, `raw/*.json`, `summary.json`, `report.md` - 真实完整证据。
- Modify: `README.md`, `ACTION_PLAN.md`, `openspec/changes/m25-programming-mode-evaluation/tasks.md` - 发布入口、里程碑状态和完成勾选。
- Create: `milestones/milestone_025.md`; Modify: `milestones/latest` - M25 交付、证据、限制、验证与续接指引。

## Fixed Interfaces

以下名称和签名是任务间合同；实现者不得在相邻任务中改名：

```text
TaskFamily = Literal["baseline", "bugfix", "feature", "refactor"]
Protocol = EvaluationProtocol | M25EvaluationProtocol
RunSpecification = RunSpec | M25RunSpec
Environment = EnvironmentManifest | M25EnvironmentManifest
RunRecord = RawRecord | M25RawRecord

validate_protocol(value: object) -> Protocol
load_protocol(path: Path) -> tuple[Protocol, str]
protocol_model_ids(protocol: Protocol) -> tuple[str, ...]
run_model_id(protocol: Protocol, run_spec: RunSpecification) -> str
run_task_family(run_spec: RunSpecification) -> TaskFamily | None
protocol_namespace(protocol: Protocol) -> Literal["m23", "m25"]
route_hash_for_model(environment: Environment, model_id: str) -> str
build_schedule(protocol: Protocol) -> tuple[RunSpecification, ...]
run_spec_hash(run_spec: RunSpecification, protocol_sha256: str) -> str
run_id_for(protocol: Protocol, run_spec: RunSpecification) -> str
environment_manifest(
    protocol: Protocol,
    protocol_sha256: str,
    *,
    repo_root: Path,
    provider_route_sha256: str | None = None,
    model_routes: Mapping[str, tuple[str, str]] | None = None,
) -> Environment
environment_sha256(manifest: Environment) -> str
build_raw_record(
    *,
    run_spec: RunSpecification,
    mode_result: ModeResult,
    checks: tuple[CheckRecord, ...],
    artifacts: tuple[ArtifactResult, ...],
    audit_metrics: AuditMetrics,
    protocol_sha256: str,
    environment_sha256: str,
    started_at: str,
    finished_at: str,
    end_to_end_latency_seconds: float,
    provider_route_sha256: str | None = None,
    error_category: str | None = None,
) -> RunRecord
read_raw_records(
    raw_dir: Path,
    protocol: Protocol,
    protocol_sha256: str,
    environment_sha256_value: str,
    *,
    environment: Environment | None = None,
) -> tuple[RunRecord, ...]
aggregate_records(
    protocol: Protocol,
    schedule: Sequence[RunSpecification],
    records: Sequence[RunRecord],
) -> dict[str, object]
```

M23 调用 `environment_manifest()` 保留现有 `provider_route_sha256=` keyword；新 M25 调用只传 `model_routes=`，函数拒绝两者同时存在或同时缺失。`pending_run_specs()` 保留前四个现有 positional 参数，并增加 keyword-only `environment: Environment | None = None`，因此现有 M23 测试和调用不需要伪造 M25 route 数据。

---

### Task 1: M23 不可变门与 M25 严格 schema 分派

**Files:**
- Create: `tests/test_m25_mode_evaluation.py`
- Modify: `scripts/m23_mode_evaluation.py:37-361`
- Test: `tests/test_m23_mode_evaluation.py`
- Test: `tests/test_m25_mode_evaluation.py`

**Interfaces:**
- Consumes: 现有 M23 `StrictModel`, `TaskSpec`, `EvaluationProtocol`, `RunSpec`, `EnvironmentManifest`, `RawRecord`, `canonical_sha256()`。
- Produces: `M25TaskSpec`, `M25EvaluationProtocol`, `M25RunSpec`, `M25ModelRoute`, `M25EnvironmentManifest`, `M25RawRecord` 和 Fixed Interfaces 中五个 protocol/run/environment helper。

- [x] **Step 1: Write the failing schema and immutability tests**

Create the test module header and M23 byte lock:

```python
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "scripts/m23_mode_evaluation.py"
M23_PROTOCOL_PATH = ROOT / "docs/evaluation/m23/protocol.json"
M23_FORMAL_ROOT = ROOT / "docs/evaluation/m23/runs/2026-07-27-haiku-4-5"
M25_PROTOCOL_PATH = ROOT / "docs/evaluation/m25/protocol.json"
BASE_REF = "d7fa30526f829959102b5fb69b4778899d6b1f88"
M25_SCHEMA = "forgeagent.m25.mode-evaluation/v1"


def load_harness():
    spec = importlib.util.spec_from_file_location("m25_mode_evaluation", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(*arguments: str) -> bytes:
    return subprocess.run(
        ("git", *arguments), cwd=ROOT, check=True, capture_output=True
    ).stdout


def test_tracked_m23_protocol_and_evidence_are_byte_identical_to_base_ref() -> None:
    expected = _git("ls-tree", "-r", "--name-only", BASE_REF, "docs/evaluation/m23")
    current = _git("ls-tree", "-r", "--name-only", "HEAD", "docs/evaluation/m23")
    assert current == expected
    for relative_path in expected.decode().splitlines():
        assert (ROOT / relative_path).read_bytes() == _git("show", f"{BASE_REF}:{relative_path}")


def test_formal_m23_raw_recomputes_to_checked_in_summary_and_report() -> None:
    harness = load_harness()
    protocol, protocol_sha256 = harness.load_protocol(M23_PROTOCOL_PATH)
    environment = harness.EnvironmentManifest.model_validate_json(
        (M23_FORMAL_ROOT / "environment.json").read_bytes()
    )
    records = harness.read_raw_records(
        M23_FORMAL_ROOT / "raw",
        protocol,
        protocol_sha256,
        harness.environment_sha256(environment),
    )
    recomputed = harness.aggregate_records(protocol, harness.build_schedule(protocol), records)
    checked_in = json.loads((M23_FORMAL_ROOT / "summary.json").read_text(encoding="utf-8"))
    recomputed.pop("generated_at")
    checked_in.pop("generated_at")
    assert recomputed == checked_in
    report = harness.render_report(
        protocol,
        environment.model_dump(mode="json", by_alias=True),
        recomputed,
    )
    assert report == (M23_FORMAL_ROOT / "report.md").read_text(encoding="utf-8")
```

Add a valid in-memory M25 contract builder and strict dispatch assertions:

```python
def m25_protocol_dict() -> dict[str, object]:
    value = json.loads(M23_PROTOCOL_PATH.read_text(encoding="utf-8"))
    source_tasks = value["tasks"]
    tasks = []
    families = ("baseline", "baseline", "baseline", "bugfix", "bugfix", "feature", "feature", "refactor", "refactor")
    for index, family in enumerate(families):
        task = copy.deepcopy(source_tasks[index % 3])
        task["id"] = task["id"] if index < 3 else f"contract-{family}-{index}"
        task["family"] = family
        tasks.append(task)
    value["schema"] = M25_SCHEMA
    value.pop("model_id")
    value["model_ids"] = ["claude-haiku-4-5", "gpt-5.4-mini"]
    value["repetitions"] = 5
    value["tasks"] = tasks
    return value


def test_validate_protocol_dispatches_m23_and_m25_without_changing_m23_dump() -> None:
    harness = load_harness()
    m23_source = json.loads(M23_PROTOCOL_PATH.read_text(encoding="utf-8"))
    m23 = harness.validate_protocol(m23_source)
    m25 = harness.validate_protocol(m25_protocol_dict())
    assert type(m23) is harness.EvaluationProtocol
    assert type(m25) is harness.M25EvaluationProtocol
    assert m23.model_dump(mode="json", by_alias=True) == m23_source
    assert m25.model_ids == ("claude-haiku-4-5", "gpt-5.4-mini")


@pytest.mark.parametrize("schema", [None, "forgeagent.m23.mode-evaluation/v1", "unknown/v1"])
def test_unknown_schema_fails_before_model_parsing(schema: str | None) -> None:
    harness = load_harness()
    value = m25_protocol_dict()
    if schema is None:
        value.pop("schema")
    else:
        value["schema"] = schema
    with pytest.raises(ValueError, match="schema"):
        harness.validate_protocol(value)
```

- [x] **Step 2: Run RED tests**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py::test_validate_protocol_dispatches_m23_and_m25_without_changing_m23_dump tests/test_m25_mode_evaluation.py::test_unknown_schema_fails_before_model_parsing`

Expected: FAIL because `M25EvaluationProtocol` and schema dispatch do not exist.

- [x] **Step 3: Add independent M25 types without changing M23 models**

Keep `PROTOCOL_SCHEMA` and every existing M23 class body unchanged. Add these strict M25 types after their M23 counterparts:

```python
M25_PROTOCOL_SCHEMA = "forgeagent.m25.mode-evaluation/v1"
TaskFamily = Literal["baseline", "bugfix", "feature", "refactor"]


class M25TaskSpec(TaskSpec):
    family: TaskFamily


class M25EvaluationProtocol(StrictModel):
    schema_: Literal[M25_PROTOCOL_SCHEMA] = Field(alias="schema")
    model_ids: tuple[
        Literal["claude-haiku-4-5"], Literal["gpt-5.4-mini"]
    ]
    generation: GenerationSettings
    execution: ExecutionSettings
    modes: tuple[Mode, ...]
    repetitions: Literal[5]
    mode_orders: tuple[tuple[Mode, ...], ...]
    tasks: tuple[M25TaskSpec, ...] = Field(min_length=9, max_length=9)

    @model_validator(mode="after")
    def validate_frozen_design(self) -> M25EvaluationProtocol:
        expected_orders = (
            ("single", "duo", "triad"),
            ("duo", "triad", "single"),
            ("triad", "single", "duo"),
        )
        if self.modes != MODES or self.mode_orders != expected_orders:
            raise ValueError("M25 modes and mode_orders must use the fixed Latin rotation")
        task_ids = [task.id for task in self.tasks]
        if len(set(task_ids)) != 9:
            raise ValueError("M25 task ids must be unique")
        expected_families = {"baseline": 3, "bugfix": 2, "feature": 2, "refactor": 2}
        observed = {family: sum(task.family == family for task in self.tasks) for family in expected_families}
        if observed != expected_families:
            raise ValueError("M25 task families must be 3/2/2/2")
        slugs = [_model_slug(model_id) for model_id in self.model_ids]
        if len(set(slugs)) != len(slugs):
            raise ValueError("M25 model slugs must be unique")
        return self


@dataclass(frozen=True)
class M25RunSpec:
    sequence: int
    task_id: str
    task_family: TaskFamily
    model_id: str
    repeat: int
    mode: Mode


class M25ModelRoute(StrictModel):
    model_id: str
    client_kind: str
    provider_route_sha256: str = Field(pattern=SHA256_PATTERN)


class M25EnvironmentManifest(StrictModel):
    schema_: Literal["forgeagent.m25.mode-evaluation.environment/v1"] = Field(
        "forgeagent.m25.mode-evaluation.environment/v1", alias="schema"
    )
    generated_at: str
    git_commit: str
    tracked_dirty: Literal[False]
    python_version: str
    python_executable_name: str
    platform: str
    package_version: str
    model_routes: tuple[M25ModelRoute, M25ModelRoute]
    builtin_models_sha256: str = Field(pattern=SHA256_PATTERN)
    builtin_config_sha256: str = Field(pattern=SHA256_PATTERN)
    protocol_sha256: str = Field(pattern=SHA256_PATTERN)
    generation: GenerationSettings
    execution: ExecutionSettings


class M25RawRecord(RawRecord):
    schema_: Literal["forgeagent.m25.mode-evaluation.run/v1"] = Field(
        "forgeagent.m25.mode-evaluation.run/v1", alias="schema"
    )
    terminal: Literal[True] = True
    task_family: TaskFamily
    model_id: str
    provider_route_sha256: str = Field(pattern=SHA256_PATTERN)


Protocol = EvaluationProtocol | M25EvaluationProtocol
RunSpecification = RunSpec | M25RunSpec
Environment = EnvironmentManifest | M25EnvironmentManifest
RunRecord = RawRecord | M25RawRecord
```

Use `_model_slug()` only for file-safe identity, not provider lookup:

```python
def _model_slug(model_id: str) -> str:
    slug = "-".join(part for part in re.sub(r"[^a-z0-9]+", "-", model_id.lower()).split("-") if part)
    if not slug:
        raise ValueError("model id has no safe slug")
    return slug
```

Add `import re`; do not add a package dependency.

- [x] **Step 4: Implement schema-first dispatch and fixed helpers**

```python
def validate_protocol(value: object) -> Protocol:
    if not isinstance(value, dict) or not isinstance(value.get("schema"), str):
        raise ValueError("protocol schema is required")
    schema = value["schema"]
    if schema == PROTOCOL_SCHEMA:
        return EvaluationProtocol.model_validate(value)
    if schema == M25_PROTOCOL_SCHEMA:
        return M25EvaluationProtocol.model_validate(value)
    raise ValueError(f"unsupported protocol schema: {schema}")


def protocol_model_ids(protocol: Protocol) -> tuple[str, ...]:
    return (protocol.model_id,) if isinstance(protocol, EvaluationProtocol) else protocol.model_ids


def run_model_id(protocol: Protocol, run_spec: RunSpecification) -> str:
    return protocol.model_id if isinstance(run_spec, RunSpec) else run_spec.model_id


def run_task_family(run_spec: RunSpecification) -> TaskFamily | None:
    return None if isinstance(run_spec, RunSpec) else run_spec.task_family


def protocol_namespace(protocol: Protocol) -> Literal["m23", "m25"]:
    return "m23" if isinstance(protocol, EvaluationProtocol) else "m25"


def route_hash_for_model(environment: Environment, model_id: str) -> str:
    if isinstance(environment, EnvironmentManifest):
        if model_id != environment.model_id:
            raise ValueError("model route is not present in environment")
        return environment.provider_route_sha256
    matches = [route.provider_route_sha256 for route in environment.model_routes if route.model_id == model_id]
    if len(matches) != 1:
        raise ValueError("model route is not uniquely present in environment")
    return matches[0]
```

`load_protocol()` keeps hashing the complete aliased model dump. Add tests that M25 rejects an extra field, reversed/duplicate model IDs, duplicate task IDs, wrong family counts, wrong repetitions, wrong Latin orders, and slug collisions (monkeypatch `_model_slug` to a constant for that test).

- [x] **Step 5: Run GREEN and M23 regression tests**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py tests/test_m23_mode_evaluation.py`

Expected: PASS; existing M23 tests remain green, and the base-ref byte lock passes.

- [x] **Step 6: Commit**

```bash
rtk git add scripts/m23_mode_evaluation.py tests/test_m25_mode_evaluation.py
rtk git commit -m "feat(evaluation): add strict M25 protocol schema"
```

### Task 2: 270-run 排程、identity、hash 与安全续跑

**Files:**
- Modify: `tests/test_m25_mode_evaluation.py`
- Modify: `scripts/m23_mode_evaluation.py:345-374,569-615,1208-1253`
- Test: `tests/test_m25_mode_evaluation.py`
- Test: `tests/test_m23_mode_evaluation.py`

**Interfaces:**
- Consumes: `M25EvaluationProtocol`, `M25RunSpec`, `_model_slug()`, `protocol_namespace()`, `route_hash_for_model()`。
- Produces: union-aware `build_schedule()`, `run_spec_hash()`, `run_id_for()` and keyword-only `pending_run_specs(..., environment=None)`。

- [x] **Step 1: Write the failing deterministic schedule tests**

```python
from collections import Counter


def test_m25_schedule_has_fixed_270_run_order_and_global_position_balance() -> None:
    harness = load_harness()
    protocol = harness.validate_protocol(m25_protocol_dict())
    schedule = harness.build_schedule(protocol)
    assert len(schedule) == 270
    assert len({(s.task_id, s.model_id, s.repeat, s.mode) for s in schedule}) == 270
    assert Counter(s.model_id for s in schedule) == {
        "claude-haiku-4-5": 135,
        "gpt-5.4-mini": 135,
    }
    assert Counter(s.mode for s in schedule) == {"single": 90, "duo": 90, "triad": 90}
    assert all(
        sum(s.task_id == task.id and s.model_id == model and s.mode == mode for s in schedule) == 5
        for task in protocol.tasks
        for model in protocol.model_ids
        for mode in protocol.modes
    )
    positions = Counter((s.mode, (s.sequence - 1) % 3) for s in schedule)
    assert positions == Counter({(mode, position): 30 for mode in protocol.modes for position in range(3)})
    assert [(s.sequence, s.model_id, s.repeat, s.mode) for s in schedule[:6]] == [
        (1, "claude-haiku-4-5", 1, "single"),
        (2, "claude-haiku-4-5", 1, "duo"),
        (3, "claude-haiku-4-5", 1, "triad"),
        (4, "gpt-5.4-mini", 1, "duo"),
        (5, "gpt-5.4-mini", 1, "triad"),
        (6, "gpt-5.4-mini", 1, "single"),
    ]
    assert [(s.sequence, s.model_id, s.repeat, s.mode) for s in schedule[-6:]] == [
        (265, "claude-haiku-4-5", 5, "triad"),
        (266, "claude-haiku-4-5", 5, "single"),
        (267, "claude-haiku-4-5", 5, "duo"),
        (268, "gpt-5.4-mini", 5, "single"),
        (269, "gpt-5.4-mini", 5, "duo"),
        (270, "gpt-5.4-mini", 5, "triad"),
    ]
```

Add identity assertions:

```python
def test_m25_run_identity_binds_model_family_sequence_and_protocol() -> None:
    harness = load_harness()
    protocol = harness.validate_protocol(m25_protocol_dict())
    first = harness.build_schedule(protocol)[0]
    digest = "a" * 64
    assert harness.run_id_for(protocol, first) == (
        "001-csv-region-summary-claude-haiku-4-5-r1-single"
    )
    changed = dataclasses.replace(first, model_id="gpt-5.4-mini")
    assert harness.run_spec_hash(first, digest) != harness.run_spec_hash(changed, digest)
```

- [x] **Step 2: Run RED schedule tests**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py::test_m25_schedule_has_fixed_270_run_order_and_global_position_balance tests/test_m25_mode_evaluation.py::test_m25_run_identity_binds_model_family_sequence_and_protocol`

Expected: FAIL because the current schedule is M23-only and `run_id_for()` is absent.

- [x] **Step 3: Implement the exact schedule formula and identity branches**

```python
def build_schedule(protocol: Protocol) -> tuple[RunSpecification, ...]:
    if isinstance(protocol, EvaluationProtocol):
        schedule: list[RunSpecification] = []
        for task in protocol.tasks:
            for repetition, order in enumerate(protocol.mode_orders, start=1):
                for mode in order:
                    schedule.append(RunSpec(len(schedule) + 1, task.id, repetition, mode))
        return tuple(schedule)

    schedule = []
    for task_index, task in enumerate(protocol.tasks):
        for repeat_index in range(protocol.repetitions):
            stable_models = list(enumerate(protocol.model_ids))
            if (task_index + repeat_index) % 2:
                stable_models.reverse()
            for model_index, model_id in stable_models:
                order = protocol.mode_orders[(2 * task_index + model_index + repeat_index) % 3]
                for mode in order:
                    schedule.append(
                        M25RunSpec(
                            sequence=len(schedule) + 1,
                            task_id=task.id,
                            task_family=task.family,
                            model_id=model_id,
                            repeat=repeat_index + 1,
                            mode=mode,
                        )
                    )
    return tuple(schedule)


def run_id_for(protocol: Protocol, run_spec: RunSpecification) -> str:
    if isinstance(run_spec, RunSpec):
        return f"{run_spec.sequence:02d}-{run_spec.task_id}-r{run_spec.repeat}-{run_spec.mode}"
    return (
        f"{run_spec.sequence:03d}-{run_spec.task_id}-{_model_slug(run_spec.model_id)}-"
        f"r{run_spec.repeat}-{run_spec.mode}"
    )
```

In `run_spec_hash()`, preserve the existing M23 dict exactly; the M25 branch hashes all six M25 fields plus `protocol_sha256`.

- [x] **Step 4: Write RED resume conflict tests**

Construct one `M25RawRecord` bound to an `M25EnvironmentManifest`. Assert an exact terminal record is skipped, then independently mutate `task_family`, `model_id`, `provider_route_sha256`, `run_id`, `run_spec_sha256`, and filename; every mutation must raise before any model call. Assert an extra JSON filename and an M23 raw schema in the M25 raw directory are rejected.

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py -k 'resume or identity'`

Expected: FAIL until `pending_run_specs()` parses the protocol-specific raw model and binds route/family/filename.

- [x] **Step 5: Implement protocol-specific pending validation**

Build expected filenames with `run_id_for(protocol, spec) + ".json"`. For M25, require `environment` to be `M25EnvironmentManifest`, parse only `M25RawRecord`, and compare terminal, schema, run ID, sequence, task, family, model, repeat, mode, protocol/environment/RunSpec hashes, and `route_hash_for_model(environment, spec.model_id)`. Keep the existing M23 branch byte-for-byte equivalent.

- [x] **Step 6: Run GREEN and commit**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py -k 'schedule or resume or identity' tests/test_m23_mode_evaluation.py`

Expected: PASS.

```bash
rtk git add scripts/m23_mode_evaluation.py tests/test_m25_mode_evaluation.py
rtk git commit -m "feat(evaluation): schedule fixed M25 run matrix"
```

### Task 3: 固定九任务协议与六个编程 fixture

**Files:**
- Create: `docs/evaluation/m25/protocol.json`
- Modify: `tests/test_m25_mode_evaluation.py`
- Test: `tests/test_m25_mode_evaluation.py`

**Interfaces:**
- Consumes: `M25TaskSpec`, `prepare_workspace()`, `run_checks()`, `hash_artifacts()` and M23 protocol task objects。
- Produces: checked-in `forgeagent.m25.mode-evaluation/v1` protocol with exact task IDs/families/files/checks。

- [x] **Step 1: Write the failing checked-in protocol contract**

```python
def test_checked_in_m25_protocol_fixes_models_tasks_families_and_baselines() -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(M25_PROTOCOL_PATH)
    m23 = json.loads(M23_PROTOCOL_PATH.read_text(encoding="utf-8"))
    assert protocol.schema_ == M25_SCHEMA
    assert protocol.model_ids == ("claude-haiku-4-5", "gpt-5.4-mini")
    assert protocol.repetitions == 5
    assert len(protocol.tasks) == 9
    assert digest == harness.canonical_sha256(protocol.model_dump(mode="json", by_alias=True))
    for index in range(3):
        actual = protocol.tasks[index].model_dump(mode="json")
        assert actual.pop("family") == "baseline"
        assert actual == m23["tasks"][index]
    assert [(task.id, task.family) for task in protocol.tasks[3:]] == [
        ("fix-ttl-expiration-boundary", "bugfix"),
        ("fix-invoice-discount-composition", "bugfix"),
        ("add-topological-batches", "feature"),
        ("add-jsonl-dead-letter-output", "feature"),
        ("refactor-notification-routing", "refactor"),
        ("refactor-config-precedence", "refactor"),
    ]
```

- [x] **Step 2: Run RED checked-in protocol test**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py::test_checked_in_m25_protocol_fixes_models_tasks_families_and_baselines`

Expected: FAIL because `docs/evaluation/m25/protocol.json` does not exist.

- [x] **Step 3: Create the protocol header and exact baseline tasks**

Create `docs/evaluation/m25/protocol.json` with this fixed header:

```json
{
  "schema": "forgeagent.m25.mode-evaluation/v1",
  "model_ids": ["claude-haiku-4-5", "gpt-5.4-mini"],
  "generation": {"max_output_tokens": 4096, "temperature": 0.0, "thinking": "off", "effort": null, "timeout_seconds": 120},
  "execution": {"tier": "restricted", "max_rounds": 10, "max_rejections": 2, "identity": false, "memory": false, "skills": false, "mcp": false, "plan_policy": "preauthorize", "check_timeout_seconds": 30},
  "modes": ["single", "duo", "triad"],
  "repetitions": 5,
  "mode_orders": [["single", "duo", "triad"], ["duo", "triad", "single"], ["triad", "single", "duo"]],
  "tasks": []
}
```

Copy the three complete task objects from `docs/evaluation/m23/protocol.json` into `tasks` without changing key order, goal, file content, paths, commands, or timeouts; add only `"family": "baseline"` immediately after each `id`.

- [x] **Step 4: Add the two exact bugfix fixtures**

`fix-ttl-expiration-boundary` uses candidate `cache.py`, immutable `test_cache.py`, artifact `cache.py`, and check `[{python}, -m, pytest, -q, test_cache.py]`. Encode these exact source files as JSON strings:

```python
# cache.py (initial defect is <= at the expiration boundary)
class TtlCache:
    def __init__(self, clock):
        self._clock = clock
        self._entries = {}

    def set(self, key, value, ttl_seconds):
        self._entries[key] = (value, self._clock() + ttl_seconds)

    def get(self, key):
        entry = self._entries.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if self._clock() <= expires_at:
            return value
        del self._entries[key]
        return None
```

```python
# test_cache.py
from cache import TtlCache


def test_hit_before_expiration_and_miss_at_boundary():
    now = [10.0]
    cache = TtlCache(lambda: now[0])
    cache.set("session", "value", 5.0)
    now[0] = 14.999
    assert cache.get("session") == "value"
    now[0] = 15.0
    assert cache.get("session") is None
    assert "session" not in cache._entries


def test_missing_and_expired_entries_are_misses():
    now = [2.0]
    cache = TtlCache(lambda: now[0])
    assert cache.get("missing") is None
    cache.set("key", 3, 1.0)
    now[0] = 4.0
    assert cache.get("key") is None
```

Its goal states: only `cache.py` may change; expiry is exclusive (`now < expires_at`); boundary/after-boundary calls evict and miss; public `TtlCache(clock).set/get` remains unchanged.

`fix-invoice-discount-composition` uses candidates `invoice.py`, `discounts.py`, immutable `test_invoice.py`, both candidates as artifacts, and pytest check. Encode:

```python
# invoice.py (initial defect rounds subtotal before composition)
from decimal import Decimal, ROUND_HALF_UP
from discounts import apply_discounts


def invoice_total(lines, adjustments):
    subtotal = sum(Decimal(str(price)) * quantity for price, quantity in lines)
    rounded = subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return apply_discounts(rounded, adjustments)
```

```python
# discounts.py (initial defects reorder adjustments and reuse subtotal)
from decimal import Decimal, ROUND_HALF_UP


def apply_discounts(subtotal, adjustments):
    total = Decimal(subtotal)
    for kind, value in sorted(adjustments):
        amount = Decimal(str(value))
        if kind == "percent":
            total -= Decimal(subtotal) * amount
        elif kind == "fixed":
            total -= amount
    return max(total, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

```python
# test_invoice.py
from decimal import Decimal
from invoice import invoice_total


def test_adjustments_apply_in_declared_order_to_running_total():
    lines = [("19.995", 2)]
    assert invoice_total(lines, [("fixed", "5"), ("percent", "0.10")]) == Decimal("31.49")
    assert invoice_total(lines, [("percent", "0.10"), ("fixed", "5")]) == Decimal("30.99")


def test_total_is_capped_at_zero_and_rounded_only_after_composition():
    assert invoice_total([("1", 1)], [("fixed", "5")]) == Decimal("0.00")
    assert invoice_total([("0.335", 3)], [("percent", "0.10")]) == Decimal("0.90")
```

Its goal states: only `invoice.py` and `discounts.py` may change; preserve `invoice_total(lines, adjustments)`; process `fixed`/`percent` in supplied order against running total; cap at zero; `ROUND_HALF_UP` only once at the end.

- [x] **Step 5: Add the two exact feature fixtures**

`add-topological-batches` is a package with candidates `dependency_graph/graph.py`, `dependency_graph/__init__.py`, immutable `test_dependency_graph.py`, both candidates as artifacts, and pytest check:

```python
# dependency_graph/graph.py (initially lacks CycleError and topological_batches)
class DependencyGraph:
    def __init__(self):
        self._dependencies = {}

    def add_node(self, node):
        self._dependencies.setdefault(node, set())

    def add_dependency(self, node, dependency):
        self.add_node(node)
        self.add_node(dependency)
        self._dependencies[node].add(dependency)
```

```python
# dependency_graph/__init__.py
from .graph import DependencyGraph

__all__ = ["DependencyGraph"]
```

```python
# test_dependency_graph.py
import pytest
from dependency_graph import CycleError, DependencyGraph


def test_batches_are_stable_and_include_isolated_nodes():
    graph = DependencyGraph()
    graph.add_dependency("deploy", "test")
    graph.add_dependency("test", "build")
    graph.add_node("docs")
    assert graph.topological_batches() == [("build", "docs"), ("test",), ("deploy",)]


def test_cycle_raises_public_cycle_error():
    graph = DependencyGraph()
    graph.add_dependency("a", "b")
    graph.add_dependency("b", "a")
    with pytest.raises(CycleError, match="cycle"):
        graph.topological_batches()
```

The goal requires `DependencyGraph.topological_batches() -> list[tuple[str, ...]]`, lexicographically sorted nodes within each ready batch, isolated nodes, `CycleError(ValueError)`, and exports from `dependency_graph` while preserving `add_node/add_dependency`.

`add-jsonl-dead-letter-output` uses candidates `event_processor.py`, `cli.py`, immutable `test_cli.py` and `events.jsonl`, and artifacts `event_processor.py`, `cli.py`, `output.jsonl`, `dead-letter.jsonl`. Fix `events.jsonl` to these bytes:

```text
{"id": 1, "kind": "OPEN"}
not-json
{"id": 2}
```

Declare both a pytest check and this mode-independent artifact check, which invokes the CLI inside the workspace and leaves the two fixed artifacts for hashing:

```json
{
  "id": "jsonl-artifacts",
  "command": [
    "{python}",
    "-c",
    "import json; from pathlib import Path; import cli; code = cli.main(['events.jsonl', 'output.jsonl', '--dead-letter', 'dead-letter.jsonl']); rows = [json.loads(line) for line in Path('output.jsonl').read_text(encoding='utf-8').splitlines()]; dead = [json.loads(line) for line in Path('dead-letter.jsonl').read_text(encoding='utf-8').splitlines()]; assert code == 1; assert rows == [{'id': '1', 'kind': 'open'}]; assert dead == [{'error': 'JSONDecodeError', 'line': 2}, {'error': 'KeyError', 'line': 3}]"
  ],
  "timeout_seconds": 30
}
```

Encode these source files as JSON strings:

```python
# event_processor.py
def normalize_event(event):
    return {"id": str(event["id"]), "kind": str(event["kind"]).lower()}
```

```python
# cli.py (initially drops invalid lines and has no dead-letter output)
import argparse
import json
from pathlib import Path

from event_processor import normalize_event


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    args = parser.parse_args(argv)
    rows = []
    for line in Path(args.input).read_text(encoding="utf-8").splitlines():
        try:
            rows.append(normalize_event(json.loads(line)))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    Path(args.output).write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```python
# test_cli.py
import json
from pathlib import Path

import cli


def _rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def test_bad_lines_are_collected_and_return_nonzero(tmp_path):
    source = tmp_path / "events.jsonl"
    output = tmp_path / "output.jsonl"
    dead = tmp_path / "dead.jsonl"
    source.write_text('{"id": 1, "kind": "OPEN"}\nnot-json\n{"id": 2}\n', encoding="utf-8")
    assert cli.main([str(source), str(output), "--dead-letter", str(dead)]) == 1
    assert _rows(output) == [{"id": "1", "kind": "open"}]
    assert _rows(dead) == [
        {"error": "JSONDecodeError", "line": 2},
        {"error": "KeyError", "line": 3},
    ]


def test_all_valid_lines_return_zero_and_empty_dead_letter(tmp_path):
    source = tmp_path / "events.jsonl"
    output = tmp_path / "output.jsonl"
    dead = tmp_path / "dead.jsonl"
    source.write_text('{"id": "a", "kind": "CLOSE"}\n', encoding="utf-8")
    assert cli.main([str(source), str(output), "--dead-letter", str(dead)]) == 0
    assert _rows(output) == [{"id": "a", "kind": "close"}]
    assert dead.read_text(encoding="utf-8") == ""
```

The goal requires `event_processor.process_jsonl(lines) -> tuple[list[dict[str, str]], list[dict[str, object]]]`, one dead-letter object per bad non-empty line with 1-based `line` and exception class `error`, deterministic JSONL, exit 1 when any rejection exists, and exit 0 otherwise.

- [x] **Step 6: Add the two exact refactor fixtures**

`refactor-notification-routing` uses initial candidate `notifications.py`, new required candidate `routing.py`, immutable `test_notifications.py`, both candidates as artifacts, a pytest behavior check, and a structure check using `{python} -c` that imports `routing.route_notification` and asserts `from routing import route_notification` occurs in `notifications.py`:

```python
# notifications.py
def send_notification(user, event):
    preferred = user.get("preferred_channel", "email")
    if event.get("urgent") and user.get("phone"):
        channel, address = "sms", user["phone"]
    elif preferred == "push" and user.get("device"):
        channel, address = "push", user["device"]
    else:
        channel, address = "email", user["email"]
    return {"channel": channel, "address": address, "message": event["message"]}
```

```python
# test_notifications.py
from notifications import send_notification


def test_routing_behavior_is_preserved():
    user = {"email": "a@example.test", "phone": "123", "device": "dev", "preferred_channel": "push"}
    assert send_notification(user, {"message": "normal"}) == {"channel": "push", "address": "dev", "message": "normal"}
    assert send_notification(user, {"message": "urgent", "urgent": True}) == {"channel": "sms", "address": "123", "message": "urgent"}
    assert send_notification({"email": "b@example.test"}, {"message": "fallback"}) == {"channel": "email", "address": "b@example.test", "message": "fallback"}
```

The goal requires moving only route selection into `routing.route_notification(user, event) -> tuple[str, str]`; `notifications.send_notification(user, event)` and all returned dicts remain unchanged.

`refactor-config-precedence` uses initial candidate `config.py`, new candidates `config_sources.py` and `config_merge.py`, immutable `test_config.py`, all three candidates as artifacts, pytest behavior check, and a structure check that imports both new modules and asserts `config.py` imports `environment_values`, `explicit_values`, and `merge_layers`:

```python
# config.py
def load_config(defaults, file_values, environment, command_line):
    result = dict(defaults)
    result.update({key: value for key, value in file_values.items() if value is not None})
    result.update({key[4:].lower(): value for key, value in environment.items() if key.startswith("APP_") and value is not None})
    result.update({key: value for key, value in command_line.items() if value is not None})
    return result
```

```python
# test_config.py
from config import load_config


def test_defaults_file_environment_cli_precedence_is_preserved():
    assert load_config(
        {"host": "default", "port": "1", "debug": "false"},
        {"host": "file", "port": "2"},
        {"APP_HOST": "env", "APP_PORT": "3", "OTHER": "ignored"},
        {"host": "cli", "port": None},
    ) == {"host": "cli", "port": "3", "debug": "false"}


def test_none_values_do_not_erase_lower_precedence_values():
    assert load_config({"name": "default"}, {"name": None}, {"APP_NAME": None}, {"name": None}) == {"name": "default"}
```

The goal requires `config_sources.environment_values(environment)`, `config_sources.explicit_values(values)`, `config_merge.merge_layers(*layers)`, and the unchanged `config.load_config(defaults, file_values, environment, command_line)` precedence defaults < file < env < CLI.

- [x] **Step 7: Run protocol GREEN tests and commit**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py -k 'checked_in_m25_protocol or protocol_rejects'`

Expected: PASS with exactly nine unique tasks and family counts 3/2/2/2.

```bash
rtk git add docs/evaluation/m25/protocol.json tests/test_m25_mode_evaluation.py
rtk git commit -m "test(evaluation): fix M25 programming task suite"
```

### Task 4: Fixture 可解性、歧义和检查强度双审计

**Files:**
- Modify: `tests/test_m25_mode_evaluation.py`
- Test: `docs/evaluation/m25/protocol.json`

**Interfaces:**
- Consumes: checked-in M25 task specs, `prepare_workspace()`, `run_checks()`。
- Produces: `_write_reference_solution(task_id, workspace)` and executable audit tests proving initial failure/reference pass/immutable protection/check strength。

- [ ] **Step 1: Write the failing initial-versus-reference audit**

Add `_write_reference_solution()` with these exact transformations:

- TTL: replace `self._clock() <= expires_at` with `self._clock() < expires_at`.
- Invoice: remove subtotal quantization from `invoice.py`; in `discounts.py` iterate `adjustments` in supplied order, subtract `total * amount` for percent and `amount` for fixed, reject other kinds with `ValueError("unknown adjustment kind")`, clamp to zero, then quantize once with `ROUND_HALF_UP`.
- Topological: add public `CycleError(ValueError)` and the ready-batch algorithm that copies dependency sets, picks `tuple(sorted(node for node, deps in remaining.items() if not deps))`, raises `CycleError("dependency cycle")` when empty, removes the ready nodes and subtracts them from remaining dependencies; export both public names.
- JSONL: add `process_jsonl(lines)` with one parse/normalize try block per non-empty line, append `{ "line": line_number, "error": type(error).__name__ }` on the four fixed exception types, and make CLI always write both files and return `1 if rejected else 0`.
- Notification: create `routing.py` containing the existing selection branches and return `(channel, address)`; make `notifications.py` import it and build the unchanged result dict.
- Config: create `config_sources.py` with the two fixed filtering functions, `config_merge.py` with ordered `dict.update`, and reduce `config.load_config()` to `merge_layers(dict(defaults), explicit_values(file_values), environment_values(environment), explicit_values(command_line))`.

Then add:

```python
@pytest.mark.parametrize("task_id", [
    "fix-ttl-expiration-boundary",
    "fix-invoice-discount-composition",
    "add-topological-batches",
    "add-jsonl-dead-letter-output",
    "refactor-notification-routing",
    "refactor-config-precedence",
])
def test_real_programming_fixture_fails_initially_and_reference_passes(task_id, tmp_path):
    harness = load_harness()
    protocol, _ = harness.load_protocol(M25_PROTOCOL_PATH)
    task = next(task for task in protocol.tasks if task.id == task_id)
    initial = tmp_path / "initial"
    initial.mkdir()
    harness.prepare_workspace(task, initial)
    assert any(check.status != "passed" for check in harness.run_checks(task, initial))
    reference = tmp_path / "reference"
    reference.mkdir()
    harness.prepare_workspace(task, reference)
    immutable_before = {path: (reference / path).read_bytes() for path in task.immutable_files}
    _write_reference_solution(task_id, reference)
    assert all(check.status == "passed" for check in harness.run_checks(task, reference))
    assert immutable_before == {path: (reference / path).read_bytes() for path in task.immutable_files}
```

- [ ] **Step 2: Run RED solvability audit**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py::test_real_programming_fixture_fails_initially_and_reference_passes`

Expected: FAIL until every reference transformation is complete and every initial fixture has a failing check.

- [ ] **Step 3: Write and run the second check-strength audit**

Add one plausible incomplete candidate per task and assert its checks fail:

```python
WEAK_MUTATIONS = {
    "fix-ttl-expiration-boundary": ("cache.py", "< expires_at", "<= expires_at"),
    "fix-invoice-discount-composition": ("discounts.py", "for kind, value in adjustments:", "for kind, value in sorted(adjustments):"),
    "add-topological-batches": ("dependency_graph/graph.py", "tuple(sorted(", "tuple("),
    "add-jsonl-dead-letter-output": ("cli.py", "return 1 if rejected else 0", "return 0"),
    "refactor-notification-routing": ("notifications.py", "from routing import route_notification", "# route remains local"),
    "refactor-config-precedence": ("config.py", "environment_values(environment)", "explicit_values(file_values)"),
}
```

For each task: prepare a fresh workspace, write the full reference solution, apply its exact weak replacement, assert at least one declared check is non-passing, and assert `fixture-integrity` also fails after changing one immutable byte. This is the second audit for ambiguity and check strength.

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py -k 'fixture_fails_initially or check_strength or fixture_integrity'`

Expected: PASS for all six initial/reference/weak/immutable cases.

- [ ] **Step 4: Commit**

```bash
rtk git add tests/test_m25_mode_evaluation.py
rtk git commit -m "test(evaluation): audit M25 fixture solvability"
```

### Task 5: 双模型执行装配、environment 与调用前 preflight

**Files:**
- Modify: `scripts/m23_mode_evaluation.py:217-243,434-464,634-858,1133-1340`
- Modify: `tests/test_m25_mode_evaluation.py`
- Test: `tests/test_m23_mode_evaluation.py`
- Test: `tests/test_m25_mode_evaluation.py`

**Interfaces:**
- Consumes: `protocol_model_ids()`, `run_model_id()`, `protocol_namespace()`, `route_hash_for_model()`, union schedule/identity。
- Produces: dual-route `environment_manifest()`, union-aware `PreflightContext`, `run_single()`, `run_collaboration()`, `execute_run()`, `preflight()`, `run_command()`。

- [ ] **Step 1: Write RED model-routing and safe-environment tests**

Use fake clients with distinct `client_kind` and base URLs. After calling `preflight()` with `client_builder` and monkeypatched `resolve_model`, make these exact assertions:

```python
assert built_model_ids == ["claude-haiku-4-5", "gpt-5.4-mini"]
assert [route.model_id for route in context.environment.model_routes] == built_model_ids
assert all(client.closed for client in clients)
persisted = (output / "environment.json").read_text(encoding="utf-8")
assert "SECRET" not in persisted
assert "https://" not in persisted
assert context.environment.tracked_dirty is False
```

Add tests that missing/ambiguous credential route, capability model mismatch, insufficient output limit, tracked dirty source, mismatched existing environment, M25 output under `docs/evaluation/m23/runs`, and an existing raw route conflict all fail before `run_single()`/`run_collaboration()` is called. Monkeypatch `_git_value` with explicit `rev-parse` and `status` returns so the dirty test is deterministic.

For execution, parameterize Single/Duo/Triad and both models; capture every `build_real_client(model_id, registry=registry)` call and every Task/Collaboration model field. Assert all roles for one `M25RunSpec` use that run's model, IDs start with `m25-` and use three sequence digits, and M23 continues using `m23-` with two digits.

- [ ] **Step 2: Run RED execution/preflight tests**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py -k 'preflight or run_single or run_collaboration or execute_run or output_root'`

Expected: FAIL because execution and preflight still read only `protocol.model_id` and one route.

- [ ] **Step 3: Implement safe dual-route environment construction**

For each `protocol_model_ids(protocol)`, `preflight()` must:

1. validate output root before registry/client construction;
2. build and close one probe client;
3. verify capability model ID and `max_output_tokens >= 4096`;
4. resolve exactly one model route and compute `canonical_sha256([model_id, client_kind, base_url or "provider-default"])`;
5. retain only `(client_kind, route_sha256)` after the probe closes.

For M25, reject non-empty tracked `git status --porcelain --untracked-files=no` before writing environment. Serialize two `M25ModelRoute` values in protocol model order. Existing environment reuse compares `environment_sha256()`, whose implementation removes only `generated_at`. For M23, keep the current dirty-field recording and one-route serialization behavior.

- [ ] **Step 4: Route every mode through the RunSpec model**

Replace each M23-only `protocol.model_id` execution lookup with:

```python
model_id = run_model_id(protocol, run_spec)
client = build_real_client(model_id, registry=registry)
namespace = protocol_namespace(protocol)
sequence = f"{run_spec.sequence:02d}" if namespace == "m23" else f"{run_spec.sequence:03d}"
```

Use `model_id` for planner/generator/evaluator model fields and include model ID in the M25 collaboration hash input. Keep M23 hash input and task/collaboration IDs unchanged. `build_raw_record()` selects `RawRecord` or `M25RawRecord`; the M25 record adds `terminal=True`, family/model/route fields and otherwise uses the existing safe projections.

In `run_command()` and `aggregate_command()`, derive the default allowed root as `docs/evaluation/{protocol_namespace(protocol)}/runs`. Pass the full environment to M25 pending/read validation. Prefix temporary workspaces `forgeagent-m23-` or `forgeagent-m25-` from the namespace.

- [ ] **Step 5: Run GREEN, safety, and M23 tests**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py -k 'preflight or environment or run_single or run_collaboration or execute_run or output_root or sensitive' tests/test_m23_mode_evaluation.py`

Expected: PASS; M23 route/ID/manifest tests remain unchanged.

- [ ] **Step 6: Commit**

```bash
rtk git add scripts/m23_mode_evaluation.py tests/test_m25_mode_evaluation.py
rtk git commit -m "feat(evaluation): execute M25 across fixed model routes"
```

### Task 6: 完整 raw 校验、分层聚合与中立报告

**Files:**
- Modify: `scripts/m23_mode_evaluation.py:859-1132,1254-1290`
- Modify: `tests/test_m25_mode_evaluation.py`
- Test: `tests/test_m23_mode_evaluation.py`
- Test: `tests/test_m25_mode_evaluation.py`

**Interfaces:**
- Consumes: `M25RawRecord`, complete M25 schedule, `route_hash_for_model()`, existing `_aggregate_group()` metrics。
- Produces: strict M25 `read_raw_records()`, `_validate_complete_m25_records()`, `_aggregate_m25_records()`, `_render_m25_report()` and dispatching `aggregate_records()/render_report()`。

- [ ] **Step 1: Write RED synthetic 270-record aggregation tests**

Add `make_m25_raw_record()` and `make_complete_m25_records()` using the fixed schedule. Give every record one known usage call, and every tenth record one additional missing-usage logical call. Assert:

```python
assert summary["completeness"] == {"expected_runs": 270, "observed_runs": 270, "complete": True}
assert summary["models"]["claude-haiku-4-5"]["modes"]["single"]["scheduled_runs"] == 45
assert summary["models"]["gpt-5.4-mini"]["modes"]["triad"]["scheduled_runs"] == 45
assert summary["families"]["baseline"]["models"]["claude-haiku-4-5"]["modes"]["duo"]["scheduled_runs"] == 15
assert summary["families"]["bugfix"]["models"]["gpt-5.4-mini"]["modes"]["single"]["scheduled_runs"] == 10
assert summary["tasks"]["csv-region-summary"]["family"] == "baseline"
assert summary["tasks"]["csv-region-summary"]["models"]["claude-haiku-4-5"]["modes"]["single"]["scheduled_runs"] == 5
assert summary["models"]["claude-haiku-4-5"]["modes"]["single"]["first_acceptance_rate"] is None
```

For a selected group, independently sum `logical_model_calls` and `usage_missing_calls` from records and assert the summary rate is `{numerator, denominator, value}` with those call totals; independently sum only non-null token values and assert each summary token `sum` matches.

- [ ] **Step 2: Write RED completeness and mixed-batch rejection tests**

Starting from 270 valid records, independently test missing, extra, duplicate combination, M23 schema, wrong protocol/environment/RunSpec hash, wrong model/route/family/run ID/sequence/filename, and `terminal != true`. Assert `aggregate_command()` leaves pre-existing `summary.json` and `report.md` bytes unchanged on every invalid set.

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py -k 'aggregate or complete or mixed or denominator'`

Expected: FAIL because current aggregation only understands 27 M23 records and cross-model slices do not exist.

- [ ] **Step 3: Implement exact M25 completeness and grouping**

`_validate_complete_m25_records()` maps records by `(task_id, model_id, repeat, mode)`, requires 270 unique combinations, and compares every field plus exact `run_id_for()` and route hash to its scheduled spec/environment. Return sequence-sorted records only after all checks pass.

Return this summary shape; do not add cross-model combined scores:

```python
{
    "schema": "forgeagent.m25.mode-evaluation.summary/v1",
    "protocol_sha256": protocol_sha256,
    "environment_sha256": environment_sha256,
    "generated_at": _utc_now(),
    "completeness": {"expected_runs": 270, "observed_runs": 270, "complete": True},
    "models": {model_id: {"modes": {mode: metrics}}},
    "families": {family: {"models": {model_id: {"modes": {mode: metrics}}}}},
    "tasks": {task_id: {"family": family, "models": {model_id: {"modes": {mode: metrics}}}}},
    "failures": failures,
    "usage_missing_runs": usage_missing_runs,
    "limitations": [
        "Nine fixed tasks and five repetitions per model and mode remain descriptive evidence.",
        "Provider-side model weights cannot be independently pinned or verified.",
        "Local platform, date, and provider routes limit generalization.",
        "Results do not establish a cross-model ranking or product recommendation."
    ]
}
```

Reuse `_aggregate_group()` so token/null/call/attempt/latency semantics remain identical. Keep the existing M23 summary dict and validation error text unchanged.

- [ ] **Step 4: Write RED report neutrality tests, then render per model/family/task**

Assert the report includes two separately labeled model sections, each mode sample size, family/task tables, provider/model-weight/time/local-platform limitations, explicit `N/A` for Single acceptance metrics, failures and usage gaps. Recursively scan summary keys and the report conclusion template for the forbidden decision terms; task IDs are values and are not substring-scanned.

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py -k 'report or neutral or ranking'`

Expected: FAIL until `_render_m25_report()` exists.

Implement `_render_m25_report()` with headings `## Model: <id>`, `### Mode: <mode>`, `## Task Families`, `## Tasks`, `## Failures And Usage Gaps`, and `## Limitations`. Show rate numerator/denominator/value, token/call/attempt/latency distributions, and usage missing rate for every model/mode; show family/task scheduled and completion denominators without collapsing models.

- [ ] **Step 5: Run GREEN and commit**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py -k 'aggregate or complete or mixed or denominator or report or neutral' tests/test_m23_mode_evaluation.py`

Expected: PASS, including repeated aggregation with equivalent metric values after ignoring only `generated_at`.

```bash
rtk git add scripts/m23_mode_evaluation.py tests/test_m25_mode_evaluation.py
rtk git commit -m "feat(evaluation): aggregate complete M25 evidence"
```

### Task 7: 独立复算与递归证据安全门

**Files:**
- Create: `scripts/m25_independent_recompute.py`
- Create: `tests/test_m25_independent_recompute.py`
- Modify: `tests/test_m25_mode_evaluation.py`
- Test: `tests/test_m25_independent_recompute.py`
- Test: `tests/test_m25_mode_evaluation.py`

**Interfaces:**
- Consumes: M25 protocol/environment/raw/summary JSON files only。
- Produces: `recompute(protocol_path: Path, output_dir: Path) -> dict[str, object]`, `verify_summary(protocol_path: Path, output_dir: Path) -> None`, CLI `--protocol/--output` with exit 0 and `INDEPENDENT_RECOMPUTE_OK runs=270`。

- [ ] **Step 1: Write failing independent recompute tests**

Create a complete synthetic evidence directory with the Task 6 helpers, write protocol/environment/raw/summary, and load the script via `importlib`. Assert:

```python
projection = recompute.recompute(M25_PROTOCOL_PATH, output)
assert projection["runs"] == 270
assert projection["models"]["claude-haiku-4-5"]["single"]["scheduled_runs"] == 45
recompute.verify_summary(M25_PROTOCOL_PATH, output)

summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
summary["models"]["gpt-5.4-mini"]["modes"]["duo"]["scheduled_runs"] = 44
(output / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
with pytest.raises(ValueError, match="independent recompute mismatch"):
    recompute.verify_summary(M25_PROTOCOL_PATH, output)


def test_recompute_script_does_not_import_harness_aggregation():
    source = (ROOT / "scripts/m25_independent_recompute.py").read_text(encoding="utf-8")
    assert "m23_mode_evaluation" not in source
    assert "aggregate_records" not in source
    assert "render_report" not in source
```

- [ ] **Step 2: Run RED recompute tests**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_independent_recompute.py`

Expected: FAIL because the independent script is absent.

- [ ] **Step 3: Implement the independent stdlib projection**

Use only `argparse`, `json`, `pathlib`, `collections`, `math`, and `typing`. Validate protocol schema/model/task/family/repetition constants, environment schema and two route hashes, exactly 270 regular non-symlink raw files, unique `(task_id, model_id, repeat, mode)`, all terminal, and all protocol/environment/model/family bindings. Recompute these exact values per model/mode, family/model/mode, and task/model/mode:

```python
{
    "scheduled_runs": int,
    "solved_runs": int,
    "logical_model_calls": int,
    "provider_attempts": int,
    "usage_missing_calls": int,
    "usage_rate_denominator_calls": int,
    "tokens": {
        "input_tokens": int,
        "output_tokens": int,
        "cached_tokens": int,
        "reasoning_tokens": int,
    },
}
```

Token totals add only non-null raw values. `verify_summary()` compares each projection value to the corresponding aggregate distribution `sum` or rate numerator/denominator; compare counts with exact integer equality and rates with `math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12)`.

- [ ] **Step 4: Add recursive secret/path/key scans**

In `tests/test_m25_mode_evaluation.py`, recursively walk `M25EnvironmentManifest`, `M25RawRecord`, and summary dumps. Reject keys matching case-insensitive `goal|prompt|messages|reply|body|text|api_key|credential|base_url|absolute_path`; reject sentinel secret/base URL/absolute workspace values anywhere in strings. Separately assert check records contain only `id,status,exit_code,duration_ms,stdout_bytes,stderr_bytes,stdout_sha256,stderr_sha256`.

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_independent_recompute.py tests/test_m25_mode_evaluation.py -k 'recompute or sensitive or safe_surface or output_projection'`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add scripts/m25_independent_recompute.py tests/test_m25_independent_recompute.py tests/test_m25_mode_evaluation.py
rtk git commit -m "test(evaluation): independently verify M25 aggregates"
```

### Task 8: 离线门禁、M23 hash 保护与实现冻结提交

**Files:**
- Verify: `scripts/m23_mode_evaluation.py`
- Verify: `scripts/m25_independent_recompute.py`
- Verify: `tests/test_m23_mode_evaluation.py`
- Verify: `tests/test_m25_mode_evaluation.py`
- Verify: `tests/test_m25_independent_recompute.py`
- Verify: `docs/evaluation/m23/**`
- Verify: `docs/evaluation/m25/protocol.json`

**Interfaces:**
- Consumes: all offline implementation from Tasks 1-7。
- Produces: green offline gate and a committed, tracked-clean implementation SHA used by the real environment manifest。

- [ ] **Step 1: Run focused M23/M25 RED-GREEN suite**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m23_mode_evaluation.py tests/test_m25_mode_evaluation.py tests/test_m25_independent_recompute.py`

Expected: PASS; synthetic aggregation observes 270/270 and the M23 base-ref byte lock passes.

- [ ] **Step 2: Run formatting and static quality gates**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run ruff format --check scripts/m23_mode_evaluation.py scripts/m25_independent_recompute.py tests/test_m23_mode_evaluation.py tests/test_m25_mode_evaluation.py tests/test_m25_independent_recompute.py`

Expected: exit 0.

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run ruff check scripts/m23_mode_evaluation.py scripts/m25_independent_recompute.py tests/test_m23_mode_evaluation.py tests/test_m25_mode_evaluation.py tests/test_m25_independent_recompute.py`

Expected: `All checks passed!`

- [ ] **Step 3: Run complete offline project gates**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q`

Expected: exit 0; the final line contains `passed` and exactly `10 skipped` when Docker is unavailable.

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run python -m tests.golden.runner --output-dir /tmp/forgeagent-m25-golden`

Expected: 20/20 offline golden cases pass.

Run: `npx @fission-ai/openspec@1.4.1 validate --all --strict`

Expected: every specification reports valid and the command exits 0.

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache build --out-dir /tmp/forgeagent-m25-dist`

Expected: one wheel and one sdist are built successfully.

Run: `git diff --check`

Expected: no output, exit 0.

- [ ] **Step 4: Confirm M23 history and implementation freeze**

Run: `git diff --exit-code d7fa30526f829959102b5fb69b4778899d6b1f88 -- docs/evaluation/m23`

Expected: no output, exit 0.

Run: `git status --short --untracked-files=no`

Expected: no tracked modifications. If the preceding task commit omitted an implementation file, stage only the M25 implementation/protocol/tests and commit it before continuing; do not include real evidence or unrelated untracked paths.

Run: `git rev-parse HEAD`

Expected: a committed implementation SHA different from base-ref; record this exact SHA for comparison with M25 `environment.json.git_commit`.

### Task 9: 双 route preflight、真实 270-run 与独立复算证据

**Files:**
- Create: `docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/environment.json`
- Create: `docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/raw/*.json` (exactly 270)
- Create: `docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/summary.json`
- Create: `docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/report.md`
- Verify: `docs/evaluation/m23/**`

**Interfaces:**
- Consumes: committed clean implementation, configured credentials/routes for both fixed model IDs, fixed protocol and serial run/aggregate CLI。
- Produces: complete terminal evidence, reproducible aggregate outputs, independent recompute PASS and evidence commit。

- [ ] **Step 1: Create only the fixed M25 evidence root**

Run: `mkdir -p docs/evaluation/m25/runs`

Expected: directory exists; no M23 path is created, removed, or modified.

- [ ] **Step 2: Execute preflight without a provider model call**

Run:

```bash
rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run python -c "import importlib.util; from pathlib import Path; path=Path('scripts/m23_mode_evaluation.py'); spec=importlib.util.spec_from_file_location('m25_preflight', path); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); protocol,digest=module.load_protocol(Path('docs/evaluation/m25/protocol.json')); output=Path('docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini'); context=module.preflight(protocol,digest,output,allowed_output_root=Path('docs/evaluation/m25/runs')); print(f'models={len(context.environment.model_routes)} routes={len({route.provider_route_sha256 for route in context.environment.model_routes})} runs={len(module.build_schedule(protocol))} commit={context.environment.git_commit}')"
```

Expected: `models=2 routes=2 runs=270 commit=<Task 8 implementation SHA>` and exit 0. Failure means no real run starts; fix only route/credential/configuration or implementation defect, rerun all affected Task 8 gates, commit tracked fixes, remove only the uncommitted M25 environment created by the failed preflight when its identity no longer matches, and rerun this step.

- [ ] **Step 3: Execute or safely resume the fixed serial batch**

Run:

```bash
rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run python scripts/m23_mode_evaluation.py run --protocol docs/evaluation/m25/protocol.json --output docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini
```

Expected: each absent run prints `RUN sequence=<n>` then `DONE sequence=<n> solved=<true|false>`; each exact existing terminal raw prints `SKIP sequence=<n>`; interruption exits without a partial raw and the identical command resumes. Exit 0 occurs only after 270 complete raws aggregate successfully. Do not run two copies concurrently.

- [ ] **Step 4: Assert complete identities before trusting aggregates**

Run:

```bash
rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run python -c "import json; from collections import Counter; from pathlib import Path; root=Path('docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini'); rows=[json.loads(path.read_text()) for path in sorted((root/'raw').glob('*.json'))]; assert len(rows)==270; assert len({(r['task_id'],r['model_id'],r['repeat'],r['mode']) for r in rows})==270; assert Counter(r['model_id'] for r in rows)=={'claude-haiku-4-5':135,'gpt-5.4-mini':135}; assert Counter(r['mode'] for r in rows)=={'single':90,'duo':90,'triad':90}; assert all(r['terminal'] is True for r in rows); print('RAW_IDENTITY_OK runs=270')"
```

Expected: `RAW_IDENTITY_OK runs=270`.

- [ ] **Step 5: Prove repeat aggregation equivalence and independent recompute**

First copy `summary.json` and `report.md` to `/tmp/forgeagent-m25-summary-first.json` and `/tmp/forgeagent-m25-report-first.md`, rerun:

```bash
rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run python scripts/m23_mode_evaluation.py aggregate --protocol docs/evaluation/m25/protocol.json --output docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini
```

Compare both summaries after deleting only `generated_at`; compare reports byte-for-byte. Expected: metric dicts equal and report bytes equal.

Run:

```bash
rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run python scripts/m25_independent_recompute.py --protocol docs/evaluation/m25/protocol.json --output docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini
```

Expected: `INDEPENDENT_RECOMPUTE_OK runs=270`.

- [ ] **Step 6: Scan real evidence safety and protect M23 once more**

Run the recursive checked-in test against the real evidence root by passing it through the test's explicit `M25_REAL_EVIDENCE_ROOT` environment hook; the hook only selects a read-only test input and does not alter product configuration:

Run: `M25_REAL_EVIDENCE_ROOT=docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py -k 'real_evidence_safety or tracked_m23'`

Expected: PASS; no sensitive key/value/path leaks and M23 bytes remain identical to base-ref.

- [ ] **Step 7: Commit only complete M25 evidence**

```bash
rtk git add docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini
rtk git commit -m "data(evaluation): record complete M25 model batch"
```

### Task 10: 公开文档、M25 里程碑与最终验证

**Files:**
- Create: `docs/evaluation/m25/README.md`
- Modify: `README.md`
- Modify: `ACTION_PLAN.md`
- Modify: `openspec/changes/m25-programming-mode-evaluation/tasks.md`
- Create: `milestones/milestone_025.md`
- Modify: `milestones/latest`
- Modify: `tests/test_m25_mode_evaluation.py`

**Interfaces:**
- Consumes: complete real report/summary, independent recompute PASS, Task 8/9 command outputs, `MILESTONE_GUIDE.md`。
- Produces: discoverable neutral evidence, completed OpenSpec task ledger, M25 milestone and final verified repository state。

- [ ] **Step 1: Write RED public-document contracts**

Add a test that requires all public documents to link `docs/evaluation/m25/protocol.json`, the fixed real `report.md`, and `scripts/m25_independent_recompute.py`; require the M25 ACTION_PLAN row and milestone to state 270/270, both model IDs, local/date/provider-weight limitations, no automatic ranking, independent recompute PASS, and M23 unchanged. Assert `milestones/latest` equals `milestone_025.md` and every checkbox in active M25 `tasks.md` is checked.

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py -k 'public_docs or milestone or action_plan'`

Expected: FAIL because M25 public docs and milestone are absent.

- [ ] **Step 2: Write the evaluation README and public entry points**

`docs/evaluation/m25/README.md` must contain:

- fixed protocol/models/tasks/repetitions and exact 270-run formula;
- exact `run`, `aggregate`, and independent recompute commands from Task 9;
- link to `runs/2026-07-27-haiku-4-5-gpt-5-4-mini/report.md` and `summary.json`;
- statement that raw is terminal/safe projection without prompt/reply/base URL/credential;
- statement that results bind the recorded date, local platform, provider routes and unpinned provider-side weights;
- statement that no cross-model or mode rank/recommendation is produced and M23 evidence was not changed.

Add a concise README section linking this document, protocol and report. Add an M25 ACTION_PLAN row with scope `9 tasks x 2 models x 3 modes x 5 repetitions`, evidence `270/270 terminal raw`, independent recompute PASS, and status `已完成并归档` only after Comet archive; before archive use `实现与真实证据完成，待 Comet verify/归档`.

- [ ] **Step 3: Create the milestone from verified facts**

Follow `MILESTONE_GUIDE.md` exactly. `milestones/milestone_025.md` must record:

- objective/scope and links to design, plan, active change, protocol, report and summary;
- ten task deliverables and 270/270 identity counts;
- both environment route hashes by safe SHA-256 only, never URL/credential;
- completion/failure/usage-missing denominators by linking the report rather than adding an unlabeled combined score;
- independent recompute command and `INDEPENDENT_RECOMPUTE_OK runs=270`;
- exact final verification command outputs produced in Step 5, including the actual pytest pass/skip counts;
- limitations and a continuation instruction that new models/tasks require a new versioned change, never mutation of M25 evidence.

Write `milestones/latest` as the single line `milestone_025.md`.

- [ ] **Step 4: Check all OpenSpec implementation boxes after evidence/docs exist**

Change each of the 18 `- [ ]` entries in `openspec/changes/m25-programming-mode-evaluation/tasks.md` to `- [x]`. Do not edit the delta spec or `.comet.yaml` in this task; Comet owns workflow state and verification report paths.

- [ ] **Step 5: Run final focused, full, golden, Ruff, build, OpenSpec and diff gates**

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m23_mode_evaluation.py tests/test_m25_mode_evaluation.py tests/test_m25_independent_recompute.py`

Expected: PASS, including real evidence safety and all public-document contracts.

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q`

Expected: exit 0; preserve the exact final summary line for the milestone.

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run python -m tests.golden.runner --output-dir /tmp/forgeagent-m25-golden-final`

Expected: 20/20 pass.

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run ruff check .`

Expected: `All checks passed!`

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run ruff format --check .`

Expected: exit 0.

Run: `rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache build --out-dir /tmp/forgeagent-m25-dist-final`

Expected: wheel and sdist build successfully without M25 raw evidence entering package artifacts.

Run: `npx @fission-ai/openspec@1.4.1 validate --all --strict`

Expected: every spec is valid, exit 0.

Run: `git diff --exit-code d7fa30526f829959102b5fb69b4778899d6b1f88 -- docs/evaluation/m23`

Expected: no output, exit 0.

Run: `git diff --check`

Expected: no output, exit 0.

- [ ] **Step 6: Complete two final audits**

Audit 1, contract/data: compare all OpenSpec requirements with protocol/environment/raw/summary/report; verify exact denominators, failure lists, usage gaps, Single N/A, route/family/model bindings and absence of partial aggregate writes.

Audit 2, privacy/neutrality/history: recursively scan all M25 JSON and report text for sensitive values/absolute paths, scan summary keys and conclusion templates for forbidden ranking semantics, and rerun the M23 base-ref byte lock. Any correction requires rerunning the affected focused tests plus Step 5 before commit.

- [ ] **Step 7: Commit documentation and milestone closure**

```bash
rtk git add README.md ACTION_PLAN.md docs/evaluation/m25/README.md milestones/milestone_025.md milestones/latest openspec/changes/m25-programming-mode-evaluation/tasks.md tests/test_m25_mode_evaluation.py
rtk git commit -m "docs(evaluation): close M25 evidence milestone"
```

After this commit, hand control back to Comet verify. Do not mark the change archived, alter `.comet.yaml`, or rewrite the ACTION_PLAN row to `已完成并归档` until Comet verification and the explicit archive decision succeed.
