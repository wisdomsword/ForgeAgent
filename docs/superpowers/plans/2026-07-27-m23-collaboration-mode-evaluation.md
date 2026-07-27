---
change: m23-collaboration-mode-evaluation
design-doc: docs/superpowers/specs/2026-07-27-m23-collaboration-mode-evaluation-design.md
base-ref: f6e0dda3c8a7f9c73400c240c0a999e20b12bbd6
---

# M23 Single/Duo/Triad 质量—成本评估 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在完全固定的任务、模型、生成参数、执行环境和产物检查下，串行重复运行 Single、Duo、Triad，保存安全的逐次机器记录并生成不作优劣结论的描述性聚合报告。

**Architecture:** 在 `scripts/` 中新增一个独立单文件 harness，直接组装现有公开 `Task`、`CollaborationRunner`、`AuditSink` 与 `check_runner` API；运行协议、任务夹具和顺序由一个版本化 JSON 固定。每次运行写一份原子 raw JSON，聚合器只能从完整 raw 集合复算 `summary.json` 与 `report.md`，不读取模型正文或运行时内存。

**Tech Stack:** Python 3.11+ 标准库、现有 Pydantic v2、ForgeAgent `Task`/`CollaborationRunner`/`AuditEvent`/`CheckDefinition`、pytest、Ruff、uv、OpenSpec/Comet。

## Global Constraints

- `openspec/changes/m23-collaboration-mode-evaluation/specs/collaboration-mode-evaluation/spec.md` 是行为合同事实源，技术细节以 design doc 为准。
- 严格 TDD：每个行为先新增目标测试并观察其因缺失行为而失败，再写最小实现使其通过。
- 只新增一个执行脚本 `scripts/m23_mode_evaluation.py` 和一个 M23 测试文件 `tests/test_m23_mode_evaluation.py`；仅允许在既有 `tests/test_collaboration_docs.py` 删除 M22 对 evolving `milestones/latest` 的历史硬编码，由 M23 测试接管当前指针合同；不得新增产品包模块、依赖、CLI 产品入口或配置面。
- 禁止修改 `src/forgeagent/collaboration.py`、`src/forgeagent/cli.py`、`src/forgeagent/model_registry.py`、credential 解析、角色提示词、memory、identity、skills、MCP 和 evaluator 能力。
- 所有角色固定使用 `claude-haiku-4-5`；生成参数固定为 `max_output_tokens=4096`、`temperature=0.0`、`thinking="off"`、`effort=null`、`timeout_seconds=120.0`。
- 执行固定为 `tier="restricted"`、`max_rounds=10`、`max_rejections=2`、零内容 `ApprovedIdentity`、无 memory/skills/MCP、Triad `headless_plan_confirmer("preauthorize")`。
- 三个任务各重复三次；固定轮换为 `single,duo,triad`、`duo,triad,single`、`triad,single,duo`，总计严格 27 次且串行运行。
- 任务完成定义为“runtime completed 且所有模式外产物检查通过”；Single 的 first acceptance、rejection、correction 必须为 JSON `null`。
- 每个 logical model call 缺失或含无效 usage 时进入缺失率分子；未知 token 不得转换成已知零。provider attempt 只统计 `llm.provider_attempt/result_status=started`。
- raw 证据不得含 goal、prompt、messages、reply/body/text、API key、base URL、完整环境或绝对主机路径；检查 stdout/stderr 只记录字节数和 SHA-256，不保存正文。
- `summary.json` 和 `report.md` 不得包含 winner、rank、recommendation、superiority 或任何自动宣称 Triad 优于 Single 的结论。
- 正式报告必须基于完整 27 份 raw 记录；中断后先用幂等 `run` 补齐，聚合器不提供不完整报告开关。
- 保留所有现有用户未跟踪文件，不把 `.agent/`、`.agents/`、`.claude/`、`.codex/`、`.superpowers/brainstorm/`、`skills-lock.json` 或 `何为Harness.html` 纳入提交。

---

## 文件结构

- Create: `scripts/m23_mode_evaluation.py` — 协议校验、排程、真实运行组装、安全投影、原子 raw 写入、聚合和两子命令 CLI。
- Create: `tests/test_m23_mode_evaluation.py` — 唯一离线合同测试，使用临时协议、fake audit 事件和 fake mode 结果覆盖全部 harness 行为与文档合同。
- Create: `docs/evaluation/m23/protocol.json` — 唯一版本化正式协议，内含三个任务的英文目标、夹具、检查和固定运行设置。
- Generate: `docs/evaluation/m23/runs/2026-07-27-haiku-4-5/environment.json` — 无 credential 的环境清单。
- Generate: `docs/evaluation/m23/runs/2026-07-27-haiku-4-5/raw/*.json` — 27 份逐次机器记录。
- Generate: `docs/evaluation/m23/runs/2026-07-27-haiku-4-5/summary.json` — 仅由 raw 复算的机器聚合。
- Generate: `docs/evaluation/m23/runs/2026-07-27-haiku-4-5/report.md` — 描述性人工报告。
- Modify: `README.md`、`ACTION_PLAN.md` — 链接 M23 协议/证据，区分描述性证据与产品结论。
- Create: `milestones/milestone_023.md`; Modify: `milestones/latest` — 按 `MILESTONE_GUIDE.md` 收尾。
- Modify: `tests/test_collaboration_docs.py` — 只删除 M22 对 `milestones/latest == milestone_022.md` 的历史断言，不改 M22 数字或证据断言。
- Modify: `openspec/changes/m23-collaboration-mode-evaluation/tasks.md` — 只在对应证据通过后逐项勾选。

### Task 1: 固定协议、严格校验与 27 次平衡排程

**Files:**
- Create: `docs/evaluation/m23/protocol.json`
- Create: `scripts/m23_mode_evaluation.py`
- Create: `tests/test_m23_mode_evaluation.py`
- Modify: `openspec/changes/m23-collaboration-mode-evaluation/tasks.md`

**Interfaces:**
- Produces: `PROTOCOL_SCHEMA = "forgeagent.m23.mode-evaluation/v1"`。
- Produces: frozen Pydantic models `CheckSpec`、`TaskSpec`、`EvaluationProtocol` and dataclass `RunSpec(sequence: int, task_id: str, repeat: int, mode: Literal["single", "duo", "triad"])`。
- Produces: `validate_protocol(value: object) -> EvaluationProtocol`、`load_protocol(path: Path) -> tuple[EvaluationProtocol, str]`、`build_schedule(protocol: EvaluationProtocol) -> tuple[RunSpec, ...]`、`run_spec_hash(spec: RunSpec, protocol_sha256: str) -> str`。
- Consumes later: Task 2 receives only validated model instances and `RunSpec`; it must never re-read unvalidated JSON dictionaries.

- [x] **Step 1: 创建测试加载器并写协议/排程 RED 合同**

在 `tests/test_m23_mode_evaluation.py` 先加入脚本模块加载器和以下测试骨架；测试必须直接读取正式 `protocol.json`，并用深拷贝变体覆盖失败分支：

