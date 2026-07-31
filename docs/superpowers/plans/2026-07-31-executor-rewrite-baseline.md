---
change: measure-executor-rewrite-baseline
design-doc: docs/superpowers/specs/2026-07-31-executor-rewrite-baseline-design.md
base-ref: a14630ff8a730b98839289785e365bda0519381a
archived-with: 2026-07-31-measure-executor-rewrite-baseline
---

# M43 Executor Rewrite Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用标准库离线测量器建立 Python 执行路径六项 Rewrite/Dependency 基线，并在不修改运行时、不新增依赖的前提下给出可复现 readiness verdict。

**Architecture:** 单一 `scripts/m43_executor_rewrite_baseline.py` 通过现有 backend API 采集聚合性能、故障恢复、结构和兼容证据，并用纯函数执行三态 verdict。版本化 JSON 保存原始证据，Markdown 负责解释阈值和平台边界；pytest 只断言确定性契约，不把本机毫秒数做成 CI 硬门禁。

**Tech Stack:** Python 3.11+、stdlib `argparse`/`ast`/`json`/`statistics`/`subprocess`/`tempfile`/`tomllib`、现有 ForgeAgent API、pytest、Ruff、uv；不新增依赖。

## Global Constraints

- M43 不修改 `src/forgeagent/executor.py`、`_sandbox_worker.py`、Runtime、CLI、配置、worker frame 或运行时依赖。
- 报告只允许 Python version、platform、machine、短 commit；禁止绝对路径、环境值、代码正文、raw exception、stdout/stderr 和主机名。
- backend evidence 状态只允许 `measured`、`not_available`、`failed`；Docker 不可用不得算通过，脚本不得拉镜像或访问网络。
- 性能阈值在首次正式测量前固定：trusted median `1.0 ms`；restricted median `250.0 ms` 或 throughput `4.0 ops/s`；越阈仍需同机干净复测和真实需求才算 confirmed bottleneck。
- future eligibility 必须同时满足六项证据完整、confirmed bottleneck、compatibility/team/rollback ready；否则保持 Python 或记为证据不足。
- 不执行 PyPI、tag 或发布自动化。普通分支 push 仅是已授权的版本控制交接。
- 主工作区存在 M43 前改动；每次提交只暂存本计划列出的 M43 文件。

---

### Task 1: 固化报告与 readiness 纯契约

**Files:**
- Create: `tests/test_m43_executor_rewrite_baseline.py`
- Create: `scripts/m43_executor_rewrite_baseline.py`
- Modify: `openspec/changes/measure-executor-rewrite-baseline/tasks.md`

**Interfaces:**
- Produces: `REPORT_SCHEMA`, `METRIC_NAMES`, `summarize_samples(samples_ms)`, `evaluate_readiness(metrics)`。
- `evaluate_readiness` consumes six metric dicts with `baseline/threshold/evidence/migration/rollback_trigger/status` and returns one of three fixed verdicts.

- [x] **Step 1: 写 schema 和 sample summary RED 测试**

  通过 `importlib.util.spec_from_file_location` 导入脚本，断言 `METRIC_NAMES` 精确为六项；`summarize_samples([1.0, 2.0, 3.0, 4.0])` 返回 count、samples、median、p95、min、max、ops_per_second，空列表抛 `ValueError("samples_required")`。

- [x] **Step 2: 运行 RED 并核对失败原因**

  Run: `rtk uv run pytest -q tests/test_m43_executor_rewrite_baseline.py`

  Expected: FAIL，因为脚本尚不存在；不得因测试导入路径或语法失败。

- [x] **Step 3: 实现最小常量与聚合函数**

  使用 `statistics.median`，p95 采用排序后 `ceil(0.95 * n) - 1` 的 nearest-rank，ops/s 为 `1000 * count / sum(samples_ms)`；数值统一 round 到 6 位但保留 samples。

- [x] **Step 4: 写三个 verdict RED 测试**

  使用固定 helper 生成六项五字段：无 confirmed bottleneck → `keep_python`；bottleneck 且三项 feasibility ready → `eligible_for_single_module_experiment`；缺字段、required `failed` 或 bottleneck 后 team not ready → `insufficient_evidence`。

