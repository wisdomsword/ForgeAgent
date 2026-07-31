---
comet_change: measure-executor-rewrite-baseline
role: technical-design
canonical_spec: openspec
---

# M43 Executor Rewrite Baseline 技术设计

## 1. 设计目标

M43 把 M32 的六项 Rewrite/Dependency 治理要求落到 ForgeAgent Python 执行路径的真实证据上。交付物回答两个问题：当前 trusted/restricted/container 执行路径是否存在已测量瓶颈；证据是否足以允许未来建立单模块、可回滚的替换试验。M43 本身不改变任何执行行为。

## 2. 现状边界

`TrustedBackend` 在宿主进程的持久 namespace 中编译并执行代码。`RestrictedBackend` 每个 block 通过 `python -I -m forgeagent._sandbox_worker` 启动新进程，以 JSON 传递代码、状态和限制，并由父进程 timeout 杀死失控 worker。`ContainerBackend` 复用同一 worker protocol，但额外承担 Docker daemon、镜像和一次性 container 开销。

测量入口不得读取 provider 配置、凭据、模型 prompt 或 Memory，不访问网络，不修改 `executor.py`、worker、运行时配置或依赖。报告不包含绝对路径、环境值、执行代码、raw exception、stdout/stderr 或主机名。

## 3. 文件与职责

### 3.1 `scripts/m43_executor_rewrite_baseline.py`

唯一测量入口，使用标准库和现有 `forgeagent` API。公开内部接口如下：

```python
REPORT_SCHEMA = "forgeagent.executor-rewrite-baseline.v1"
METRIC_NAMES = (
    "performance",
    "reliability",
    "maintenance_cost",
    "compatibility",
    "team_capability",
    "migration_rollback_risk",
)

def summarize_samples(samples_ms: list[float]) -> dict[str, object]: ...
def evaluate_readiness(metrics: dict[str, dict[str, object]]) -> str: ...
def build_report(*, samples: int, reliability_runs: int) -> dict[str, object]: ...
def write_report(path: Path, report: dict[str, object]) -> None: ...
```

命令行只提供 `--output`、`--samples` 和 `--reliability-runs`。默认 `samples=15`、`reliability-runs=20`；输入必须为有界正整数。输出文件使用同目录临时文件、flush、`os.fsync()` 和 `os.replace()` 原子替换，避免留下半份 evidence。

### 3.2 `tests/test_m43_executor_rewrite_baseline.py`

通过文件路径导入脚本，测试纯判定与固定 fake measurements，不依赖 Docker 或计时稳定性。一个真实 smoke 使用最小样本执行 trusted/restricted，证明脚本可运行和公开报告不泄漏临时绝对路径；timeout/crash 的完整真实证据由基线命令和现有 restricted 测试共同验证。

### 3.3 `docs/evaluation/m43/`

- `executor-rewrite-baseline.json`：脚本生成的原始证据。
- `rewrite-dependency-baseline.md`：六项表、阈值、复现命令、环境边界、判定和未来试验限制。

验证报告只引用证据中的聚合值和测试结果，不复制敏感或无界原始输出。

## 4. 测量模型

### 4.1 性能

同一进程内分别构造 backend，先 warm up，再对 `value = 1 + 1` 执行固定样本。使用 `perf_counter_ns()` 记录每次 wall time，报告 count、median、p95、min、max 和由总时间得到的 ops/s。trusted 与 restricted 分开报告；restricted 的每次执行天然包含 Python worker 启动和 JSON protocol 成本。

阈值在首次正式测量前固定：

- trusted trivial execute median 超过 `1.0 ms` 视为候选瓶颈；
- restricted trivial execute median 超过 `250.0 ms` 或 throughput 低于 `4.0 ops/s` 视为候选瓶颈；
- 任一越阈必须在同机干净复测再次越阈，并有真实任务预算或吞吐需求，才计为 `confirmed_bottleneck`；
- container 记录 median/p95/ops/s，但其启动开销不单独触发 Python rewrite。

阈值不是跨机器 SLA。原始样本保留在 JSON 以便同口径复测。

### 4.2 可靠性

trusted 与 restricted 各执行 `reliability_runs` 次简单 block，控制面失败必须为零。restricted 额外执行：

1. 在临时允许目录写入一个字节后，以 `os._exit(7)` 造成 worker 无结果退出，父进程必须得到结构化失败；
2. 在另一个临时哨兵写入一个字节后，以无限循环触发 `1.0s` timeout；
3. 每个失败之后立即执行新 block，必须成功，且宿主读取的对应哨兵必须仍精确为一个字节。