```python
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).parents[1]
PROTOCOL_PATH = ROOT / "docs" / "evaluation" / "m23" / "protocol.json"


def load_harness():
    path = ROOT / "scripts" / "m23_mode_evaluation.py"
    spec = importlib.util.spec_from_file_location("m23_mode_evaluation", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def protocol_dict() -> dict[str, object]:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def test_checked_in_protocol_builds_balanced_27_run_schedule() -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)

    assert digest == harness.canonical_sha256(protocol.model_dump(mode="json", by_alias=True))
    assert len(schedule) == 27
    assert [item.mode for item in schedule[:9]] == [
        "single", "duo", "triad",
        "duo", "triad", "single",
        "triad", "single", "duo",
    ]
    assert {(item.task_id, item.repeat, item.mode) for item in schedule} == {
        (task.id, repeat, mode)
        for task in protocol.tasks
        for repeat in range(1, 4)
        for mode in ("single", "duo", "triad")
    }
    assert all(sum(item.mode == mode for item in schedule) == 9 for mode in protocol.modes)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.pop("generation"), "generation"),
        (lambda value: value.__setitem__("repetitions", 2), "at least 3"),
        (lambda value: value.__setitem__("modes", ["single", "duo"]), "modes"),
        (lambda value: value.__setitem__("mode_orders", [["single", "duo", "triad"]] * 3), "mode_orders"),
        (lambda value: value.__setitem__("unknown", True), "extra"),
        (lambda value: value["tasks"].append(copy.deepcopy(value["tasks"][0])), "task id"),
    ],
)
def test_protocol_rejects_incomplete_or_ambiguous_contract(mutate, message: str) -> None:
    harness = load_harness()
    value = protocol_dict()
    mutate(value)
    with pytest.raises((ValidationError, ValueError), match=message):
        harness.validate_protocol(value)


@pytest.mark.parametrize("bad_path", ["/tmp/escape", "../escape", "a/../../escape", "bad\x00name"])
def test_protocol_rejects_fixture_and_artifact_path_escape(bad_path: str) -> None:
    harness = load_harness()
    value = protocol_dict()
    value["tasks"][0]["initial_files"] = {bad_path: "x"}
    with pytest.raises((ValidationError, ValueError), match="relative path"):
        harness.validate_protocol(value)
```

- [x] **Step 2: 运行测试并确认 RED 原因准确**

Run: `rtk uv run pytest -q tests/test_m23_mode_evaluation.py -k 'protocol or schedule'`

Expected: FAIL during module load because `scripts/m23_mode_evaluation.py` and/or `docs/evaluation/m23/protocol.json` does not exist；不得接受因语法错误、测试夹具错误或环境 credential 导致的失败。

- [x] **Step 3: 写入唯一正式协议**

创建 `docs/evaluation/m23/protocol.json`，顶层键固定为下列集合，禁止 CLI 覆盖：

```json
{
  "schema": "forgeagent.m23.mode-evaluation/v1",
  "model_id": "claude-haiku-4-5",
  "generation": {
    "max_output_tokens": 4096,
    "temperature": 0.0,
    "thinking": "off",
    "effort": null,
    "timeout_seconds": 120.0
  },
  "execution": {
    "tier": "restricted",
    "max_rounds": 10,
    "max_rejections": 2,
    "identity": false,
    "memory": false,
    "skills": false,
    "mcp": false,
    "plan_policy": "preauthorize",
    "check_timeout_seconds": 30.0
  },
  "modes": ["single", "duo", "triad"],
  "repetitions": 3,
  "mode_orders": [
    ["single", "duo", "triad"],
    ["duo", "triad", "single"],
    ["triad", "single", "duo"]
  ],
  "tasks": [
  {
    "id": "csv-region-summary",
    "goal": "Read sales.csv. Create summarize.py using only the Python standard library. The script must accept INPUT_CSV OUTPUT_JSON arguments, sum integer amount values by region, and write a JSON object with region keys in sorted order. Also run it to create summary.json for the provided input. Do not change sales.csv.",
    "initial_files": {
      "sales.csv": "region,amount\nNorth,10\nSouth,7\nNorth,5\nSouth,3\nWest,8\n"
    },
    "required_candidate_files": ["summarize.py", "summary.json"],
    "checks": [{
      "id": "csv-summary",
      "command": ["{python}", "-c", "import json, subprocess, sys; from pathlib import Path; expected = {'North': 15, 'South': 10, 'West': 8}; subprocess.run([sys.executable, 'summarize.py', 'sales.csv', '.m23-check-summary.json'], check=True); assert json.loads(Path('summary.json').read_text(encoding='utf-8')) == expected; assert json.loads(Path('.m23-check-summary.json').read_text(encoding='utf-8')) == expected"],
      "timeout_seconds": 30.0
    }],
    "artifacts": ["summarize.py", "summary.json"]
  },
  {
    "id": "fix-range-compression",
    "goal": "Fix range_compression.py without changing the public compress_ranges(values) signature. It must sort and deduplicate integers, combine consecutive values into inclusive 'start-end' strings, keep single values as strings, and return an empty list for empty input. Make the existing test_range_compression.py pass. Do not edit the test file.",
    "initial_files": {
      "range_compression.py": "def compress_ranges(values):\n    ordered = sorted(set(values))\n    if not ordered:\n        return []\n    result = []\n    start = end = ordered[0]\n    for value in ordered[1:]:\n        if value == end:\n            end = value\n            continue\n        result.append(str(start) if start == end else f'{start}-{end}')\n        start = end = value\n    result.append(str(start) if start == end else f'{start}-{end}')\n    return result\n",
      "test_range_compression.py": "from range_compression import compress_ranges\n\n\ndef test_mixed_ranges():\n    assert compress_ranges([1, 2, 3, 5, 7, 8]) == ['1-3', '5', '7-8']\n\n\ndef test_empty_and_duplicates():\n    assert compress_ranges([]) == []\n    assert compress_ranges([4, 4, 4]) == ['4']\n\n\ndef test_negative_values():\n    assert compress_ranges([-3, -2, 0]) == ['-3--2', '0']\n"
    },
    "required_candidate_files": ["range_compression.py"],
    "checks": [{
      "id": "range-pytest",
      "command": ["{python}", "-m", "pytest", "-q", "test_range_compression.py"],
      "timeout_seconds": 30.0
    }],
    "artifacts": ["range_compression.py"]
  },
  {
    "id": "normalize-events",
    "goal": "Read events.json. Create normalize_events.py using only the Python standard library. The script must accept INPUT_JSON OUTPUT_JSON arguments, keep the event with the lexicographically latest ISO-8601 timestamp for each id, then sort retained events by timestamp and id, preserving every event field. Also run it to create normalized.json. Do not change events.json.",
    "initial_files": {
      "events.json": "[\n  {\"id\": \"a\", \"timestamp\": \"2026-01-02T10:00:00Z\", \"kind\": \"open\"},\n  {\"id\": \"b\", \"timestamp\": \"2026-01-01T12:00:00Z\", \"kind\": \"create\"},\n  {\"id\": \"a\", \"timestamp\": \"2026-01-03T09:00:00Z\", \"kind\": \"close\"},\n  {\"id\": \"c\", \"timestamp\": \"2026-01-01T12:00:00Z\", \"kind\": \"create\"}\n]\n"
    },
    "required_candidate_files": ["normalize_events.py", "normalized.json"],
    "checks": [{
      "id": "normalized-events",
      "command": ["{python}", "-c", "import json, subprocess, sys; from pathlib import Path; expected = [{'id': 'b', 'timestamp': '2026-01-01T12:00:00Z', 'kind': 'create'}, {'id': 'c', 'timestamp': '2026-01-01T12:00:00Z', 'kind': 'create'}, {'id': 'a', 'timestamp': '2026-01-03T09:00:00Z', 'kind': 'close'}]; subprocess.run([sys.executable, 'normalize_events.py', 'events.json', '.m23-check-events.json'], check=True); assert json.loads(Path('normalized.json').read_text(encoding='utf-8')) == expected; assert json.loads(Path('.m23-check-events.json').read_text(encoding='utf-8')) == expected"],
      "timeout_seconds": 30.0
    }],
    "artifacts": ["normalize_events.py", "normalized.json"]
  }
  ]
}
```

上述完整 JSON 是唯一正式协议内容；字符串中的换行使用 `\n` 转义。