- [x] **Step 5: 实现最小 `evaluate_readiness` 并跑 GREEN**

  先验证 metric key 与五字段集合，再按 design 第 5 节顺序判定；不引入 class hierarchy 或通用 rules engine。

  Run: `rtk uv run pytest -q tests/test_m43_executor_rewrite_baseline.py`

  Expected: PASS。

- [x] **Step 6: 勾选 OpenSpec 1.1 并提交**

  Commit: `test: define M43 rewrite readiness contract`

### Task 2: 实现真实 backend 测量与安全报告

**Files:**
- Modify: `tests/test_m43_executor_rewrite_baseline.py`
- Modify: `scripts/m43_executor_rewrite_baseline.py`
- Modify: `openspec/changes/measure-executor-rewrite-baseline/tasks.md`

**Interfaces:**
- Produces: `build_report(*, samples: int, reliability_runs: int) -> dict[str, object]`、`write_report(path, report)`、`main(argv=None) -> int`。
- Internal backend records use fixed statuses and never expose caught exception text.

- [x] **Step 1: 写报告完整性、脱敏和原子写 RED 测试**

  monkeypatch backend measurements 为固定值，断言顶层 schema/environment/metrics/verdict，六项均含五字段和 status；向 fake failure 注入 `SECRET_VALUE` 与绝对 temp path，序列化报告不得包含二者；替换 `os.replace` 抛错时旧 output 内容不变且临时文件被清理。

- [x] **Step 2: 写 backend 三态和 verdict 集成 RED 测试**

  container unavailable 返回 `{status: "not_available", reason: "container_unavailable"}`；required trusted/restricted failure 使 verdict 为 `insufficient_evidence`；unavailable container 不得被写成 `measured` 或 `passed`。

- [x] **Step 3: 运行 RED**

  Run: `rtk uv run pytest -q tests/test_m43_executor_rewrite_baseline.py`

  Expected: FAIL，因为 build/write/backend measurement 尚未实现。

- [x] **Step 4: 实现性能、可靠性、维护与兼容采集**

  trusted/restricted 对同一 trivial block warmup 后计时；restricted 用独立 backend 做 20 次正常执行、`os._exit(7)` 后恢复和 `1.0s` timeout 后恢复。维护统计只读取 `src/forgeagent/executor.py`、`_sandbox_worker.py`、`runtime.py` 与 `pyproject.toml`，只输出相对标识。兼容基线记录 `ExecResult` 字段和 state roundtrip 结果。

- [x] **Step 5: 实现 container 条件测量、固定 failure code 与报告写入**

  只调用本地 `docker info` 和 `docker image inspect python:3.11-slim`；任何不可用或异常映射为固定 reason。可用时最少运行正常与异常后恢复并关闭 backend。写入使用同目录 `NamedTemporaryFile(delete=False)`、flush/fsync/replace。

- [x] **Step 6: 跑 GREEN 与现有 executor 安全专项**

  Run: `rtk uv run pytest -q tests/test_m43_executor_rewrite_baseline.py tests/test_executor.py tests/test_restricted_backend.py tests/test_container_backend.py tests/test_escape.py tests/test_policy_wiring.py`

  Expected: 全部 PASS；Docker 场景可按既有 marker skip，但 M43 单元测试不得 skip。

- [x] **Step 7: Ruff 并提交**

  Run: `rtk uv run ruff check scripts/m43_executor_rewrite_baseline.py tests/test_m43_executor_rewrite_baseline.py`

  Commit: `feat: measure executor rewrite readiness`

### Task 3: 生成基线、锁定文档契约并形成 verdict

**Files:**
- Modify: `tests/test_m43_executor_rewrite_baseline.py`
- Create: `docs/evaluation/m43/executor-rewrite-baseline.json`
- Create: `docs/evaluation/m43/rewrite-dependency-baseline.md`
- Modify: `openspec/changes/measure-executor-rewrite-baseline/tasks.md`