阈值为零正常执行控制面失败、两类故障后恢复均为 `true`。失败只有在同口径复现且影响真实路径时才构成 reliability bottleneck；M43 不自动将 bug 改写为 rewrite 理由。

container 可用时执行最小正常与异常后恢复；不可用写固定 `not_available` code，不写 raw Docker stderr。

### 4.3 维护成本

使用 `ast` 和文件字节统计 `executor.py`、`_sandbox_worker.py`、`runtime.py` 的 lines、bytes、顶层 symbol/import 数；使用 `tomllib` 统计 `pyproject.toml` 的直接 runtime dependency 数。报告只写相对文件标识。

当前边界若总代码超过 `1000` 行或直接运行时依赖超过 `8` 才标记维护瓶颈。未来试验不得新增 runtime dependency，候选单模块不得超过 `400` 行；若为满足阈值引入 FFI framework、生成器、注册器或第二套 protocol，立即回滚。

### 4.4 兼容性

基线固定 `ExecResult` 字段、三类 backend 名称、restricted JSON state roundtrip、异常结构化和故障后恢复。未来试验必须使现有 executor、restricted、container、escape、policy wiring 和 tool integration 测试零失败，且不改变 CLI/config/HTTP 或 worker frame。任一契约差异即回滚。

### 4.5 团队能力

报告记录 Python、uv、pytest、Ruff 已用于当前验证；`rustc/cargo` 仅记录 `available`，不得据此宣称具备维护能力。未来试验准入要求有明确维护所有者，并完成目标平台构建、故障调试、包集成、性能剖析和旧路径回滚演练。M43 不执行这些演练，因此该门默认 `not_ready`。

### 4.6 迁移与回滚风险

M43 baseline 为零 schema/config/data migration。未来试验必须只替换一个内部模块，保留当前 Python 路径和现有 worker protocol，不进行状态双写或无条件重放。若回滚需要数据转换、无法单独关闭候选、旧路径在验证前被删除或故障污染持久状态，试验不得开始或立即回滚。

## 5. 报告 schema 与判定

顶层字段固定为：

```json
{
  "schema": "forgeagent.executor-rewrite-baseline.v1",
  "generated_at": "UTC ISO-8601",
  "environment": {},
  "metrics": {},
  "verdict": "keep_python"
}
```

`environment` 只允许 Python version、`sys.platform`、machine architecture 和短 Git commit。每个 metric 必须包含 `baseline`、`threshold`、`evidence`、`migration`、`rollback_trigger`、`status`。backend evidence 状态只允许 `measured`、`not_available`、`failed`。

每项 status 使用按 metric 固定的允许集合；任何未知或拼写错误的 status 都是证据不完整。
`evaluate_readiness()` 按以下顺序判定：

1. 缺 metric、缺治理字段、required measurement 为 `failed` → `insufficient_evidence`；
2. 没有 `confirmed_bottleneck` → `keep_python`；
3. 有瓶颈但 compatibility、team capability 或 migration/rollback 未 ready → `insufficient_evidence`；
4. 所有门通过 → `eligible_for_single_module_experiment`。

`eligible` 只授权建立后续 full change，不授权实现、依赖、迁移或运行时切换。

## 6. 安全与失败语义

- 所有动态异常在报告中映射为固定 code；不序列化 `str(exc)`。
- 不保存 block 正文、stdout/stderr、allowed root、临时目录或 Docker 命令输出。
- 不拉取镜像、不启动服务、不发网络请求。
- 输出路径不写入 evidence；原子替换失败保留旧报告并删除临时文件。
- measurement failure 不能降级成空样本成功；空样本由纯函数拒绝。

## 7. TDD 与验证

RED/GREEN 顺序：先锁定 schema/字段与三种 verdict，再锁定脱敏和 backend 三态，最后实现真实测量和原子写。聚焦验证包含新测试与现有 executor/restricted/container/escape 测试；全量验证包含 pytest、Ruff check/format、diff check、OpenSpec strict 与 Comet guard。

性能结果仅以真实脚本输出为证据，不在单元测试断言具体毫秒值。Docker 未运行时如实记录未验证；没有 Linux 或真实容器证据时不得扩大结论。

## 8. 交付结论规则

基线文档必须逐行给出六项五字段并引用 JSON evidence。若当前无 confirmed bottleneck 或团队能力门未满足，M43 推荐结论必须是保持 Python；不得为了继续路线图而调整阈值。未来若真实需求改变，使用同一脚本重新测量并另建 change，而不是修改 M43 历史 evidence。