每个 task 的键只能是 `id`、`goal`、`initial_files`、`required_candidate_files`、`checks`、`artifacts`；每个 check 的键只能是 `id`、`command`、`timeout_seconds`。所有 goal/fixture/check 代码必须在 JSON 中完整写出，不引用仓库外脚本或网络资源。

- [x] **Step 4: 实现最小严格模型、canonical hash 和排程**

在 `scripts/m23_mode_evaluation.py` 中实现以下结构，不先加入真实 client 代码：

```python
PROTOCOL_SCHEMA = "forgeagent.m23.mode-evaluation/v1"
MODES = ("single", "duo", "triad")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GenerationSettings(StrictModel):
    max_output_tokens: Literal[4096]
    temperature: Literal[0.0]
    thinking: Literal["off"]
    effort: None
    timeout_seconds: Literal[120.0]


class ExecutionSettings(StrictModel):
    tier: Literal["restricted"]
    max_rounds: Literal[10]
    max_rejections: Literal[2]
    identity: Literal[False]
    memory: Literal[False]
    skills: Literal[False]
    mcp: Literal[False]
    plan_policy: Literal["preauthorize"]
    check_timeout_seconds: Literal[30.0]


class CheckSpec(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    command: tuple[str, ...] = Field(min_length=2)
    timeout_seconds: Literal[30.0]


class TaskSpec(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    goal: str = Field(min_length=1, max_length=4000)
    initial_files: dict[str, str]
    required_candidate_files: tuple[str, ...] = Field(min_length=1)
    checks: tuple[CheckSpec, ...] = Field(min_length=1)
    artifacts: tuple[str, ...] = Field(min_length=1)


class EvaluationProtocol(StrictModel):
    schema_: Literal[PROTOCOL_SCHEMA] = Field(PROTOCOL_SCHEMA, alias="schema")
    model_id: Literal["claude-haiku-4-5"]
    generation: GenerationSettings
    execution: ExecutionSettings
    modes: tuple[Literal["single", "duo", "triad"], ...]
    repetitions: Literal[3]
    mode_orders: tuple[tuple[Literal["single", "duo", "triad"], ...], ...]
    tasks: tuple[TaskSpec, ...] = Field(min_length=3, max_length=3)


@dataclass(frozen=True)
class RunSpec:
    sequence: int
    task_id: str
    repeat: int
    mode: Literal["single", "duo", "triad"]


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()
```

`validate_protocol` 必须额外检查：模式恰为三个且无重复；恰有三个 task 且 ID 唯一；`mode_orders` 数量等于 repetitions，且逐行精确等于上方三行固定轮换；所有路径均是非空 canonical relative POSIX path，禁止绝对路径、`.`、`..`、反斜杠、NUL/控制字符；同一列表内路径唯一；`required_candidate_files` 是 `artifacts` 的子集；check 首项必须为字面值 `{python}`，运行时只替换为 `sys.executable` 后构造 `CheckDefinition`；所有固定设置与上方 Global Constraints 完全相等。`load_protocol` 先 `json.loads`，再校验并对 validated model 的 alias JSON 计算摘要。`build_schedule` 按 task → repeat → 对应 mode order 生成 sequence 1..27。

- [x] **Step 5: 运行协议测试至 GREEN 并完成第一轮自审**

Run: `rtk uv run pytest -q tests/test_m23_mode_evaluation.py -k 'protocol or schedule'`

Expected: PASS；确认 27 个 RunSpec 唯一、每模式 9 次、每 task/mode 3 次。

自审检查：删除任意固定字段、加入未知键、把路径换成绝对/逃逸路径、把重复数降为 2、把 order 改成非排列时，都必须在模型调用前失败。

- [x] **Step 6: 勾选 1.1 并提交 Task 1**

仅在上一步通过后勾选 OpenSpec task `1.1`，暂不勾选 `1.2`。

```bash
rtk git add docs/evaluation/m23/protocol.json scripts/m23_mode_evaluation.py tests/test_m23_mode_evaluation.py openspec/changes/m23-collaboration-mode-evaluation/tasks.md
rtk git commit -m "feat: define M23 evaluation protocol"
```

### Task 2: 隔离运行、audit 投影、外部检查与原子 raw 记录

**Files:**
- Modify: `scripts/m23_mode_evaluation.py`
- Modify: `tests/test_m23_mode_evaluation.py`
- Modify: `openspec/changes/m23-collaboration-mode-evaluation/tasks.md`

**Interfaces:**
- Produces: `CollectingAuditSink.emit(event: AuditEvent) -> bool`、`EnvironmentManifest`、`ModeResult`、`TokenTotals`、`AuditMetrics`、`CheckRecord`、`ArtifactResult`、`RawRecord`。
- Produces: `environment_manifest(protocol: EvaluationProtocol, protocol_sha256: str, *, repo_root: Path, provider_route_sha256: str) -> EnvironmentManifest`、`prepare_workspace(task: TaskSpec, root: Path) -> None`。
- Produces: `run_single(protocol: EvaluationProtocol, task: TaskSpec, run_spec: RunSpec, workspace: Path, registry: Registry, audit_sink: CollectingAuditSink) -> ModeResult`。
- Produces: `run_collaboration(protocol: EvaluationProtocol, task: TaskSpec, run_spec: RunSpec, workspace: Path, registry: Registry, audit_sink: CollectingAuditSink) -> ModeResult`。
- Produces: `project_audit_metrics(events: Sequence[AuditEvent]) -> AuditMetrics`、`run_checks(task: TaskSpec, workspace: Path) -> tuple[CheckRecord, ...]`、`hash_artifacts(task: TaskSpec, workspace: Path) -> tuple[ArtifactResult, ...]`、`write_raw_record(path: Path, record: RawRecord) -> None`。
- Produces: `build_raw_record(*, run_spec: RunSpec, mode_result: ModeResult, checks: tuple[CheckRecord, ...], artifacts: tuple[ArtifactResult, ...], audit_metrics: AuditMetrics, protocol_sha256: str, environment_sha256: str, started_at: str, finished_at: str, end_to_end_latency_seconds: float, error_category: str | None = None) -> RawRecord`。
- Produces orchestration: `execute_run(protocol: EvaluationProtocol, protocol_sha256: str, environment_sha256: str, task: TaskSpec, run_spec: RunSpec, workspace: Path, registry: Registry) -> RawRecord`；测试通过 monkeypatch `run_single`/`run_collaboration` 隔离真实模型，真实命令使用 `build_real_client(model_id, registry=registry)`。
- Consumes: Task 1 validated protocol and schedule；现有公开 `Task`、`CollaborationRunner.create`、`headless_plan_confirmer`、`ApprovedIdentity`、`GenerationParams`、`load_registry`、`build_real_client`、`CheckDefinition`、`run_check`。

- [x] **Step 1: 写安全投影、N/A、外部失败和原子写入 RED 测试**

追加以下测试（可把重复构造收敛到测试文件内普通 helper，不新增 fixture 文件）：