**Interfaces:**
- Consumes: Task 2 CLI output and fixed thresholds.
- Produces: frozen JSON evidence plus a six-row Markdown governance table.

- [x] **Step 1: 写文档契约 RED 测试**

  断言 JSON schema、六项 key、五字段、合法 verdict；Markdown 对每项恰有一行且包含 baseline/threshold/evidence/migration/rollback trigger、复现命令、Docker 边界、同机复测规则和“不授权重写/依赖”结论。

- [x] **Step 2: 运行 RED**

  Run: `rtk uv run pytest -q tests/test_m43_executor_rewrite_baseline.py`

  Expected: FAIL，因为 evidence 和 Markdown 尚不存在。

- [x] **Step 3: 运行正式测量两次**

  Run: `rtk uv run python scripts/m43_executor_rewrite_baseline.py --output docs/evaluation/m43/executor-rewrite-baseline.json`

  Run: 第二次输出到临时 evidence，比较同机阈值结论；若首轮越阈，第二轮必须同样越阈且绑定真实需求才可设置 confirmed bottleneck。不得改阈值迎合结果。

- [x] **Step 4: 写六项基线文档和最终 verdict**

  表格逐项记录五字段、真实数值/状态、evidence 路径、未来 migration 和 rollback trigger。container 未运行时写未验证；team capability 未演练时写 not ready。结论严格来自 JSON evaluator。

- [x] **Step 5: 跑 GREEN 并提交**

  Run: `rtk uv run pytest -q tests/test_m43_executor_rewrite_baseline.py`

  Commit: `docs: record M43 executor rewrite baseline`

### Task 4: 同步规划、评审、验证和里程碑

**Files:**
- Modify: `ACTION_PLAN.md`
- Modify: `docs/reviews/2026-07-30-agent开发指南评审-借鉴清单.md`
- Modify: `docs/reviews/2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md`
- Create: `docs/superpowers/reports/2026-07-31-executor-rewrite-baseline-verify.md`
- Create: `milestones/milestone_043.md`
- Modify: `milestones/latest`
- Modify: `openspec/changes/measure-executor-rewrite-baseline/tasks.md`

**Interfaces:**
- Consumes: frozen evidence、focused/full verification and base-ref diff.
- Produces: M43 completion ledger, continuation guidance and archive-ready tasks.

- [x] **Step 1: 同步 M43 规划与借鉴清单**

  将 M43 写为“测量完成，不等于 rewrite 获批”；记录当前 verdict、触发未来独立试验所缺证据，并保留 PyPI/tag/发布自动化移除边界。不要改写 M41/M42 历史数值。

- [x] **Step 2: 做两轮最终自审并修复**

  第一轮核对 schema、阈值先验性、fault recovery、secret/path 禁入和 verdict；第二轮核对 YAGNI、无运行时/依赖变化、工作区文件归因、OpenSpec/design/tasks/docs 前后一致。每个发现先补 RED 回归再修复，并重跑受影响专项。

- [x] **Step 3: 完成 standard review gate**

  使用 requesting-code-review 技能对 `base-ref..HEAD` 和未提交 M43 文件做正确性、安全、边界审查；当前平台禁止子代理时，以 fresh diff 自审记录替代，并如实写入验证报告。

- [x] **Step 4: 运行完整门禁**

  Run: `rtk uv run pytest -q`

  Run: `rtk uv run ruff check .`

  Run: `rtk uv run ruff format --check .`

  Run: `rtk git diff --check`

  Run: `rtk openspec validate --all --strict`

  Expected: pytest/Ruff/format/diff/OpenSpec 全部通过；skip 和 Docker/Linux 未验证边界原样记录。

- [x] **Step 5: 写验证报告、M43 milestone 并完成提交**

  验证报告记录基线与最终测试数、两次测量、六项 status、verdict、既有工作区差异和发布边界。里程碑按 `MILESTONE_GUIDE.md` 更新并将 `milestones/latest` 指向 043。

  Commit: `docs: complete M43 rewrite baseline milestone`