```python
from forgeagent.audit import AuditEvent


def test_audit_projection_counts_calls_attempts_tokens_and_missing_usage() -> None:
    harness = load_harness()
    events = [
        AuditEvent(event_type="llm.provider_attempt", result_status="started", attempt=1),
        AuditEvent(event_type="llm.provider_attempt", result_status="success", attempt=1),
        AuditEvent(
            event_type="llm.outcome",
            result_status="success",
            parameters={"usage": {"input_tokens": 10, "output_tokens": 4,
                                  "cached_tokens": 2, "reasoning_tokens": 1}},
        ),
        AuditEvent(event_type="llm.outcome", result_status="error", parameters={}),
    ]
    metrics = harness.project_audit_metrics(events)
    assert metrics.logical_model_calls == 2
    assert metrics.provider_attempts == 1
    assert metrics.usage_present_calls == 1
    assert metrics.usage_missing_calls == 1
    assert metrics.usage_missing_rate == 0.5
    assert metrics.tokens.model_dump() == {
        "input_tokens": 10, "output_tokens": 4,
        "cached_tokens": 2, "reasoning_tokens": 1,
    }


def test_no_calls_has_zero_calls_null_missing_rate_and_known_zero_tokens() -> None:
    harness = load_harness()
    metrics = harness.project_audit_metrics([])
    assert metrics.logical_model_calls == 0
    assert metrics.usage_missing_rate is None
    assert metrics.tokens.input_tokens == 0


def test_all_missing_usage_keeps_unknown_tokens_null() -> None:
    harness = load_harness()
    metrics = harness.project_audit_metrics([
        AuditEvent(event_type="llm.outcome", result_status="error", parameters={})
    ])
    assert metrics.logical_model_calls == metrics.usage_missing_calls == 1
    assert metrics.tokens.input_tokens is None
    assert metrics.tokens.output_tokens is None


def test_single_acceptance_loop_fields_are_null() -> None:
    harness = load_harness()
    result = harness.ModeResult(
        runtime_completed=True, runtime_status="completed", runtime_reason="completed",
        first_acceptance_passed=None, rejection_count=None, correction_count=None,
    )
    assert result.first_acceptance_passed is None
    assert result.rejection_count is None
    assert result.correction_count is None


def test_internal_completion_with_failed_external_check_is_not_solved(tmp_path: Path) -> None:
    harness = load_harness()
    record = harness.build_raw_record(
        run_spec=harness.RunSpec(1, "task", 1, "duo"),
        mode_result=harness.ModeResult(
            runtime_completed=True, runtime_status="completed", runtime_reason="completed",
            first_acceptance_passed=True, rejection_count=0, correction_count=0,
        ),
        checks=(harness.CheckRecord(
            id="artifact",
            status="failed",
            exit_code=1,
            stdout_bytes=0,
            stderr_bytes=0,
            stdout_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            stderr_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        ),),
        artifacts=(), audit_metrics=harness.project_audit_metrics([]),
        protocol_sha256="a" * 64, environment_sha256="b" * 64,
        started_at="2026-07-27T00:00:00.000Z", finished_at="2026-07-27T00:00:01.000Z",
        end_to_end_latency_seconds=1.0,
    )
    assert record.runtime_completed is True
    assert record.solved is False


def test_write_raw_record_is_atomic_and_never_leaves_temp_file(tmp_path: Path) -> None:
    harness = load_harness()
    record = make_raw_record(
        harness,
        harness.RunSpec(sequence=1, task_id="csv-region-summary", repeat=1, mode="single"),
        protocol_sha256="a" * 64,
    )
    target = tmp_path / "raw" / "01-task-r1-single.json"
    harness.write_raw_record(target, record)
    assert json.loads(target.read_text()) == record.model_dump(mode="json", by_alias=True)
    assert list(target.parent.glob(".*.tmp")) == []
```

在这些测试之前加入完整 test-only helper；后续 Task 3/4 复用它，不在 harness 增加测试专用 API：

```python
def make_raw_record(
    harness,
    spec,
    protocol_sha256: str,
    *,
    environment_sha256: str = "b" * 64,
    solved: bool = True,
):
    applicable = spec.mode != "single"
    return harness.RawRecord(
        run_id=f"{spec.sequence:02d}-{spec.task_id}-r{spec.repeat}-{spec.mode}",
        sequence=spec.sequence,
        task_id=spec.task_id,
        mode=spec.mode,
        repeat=spec.repeat,
        protocol_sha256=protocol_sha256,
        environment_sha256=environment_sha256,
        run_spec_sha256=harness.run_spec_hash(spec, protocol_sha256),
        started_at="2026-07-27T00:00:00.000Z",
        finished_at="2026-07-27T00:00:01.000Z",
        runtime_completed=True,
        runtime_status="completed",
        runtime_reason="completed",
        checks=(harness.CheckRecord(
            id="artifact",
            status="passed",
            exit_code=0,
            stdout_bytes=0,
            stderr_bytes=0,
            stdout_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            stderr_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        ),),
        artifacts=(),
        solved=solved,
        first_acceptance_passed=True if applicable else None,
        rejection_count=0 if applicable else None,
        correction_count=0 if applicable else None,
        tokens=harness.TokenTotals(
            input_tokens=10,
            output_tokens=4,
            cached_tokens=2,
            reasoning_tokens=1,
        ),
        logical_model_calls=1,
        provider_attempts=1,
        usage_present_calls=1,
        usage_missing_calls=0,
        usage_missing_rate=0.0,
        end_to_end_latency_seconds=1.0,
        error_category=None,
    )
```

再增加参数化测试覆盖：usage 的 bool/负数/缺键/非 dict 都视为 missing；provider started/terminal 不重复；`prepare_workspace` 拒绝 symlink/路径逃逸；artifact 缺失、目录、symlink 各有稳定状态；所有检查 stdout/stderr 只投影 UTF-8 字节数和 SHA-256，成功/失败都不保存正文；raw 递归键名不得出现 `goal,prompt,messages,reply,body,text,api_key,base_url,environment`。

- [x] **Step 2: 运行 Task 2 测试并确认 RED**

Run: `rtk uv run pytest -q tests/test_m23_mode_evaluation.py -k 'audit or usage or raw or workspace or artifact or external or acceptance'`

Expected: FAIL because Task 2 data models/functions do not exist；不调用真实模型。

- [x] **Step 3: 实现安全数据模型和 audit 投影**

在同一脚本中加入 frozen `StrictModel` 子类：

```python
class TokenTotals(StrictModel):
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    reasoning_tokens: int | None


class AuditMetrics(StrictModel):
    tokens: TokenTotals
    logical_model_calls: int = Field(ge=0)
    provider_attempts: int = Field(ge=0)
    usage_present_calls: int = Field(ge=0)
    usage_missing_calls: int = Field(ge=0)
    usage_missing_rate: float | None = Field(default=None, ge=0.0, le=1.0)


@dataclass(frozen=True)
class ModeResult:
    runtime_completed: bool
    runtime_status: str
    runtime_reason: str | None
    first_acceptance_passed: bool | None
    rejection_count: int | None
    correction_count: int | None


class CollectingAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> bool:
        self.events.append(event)
        return True
```

同时定义：`EnvironmentManifest` 的允许字段为 schema/generated_at/git_commit/tracked_dirty/python_version/python_executable_name/platform/package_version/model_id/provider_route_sha256/builtin_models_sha256/builtin_config_sha256/protocol_sha256/generation/execution；`CheckRecord` 为 id/status/exit_code/duration_ms/stdout_bytes/stderr_bytes/stdout_sha256/stderr_sha256；`ArtifactResult` 为 path/status/size/sha256；`RawRecord` 的字段与上方 `make_raw_record` 一一对应，所有 model 均 `extra="forbid"`。`RawRecord.schema` 固定默认 `forgeagent.m23.mode-evaluation.run/v1`；`CheckRecord.duration_ms` 和输出字节数默认 0，两个 SHA-256 必须是 64 位小写十六进制且即使输出为空也保存空字节摘要；`ArtifactResult` 非 `ok` 时 size/hash 为 null。

`project_audit_metrics` 只把 `event_type == "llm.outcome"` 计为 logical call；usage 必须是 dict 且四个字段均满足 `type(value) is int and value >= 0` 才 present。所有 present call 逐字段求和；有 call 但 present 为 0 时四项 token 都是 null；无 call 时四项为 0。provider attempts 只数 started 事件。

- [x] **Step 4: 实现环境清单、工作区、检查、artifact hash 与 raw 原子落盘**

`environment_manifest` 只记录允许字段：`schema`、UTC 生成时间、git commit、tracked dirty bool、`sys.version`、`sys.executable` 的 basename、`platform.system/release/machine`、安装包版本、model ID、内置 `models.yaml`/`config.yaml` SHA-256、固定 generation/execution 设置、protocol SHA-256 和 `provider_route_sha256`；禁止复制 `os.environ`、user registry、api key 或 base URL。preflight 用现有 `resolve_model()` 在内存得到 client kind/base URL，以 canonical `[model_id, client_kind, base_url or "provider-default"]` 计算 route hash，随后丢弃原值。`environment_sha256` 对 manifest 去掉 `generated_at` 后的 canonical JSON 计算，保证同一提交/环境的合法续跑稳定；若已有 `environment.json`，重新计算稳定字段并精确比较，保留第一次的 generated_at。

`prepare_workspace` 只能在已经存在且为空的临时目录写协议 `initial_files`；每一级目录用 `Path.resolve().is_relative_to(root.resolve())` 验证，不覆盖 symlink/目录。

`run_checks` 把协议首项 `{python}` 替换为 `sys.executable` 后构造：

```python
definition = CheckDefinition(
    id=check.id,
    argv=(sys.executable, *check.command[1:]),
    timeout_seconds=check.timeout_seconds,
)
result = run_check(definition, allowed_root=workspace)
```

成功、失败和 timeout 统一记录 `id/status/exit_code/duration_ms`、`len(stdout.encode("utf-8"))`、`len(stderr.encode("utf-8"))` 及两个 SHA-256；不保留任何输出正文。`hash_artifacts` 只接受普通非 symlink 文件，记录 relative path、size、SHA-256 或稳定 `missing/not_regular/symlink/io_error`。

`write_raw_record` 在目标目录创建同目录 `.<name>.<uuid>.tmp`，以 UTF-8 canonical JSON 写入、flush、`os.fsync` 后 `os.replace`，finally 删除残留 temp；目标若已存在只允许内容完全相同，否则报错，支持安全续跑。

- [x] **Step 5: 实现 Single 与 Duo/Triad 的公开 API 组装**

在脚本中保持下列调用合同：

```python
params = GenerationParams(**protocol.generation.model_dump())
identity = ApprovedIdentity(soul=None, user=None, project_agents=None, memory=None)

task = Task(
    client,
    tier="restricted",
    allowed_root=str(workspace),
    identity=identity,
    max_rounds=10,
    params=params,
    confirmer=lambda _request: True,
    audit_sink=audit_sink,
    task_id=stable_task_id,
)
outcome = task.run(task_spec.goal)
```

Single 返回 `runtime_completed=outcome.status.completed`、status/reason 和三个 null 验收字段。finally 必须依次 `task.close()`，然后对 client 的可调用 `close()` 做 best-effort 调用。

Duo/Triad 的 `role_task_builder(role, attempt, registry, system_prompt)` 必须为每次 role/attempt 创建 fresh real client 和 fresh Task，传入 runner 提供的 `system_prompt`/`tool_registry`，并返回一个本地 `_OwnedRoleTask`：其 `run()` 原样转发，`close()` 同时关闭 Task backend 和 client。创建 runner：

```python
runner = CollaborationRunner.create(
    mode=mode,
    goal=task_spec.goal,
    allowed_root=str(workspace),
    role_task_builder=role_task_builder,
    plan_confirmer=headless_plan_confirmer("preauthorize") if mode == "triad" else None,
    required_candidate_files=task_spec.required_candidate_files,
    execution_tier="restricted",
    collaboration_id=stable_collaboration_id,
    planner_model=protocol.model_id,
    generator_model=protocol.model_id,
    evaluator_model=protocol.model_id,
    evaluator_tier="restricted",
    max_rejections=2,
    audit_sink=audit_sink,
    task_id=stable_task_id,
    loop_id=None,
)
report = runner.run(task_spec.goal)
```

不得传 `evaluator_checks`。`first_acceptance_passed` 精确定义为 `report.status == "completed" and report.generator_attempts == 1 and report.evaluator_attempts == 1 and report.rejections == 0`；`rejection_count=report.rejections`；`correction_count=max(0, report.generator_attempts - 1)`。finally `runner.close()`；role task 已由 runner 逐次关闭。

- [x] **Step 6: 实现 execute_run 的错误收敛和 raw record**

计时从 workspace 完成后、调用 mode runner 之前开始，到外部 checks 与 artifact hash 完成后结束。任何普通异常映射为固定 `configuration_error/client_error/check_error/io_error/internal_error`，不得把 `str(exc)` 写入 raw；仍执行可以安全执行的 checks/hash 并写 terminal raw。`KeyboardInterrupt` 不吞掉，已完成 raw 保留。

raw 的稳定字段必须包含：schema/run ID/sequence/task ID/mode/repeat、protocol/environment/RunSpec hash、开始结束 UTC、runtime status/completed/reason、checks/artifacts、solved、验收循环三字段、四类 token、logical calls/provider attempts/usage present/missing/rate、end-to-end latency 和固定 error category。

- [x] **Step 7: 跑 Task 2 测试至 GREEN，再加真实 API 装配的 fake client 测试**

Run: `rtk uv run pytest -q tests/test_m23_mode_evaluation.py -k 'audit or usage or raw or workspace or artifact or external or acceptance or run_single or run_collaboration'`

Expected: PASS。

再用现有 `MockClient` 或最小 fake client 验证：Single 只建一个 Task；Duo 至少构造 Generator/Evaluator fresh client；Triad 构造 Planner/Generator/Evaluator；所有 client/backend 关闭；所有模式收到同一 params/model/root；协作不传 evaluator check。

- [x] **Step 8: 勾选 2.1–2.3 和 1.2 并提交 Task 2**

Run: `rtk uv run ruff format scripts/m23_mode_evaluation.py tests/test_m23_mode_evaluation.py && rtk uv run ruff check scripts/m23_mode_evaluation.py tests/test_m23_mode_evaluation.py`

Expected: 两条命令退出 0。随后勾选 OpenSpec `1.2`、`2.1`、`2.2`、`2.3`：

```bash
rtk git add scripts/m23_mode_evaluation.py tests/test_m23_mode_evaluation.py openspec/changes/m23-collaboration-mode-evaluation/tasks.md
rtk git commit -m "feat: record isolated M23 mode runs"
```

### Task 3: 从 raw 复算汇总与中立报告

**Files:**
- Modify: `scripts/m23_mode_evaluation.py`
- Modify: `tests/test_m23_mode_evaluation.py`
- Modify: `openspec/changes/m23-collaboration-mode-evaluation/tasks.md`

**Interfaces:**
- Produces: `read_raw_records(raw_dir: Path, protocol: EvaluationProtocol, protocol_sha256: str, environment_sha256: str) -> tuple[RawRecord, ...]`。
- Produces: `distribution(values: Sequence[int | float]) -> dict[str, int | float | None]` with `sum/mean/median/min/max`。
- Produces: `aggregate_records(protocol: EvaluationProtocol, schedule: Sequence[RunSpec], records: Sequence[RawRecord]) -> dict[str, object]`。
- Produces: `render_report(protocol: EvaluationProtocol, environment: Mapping[str, object], summary: Mapping[str, object]) -> str`、`write_aggregate_outputs(output_dir: Path, summary: Mapping[str, object], report: str) -> None`。
- Consumes: 只接受 Task 2 `RawRecord` schema；禁止读取 workspace、audit events、model outputs 或 collaboration state。

- [x] **Step 1: 写完整性、聚合分母、N/A 与中立性 RED 测试**

在唯一测试文件中加入 helper 生成 27 个最小有效 raw records，然后覆盖：

```python
def test_aggregate_uses_exact_denominators_and_single_na() -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)
    records = make_complete_records(harness, schedule, digest)
    summary = harness.aggregate_records(protocol, schedule, records)

    for mode in ("single", "duo", "triad"):
        assert summary["modes"][mode]["scheduled_runs"] == 9
        assert summary["modes"][mode]["task_completion_rate"]["denominator"] == 9
    assert summary["modes"]["single"]["first_acceptance_rate"] is None
    assert summary["modes"]["single"]["rejections"] is None
    assert summary["modes"]["single"]["corrections"] is None
    assert summary["modes"]["duo"]["first_acceptance_rate"]["denominator"] == 9
    assert summary["modes"]["triad"]["first_acceptance_rate"]["denominator"] == 9


def test_aggregate_rejects_missing_duplicate_or_mixed_records() -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)
    records = make_complete_records(harness, schedule, digest)
    with pytest.raises(ValueError, match="complete 27"):
        harness.aggregate_records(protocol, schedule, records[:-1])
    with pytest.raises(ValueError, match="duplicate"):
        harness.aggregate_records(protocol, schedule, (*records[:-1], records[0], records[0]))
    mixed = records[0].model_copy(update={"protocol_sha256": "f" * 64})
    with pytest.raises(ValueError, match="protocol"):
        harness.aggregate_records(protocol, schedule, (mixed, *records[1:]))


def test_report_is_descriptive_and_contains_no_ranking_contract() -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)
    records = make_complete_records(harness, schedule, digest)
    summary = harness.aggregate_records(protocol, schedule, records)
    report = harness.render_report(
        protocol,
        {"schema": "forgeagent.m23.environment/v1", "model_id": protocol.model_id},
        summary,
    )
    lowered = report.lower()
    assert "不自动宣称 triad 优于 single" in lowered
    assert "小样本" in report
    assert "n/a" in report
    for forbidden in ("winner", "rank", "recommendation", "superiority"):
        assert forbidden not in lowered
```

在测试文件定义完整 helper：

```python
def make_complete_records(harness, schedule, protocol_sha256: str):
    return tuple(
        make_raw_record(harness, spec, protocol_sha256, solved=spec.sequence % 4 != 0)
        for spec in schedule
    )
```

再覆盖：task completion 以 `solved` 为准而非 runtime completed；usage missing 以 calls 为加权分母而非 run 平均；token 只汇总非 null 值且并列 missing calls；四类 token/model calls/provider attempts/latency/rejection/correction 均有 sum/mean/median/min/max；逐 task/mode 样本恰为 3；同一 raw 集两次聚合的 metrics 相等。

- [x] **Step 2: 运行聚合测试并确认 RED**

Run: `rtk uv run pytest -q tests/test_m23_mode_evaluation.py -k 'aggregate or report or denominator or ranking or complete'`

Expected: FAIL because aggregate/report functions are absent。

- [x] **Step 3: 实现严格 raw 加载与完整性检查**

`read_raw_records` 只读取 `raw/*.json` 普通非 symlink 文件，逐个 `RawRecord.model_validate`。必须证明：文件数 27；(task, repeat, mode) 与 schedule 一一对应；sequence/run_spec_hash/protocol hash/environment hash 一致；schema 唯一；没有缺失、多余或重复组合；不提供不完整聚合路径。

- [x] **Step 4: 实现指标聚合**

先计算：

```python
logical_call_total = sum(record.logical_model_calls for record in mode_records)
missing_call_total = sum(record.usage_missing_calls for record in mode_records)


def known_token_values(field: str) -> list[int]:
    return [
        value
        for record in mode_records
        if (value := getattr(record.tokens, field)) is not None
    ]
```

每个 mode 生成下列稳定键：

```python
{
    "scheduled_runs": 9,
    "task_completion_rate": {"numerator": solved, "denominator": 9, "value": solved / 9},
    "first_acceptance_rate": None,  # Single；协作模式为 numerator/denominator/value
    "rejections": None,             # Single；协作模式为 distribution
    "corrections": None,
    "tokens": {
        "input_tokens": distribution(known_token_values("input_tokens")),
        "output_tokens": distribution(known_token_values("output_tokens")),
        "cached_tokens": distribution(known_token_values("cached_tokens")),
        "reasoning_tokens": distribution(known_token_values("reasoning_tokens")),
        "usage_missing_calls": sum(record.usage_missing_calls for record in mode_records),
    },
    "logical_model_calls": distribution(
        [record.logical_model_calls for record in mode_records]
    ),
    "provider_attempts": distribution([record.provider_attempts for record in mode_records]),
    "end_to_end_latency_seconds": distribution(
        [record.end_to_end_latency_seconds for record in mode_records]
    ),
    "usage_missing_rate": {
        "numerator": missing_call_total,
        "denominator": logical_call_total,
        "value": (
            None if logical_call_total == 0 else missing_call_total / logical_call_total
        ),
    },
}
```

`distribution([])` 返回五项 null，绝不伪造 0。summary 的 `schema` 固定为 `forgeagent.m23.mode-evaluation.summary/v1`，顶层只允许 `schema/protocol_sha256/environment_sha256/generated_at/completeness/modes/tasks/failures/usage_missing_runs/limitations`；不得加入比较、排行或推荐字段。

- [x] **Step 5: 实现中立 Markdown 与幂等输出**

报告固定章节为：协议、环境、证据完整性、按模式指标、按任务指标、失败/usage 缺失清单、限制。每个 rate 同时显示 numerator/denominator；Single 验收循环显示 `N/A`。末尾逐字包含：

```text
这些结果来自固定协议下的小样本描述性评估；本报告不自动宣称 Triad 优于 Single，也不据此作产品决策。
```

`write_aggregate_outputs` 使用与 raw 相同的同目录原子替换；重复执行内容的 metric 部分必须相同，只有明确的 `generated_at` 可以变化，测试比较时排除该字段。

- [x] **Step 6: 运行 Task 3 全部离线合同至 GREEN**

Run: `rtk uv run pytest -q tests/test_m23_mode_evaluation.py`

Expected: 全部 PASS，且不会访问网络或读取用户 credential。

- [x] **Step 7: 勾选 2.4 并提交 Task 3**

```bash
rtk uv run ruff format scripts/m23_mode_evaluation.py tests/test_m23_mode_evaluation.py
rtk uv run ruff check scripts/m23_mode_evaluation.py tests/test_m23_mode_evaluation.py
rtk git add scripts/m23_mode_evaluation.py tests/test_m23_mode_evaluation.py openspec/changes/m23-collaboration-mode-evaluation/tasks.md
rtk git commit -m "feat: aggregate neutral M23 evidence"
```

Expected: format/check 退出 0，commit 只包含上列文件。

### Task 4: CLI、preflight 与 27 次真实模型证据

**Files:**
- Modify: `scripts/m23_mode_evaluation.py`
- Modify: `tests/test_m23_mode_evaluation.py`
- Generate: `docs/evaluation/m23/runs/2026-07-27-haiku-4-5/environment.json`
- Generate: `docs/evaluation/m23/runs/2026-07-27-haiku-4-5/raw/*.json`
- Generate: `docs/evaluation/m23/runs/2026-07-27-haiku-4-5/summary.json`
- Generate: `docs/evaluation/m23/runs/2026-07-27-haiku-4-5/report.md`
- Modify: `openspec/changes/m23-collaboration-mode-evaluation/tasks.md`

**Interfaces:**
- Produces: local `ClientBuilder` Protocol (`__call__(model_id: str, *, registry: Registry) -> ModelClient`) and frozen `PreflightContext(registry: Registry, environment: EnvironmentManifest, environment_sha256: str)`。
- Produces: `preflight(protocol: EvaluationProtocol, protocol_sha256: str, output_dir: Path, *, allowed_output_root: Path, registry_loader: Callable[[], Registry] = load_registry, client_builder: ClientBuilder = build_real_client) -> PreflightContext`。
- Produces resume helper: `pending_run_specs(output_dir: Path, schedule: Sequence[RunSpec], protocol_sha256: str, environment_sha256: str) -> tuple[RunSpec, ...]`。
- Produces: `run_command(protocol_path: Path, output_dir: Path, *, allowed_output_root: Path | None = None) -> int`、`aggregate_command(protocol_path: Path, output_dir: Path) -> int`、`main(argv: Sequence[str] | None = None) -> int`。
- CLI exact forms: `run --protocol PATH --output DIR` and `aggregate --protocol PATH --output DIR`；无 model/param/task/repetition/incomplete override。

- [x] **Step 1: 写 CLI/preflight/resume RED 测试**

追加测试：

```python
def test_parser_exposes_only_fixed_run_and_aggregate_inputs() -> None:
    harness = load_harness()
    parser = harness.build_parser()
    run_args = parser.parse_args(["run", "--protocol", str(PROTOCOL_PATH), "--output", "/tmp/m23"])
    assert run_args.command == "run"
    aggregate_args = parser.parse_args([
        "aggregate", "--protocol", str(PROTOCOL_PATH), "--output", "/tmp/m23",
    ])
    assert aggregate_args.command == "aggregate"
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--model", "other", "--protocol", str(PROTOCOL_PATH), "--output", "/tmp/m23"])


def test_preflight_fails_before_schedule_when_model_or_output_mismatches(tmp_path) -> None:
    harness = load_harness()
    calls: list[str] = []
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)

    def failing_builder(model_id: str, *, registry):
        calls.append(model_id)
        raise ValueError("model capability mismatch")

    with pytest.raises(ValueError, match="model capability"):
        harness.preflight(
            protocol,
            digest,
            tmp_path / "output",
            allowed_output_root=tmp_path,
            registry_loader=harness.load_registry,
            client_builder=failing_builder,
        )
    assert calls == ["claude-haiku-4-5"]


def test_resume_skips_only_exact_matching_raw_record(tmp_path) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)
    first = make_raw_record(harness, schedule[0], digest)
    target = tmp_path / "raw" / f"{first.run_id}.json"
    harness.write_raw_record(target, first)

    pending = harness.pending_run_specs(tmp_path, schedule, digest, "b" * 64)
    assert [spec.sequence for spec in pending] == list(range(2, 28))

    value = json.loads(target.read_text(encoding="utf-8"))
    value["run_spec_sha256"] = "f" * 64
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="run spec"):
        harness.pending_run_specs(tmp_path, schedule, digest, "b" * 64)
```

另覆盖：输出目录 symlink/协议 hash 混用失败；preflight 不把 key/base URL 写入 manifest/异常输出；单次执行异常仍写 raw 并继续；KeyboardInterrupt 不删除既有 raw；aggregate 缺 1 份退出 2；完整 run 结束自动 aggregate。

- [x] **Step 2: 运行 CLI 测试并确认 RED**

Run: `rtk uv run pytest -q tests/test_m23_mode_evaluation.py -k 'parser or preflight or resume or command'`

Expected: FAIL because CLI/preflight orchestration is absent；不得发出网络请求。

- [x] **Step 3: 实现两子命令与安全 preflight**

`preflight` 的严格顺序：加载并校验协议 → 验证 output 不为 symlink 且位于仓库 `docs/evaluation/m23/runs/`（测试可显式注入临时允许根）→ `load_registry()` 获取一次 snapshot → 校验 model/capability/4096 上限/固定 settings → 调用一次 `build_real_client(model_id, registry=snapshot)` 仅验证 credential 可解析并立即 close → 建 environment manifest/hash → 在首个 model call 前原子写 `environment.json`。错误输出只使用固定类别和字段名，不打印 `ResolvedModel` 或 exception repr。

`run_command` 串行遍历 `build_schedule`；每次 `tempfile.TemporaryDirectory(prefix="forgeagent-m23-", dir="/tmp")` 创建全新 workspace。raw 文件名固定为 `{sequence:02d}-{task_id}-r{repeat}-{mode}.json`。若已有 raw 的 schema/hash/RunSpec 完全匹配则打印 bounded `SKIP sequence=N`；否则拒绝覆盖。单次失败记录后继续，全部 27 terminal raw 写完后调用正式 aggregate。

`main` 捕获预检/持久化/完整性错误并返回 2；完整证据生成返回 0。模式质量失败是评估数据，不改变 harness exit code；未生成 terminal raw 才是 harness 失败。

- [x] **Step 4: 运行全部离线测试至 GREEN**

```bash
rtk uv run pytest -q tests/test_m23_mode_evaluation.py
rtk uv run ruff format --check scripts/m23_mode_evaluation.py tests/test_m23_mode_evaluation.py
rtk uv run ruff check scripts/m23_mode_evaluation.py tests/test_m23_mode_evaluation.py
```

Expected: 全部退出 0。

- [x] **Step 5: 执行正式 27 次真实模型评估**

先确认当前实现已提交，保证环境 manifest 的 commit 稳定。然后运行：

```bash
UV_CACHE_DIR=/tmp/forgeagent-m23-uv-cache rtk uv run python scripts/m23_mode_evaluation.py run \
  --protocol docs/evaluation/m23/protocol.json \
  --output docs/evaluation/m23/runs/2026-07-27-haiku-4-5
```

Expected: preflight 成功；按固定顺序串行产生 27 个 terminal raw；命令退出 0 并生成 `environment.json`、`summary.json`、`report.md`。不要预设 solved 数、first acceptance、token、调用次数或延迟结果。

若网络/credential 暂时失败且代码/提交/协议/环境指纹未变，保留已有一致 raw 后用原命令续跑；不得改协议、模型或减少重复次数来绕过失败。若失败来自 harness bug，先用离线 RED 回归复现、修复、跑全测试并提交；新提交会改变环境指纹，因此把旧 output 原子移动到同级 `2026-07-27-haiku-4-5-invalid-<old-commit-prefix>` 保留审计痕迹，再从空的正式 output 目录完整重跑 27 次，禁止混合新旧提交证据。

- [x] **Step 6: 独立复算并核对证据合同**

```bash
UV_CACHE_DIR=/tmp/forgeagent-m23-uv-cache rtk uv run python scripts/m23_mode_evaluation.py aggregate \
  --protocol docs/evaluation/m23/protocol.json \
  --output docs/evaluation/m23/runs/2026-07-27-haiku-4-5
rtk uv run pytest -q tests/test_m23_mode_evaluation.py
```

Expected: aggregate 退出 0；raw 恰为 27 份、每模式 9 份、每 task/mode 3 份；协议 hash 和环境 hash 各唯一；summary 可从 raw 重算；report 与 summary 分母一致；报告保留失败与 usage 缺失，不含 prompt/reply/credential/自动优劣结论。

- [x] **Step 7: 两轮证据自审并修复发现**

第一轮从“公平性/统计口径”审查：同一模型、参数、任务、检查、重复数、轮换顺序是否真的适用于所有模式；Single N/A 是否保持 null；completion 是否使用 runtime+external 双条件；usage 缺失是否按 call 加权。

第二轮从“安全性/可复现性”审查：raw/manifest/report 是否存在敏感值、绝对路径、正文、混合 hash、未知 token 归零、重复/缺失样本或非原子写；汇总是否暗含排名/推荐。

任何发现必须先加入 `tests/test_m23_mode_evaluation.py` 的失败回归，再修复脚本、重跑 Task 4 Step 4 和 Step 6；如果修复改变协议 hash 或指标口径，删除/重跑证据前必须明确确认旧证据不可混用，不能静默覆盖。

- [x] **Step 8: 勾选 3.1–3.3 并提交真实证据**

仅在完整核对通过后勾选 OpenSpec `3.1`、`3.2`、`3.3`：

```bash
rtk git add scripts/m23_mode_evaluation.py tests/test_m23_mode_evaluation.py docs/evaluation/m23/runs/2026-07-27-haiku-4-5 openspec/changes/m23-collaboration-mode-evaluation/tasks.md
rtk git commit -m "test: record M23 mode evaluation evidence"
```

### Task 5: README/ACTION_PLAN/M23 里程碑与完成门禁

**Files:**
- Modify: `tests/test_m23_mode_evaluation.py`
- Modify: `tests/test_collaboration_docs.py` (one historical-pointer assertion only)
- Modify: `README.md`
- Modify: `ACTION_PLAN.md`
- Create: `milestones/milestone_023.md`
- Modify: `milestones/latest`
- Modify: `openspec/changes/m23-collaboration-mode-evaluation/tasks.md`

**Interfaces:**
- Documents only the already generated protocol/evidence；不新增运行时行为或易变测试数字长期合同。
- 新增的 M23 测试文件拥有当前文档/latest 指针合同；既有 `tests/test_collaboration_docs.py` 只移除已失效的 M22 latest 断言，其他 M22 历史证据合同保持原样。

- [x] **Step 1: 写 M23 文档 RED 合同**

在 `tests/test_m23_mode_evaluation.py` 增加：

```python
import subprocess


def test_m23_public_docs_link_fixed_protocol_and_neutral_evidence() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    action_plan = (ROOT / "ACTION_PLAN.md").read_text(encoding="utf-8")
    milestone = (ROOT / "milestones" / "milestone_023.md").read_text(encoding="utf-8")

    for text in (readme, action_plan, milestone):
        assert "docs/evaluation/m23/protocol.json" in text
        assert "2026-07-27-haiku-4-5/report.md" in text
        assert "不自动宣称 Triad 优于 Single" in text
    assert "| **M23**" in action_plan
    assert "已完成" in next(
        line for line in action_plan.splitlines() if line.startswith("| **M23**")
    )
    assert (ROOT / "milestones" / "latest").read_text().strip() == "milestone_023.md"


def test_m23_does_not_modify_product_runtime_or_dependencies() -> None:
    protected = (
        "src/forgeagent/collaboration.py",
        "src/forgeagent/cli.py",
        "src/forgeagent/model_registry.py",
        "pyproject.toml",
        "uv.lock",
    )
    for path in protected:
        before = subprocess.run(
            ["git", "show", f"f6e0dda3c8a7f9c73400c240c0a999e20b12bbd6:{path}"],
            check=True, capture_output=True,
        ).stdout
        assert (ROOT / path).read_bytes() == before
```

Run: `rtk uv run pytest -q tests/test_m23_mode_evaluation.py -k 'public_docs or product_runtime'`

Expected: documentation test FAIL because M23 docs/milestone are not yet updated；protected file test PASS。

同时在 `tests/test_collaboration_docs.py::test_m22_closeout_artifacts_record_final_gates` 只删除：

```python
assert _text("milestones/latest").strip() == "milestone_022.md"
```

该断言把 evolving current pointer 错误归入 M22 历史合同；M22 的 `2155 passed / 10 skipped`、结构化提交、报告和 milestone 内容断言全部保持不变，当前 latest 指针由上面的 M23 测试接管。

- [x] **Step 2: 更新 README 与 ACTION_PLAN**

README 新增 M23 独立评估段，链接 protocol、summary、report，列出 7 类要求指标和 3×3×3 样本设计；填入 report 的真实描述性数字，不挑选只支持某模式的样本。逐字保留“不自动宣称 Triad 优于 Single”，并注明真实请求会产生成本、harness 不属于产品 CLI/CI。

ACTION_PLAN 里程碑表新增 `**M23**` 行：交付物写固定协议/27 raw/机器汇总/中立报告；验证列引用实际文件和真实完整性计数；状态在全部门禁前写“进行中”，全部完成后改“已完成，待归档”，由后续 `comet-archive` 阶段再同步为“已完成并归档”。不要修改 M22 历史测试数字或证据。

- [x] **Step 3: 创建 M23 里程碑并更新 latest**

严格按 `MILESTONE_GUIDE.md` 固定章节创建 `milestones/milestone_023.md`，至少包含：

- 目标/范围：独立评估层，不含 credential 功能，不修改协作运行时。
- 方案：固定协议、平衡顺序、外部检查、raw-first 聚合、Single N/A、中立结论。
- 交付物：脚本、唯一测试、protocol、environment/raw/summary/report、OpenSpec change。
- 三次评审：技术方案、代码/两轮自审、验收；只记录已经执行的真实证据。
- 遗留问题：小样本、单一任务族/模型/平台、provider 波动和 usage 缺失的实际情况；不能据此作产品结论。
- 续接指引：M24 候选仅作下一步，不把 credential 功能塞回 M23。

把 `milestones/latest` 改成唯一一行 `milestone_023.md`。

- [x] **Step 4: 文档测试 GREEN 并完成全部质量门禁**

按顺序执行并记录精确输出：

```bash
rtk uv run pytest -q tests/test_m23_mode_evaluation.py
rtk uv run ruff format --check scripts tests
rtk uv run ruff check scripts tests
rtk uv run pytest -q
rtk uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-m23-golden-offline
rtk uv build --out-dir /tmp/forgeagent-m23-build
rtk openspec validate m23-collaboration-mode-evaluation --strict
rtk openspec validate --all --strict
rtk git diff --check
```

Expected: 所有命令退出 0；全量 pytest/golden/OpenSpec 的实际计数写入 milestone/ACTION_PLAN 时只作为本次证据，不改写历史 M22 数字，也不把易变 pytest 数定义为 README 长期产品合同。

- [x] **Step 5: 完成最终两轮自我评审并修复复验**

先按仓库完成门使用 `requesting-code-review` 对 `base-ref..HEAD` 全 diff 做独立代码评审，重点检查 raw 安全边界、统计分母、资源关闭和 runtime/credential 零改动；Critical/Important finding 必须先加 RED 回归再修复。

第一轮逐条对照 delta spec 的 7 个 Requirement/全部 Scenario、design doc §1–§8 和 OpenSpec tasks；给每条要求指出一个实现路径、一个测试和一份真实证据，缺任何一项都不得勾选完成。

第二轮检查前后不一致与遗漏：指标字段命名/分母是否一致；27 raw 与 summary/report 是否一致；文档是否错误把内部 completed 当 solved；是否误把 Single N/A 写 0；是否出现 credential/运行时/CLI 改动；是否出现 Triad 排名、winner 或暗示性推荐；README/ACTION_PLAN/milestone 链接是否存在。

发现问题时立即加入 RED 回归、最小修复、重跑 focused test 和 Step 4 全门禁；在所有发现关闭后才更新 OpenSpec tasks `4.1`、`4.2`、`4.3` 和未勾选项。

- [x] **Step 6: 提交收尾文档**

```bash
rtk git add README.md ACTION_PLAN.md milestones/milestone_023.md milestones/latest tests/test_m23_mode_evaluation.py tests/test_collaboration_docs.py openspec/changes/m23-collaboration-mode-evaluation/tasks.md
rtk git commit -m "docs: complete M23 mode evaluation"
```

Expected: commit 不包含受保护 runtime/CLI/credential 文件或用户未跟踪文件。

- [x] **Step 7: Comet verify 与归档前最终状态核对**

Run: `rtk comet status --json`

Expected: change `m23-collaboration-mode-evaluation` 的 proposal/design/specs/tasks 完整，tasks 全勾选。按 Comet verify 流程复查实现/证据/规格一致性；归档前再次运行 `rtk openspec validate m23-collaboration-mode-evaluation --strict` 和 `rtk git diff --check`。归档动作由 `comet-archive` 阶段完成，不在实现步骤中手工绕过 Comet。
