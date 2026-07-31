# Comet Design Handoff

- Change: measure-executor-rewrite-baseline
- Phase: design
- Mode: compact
- Context hash: b58f55ca1e58640bb4cc8d797374ef5c75b8334e2e1e760a377bcc7b3b2be932

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/measure-executor-rewrite-baseline/proposal.md

- Source: openspec/changes/measure-executor-rewrite-baseline/proposal.md
- Lines: 1-26
- SHA256: a0ca3b197e7623da02939afeb6d0558d8da61bd2e1fdfbc2f698c95e92ae2fe4

```md
## Why

ForgeAgent 已具备 trusted、restricted 和 container 三条 Python 执行路径，但当前没有针对执行后端替换的同口径基线，无法用证据判断启动延迟、吞吐、隔离、崩溃恢复或维护成本是否已经构成重写瓶颈。M43 先把六项 Rewrite/Dependency 门禁落成可复现测量和有界结论，避免因技术偏好直接进入 Rust 重写或新增依赖。

## What Changes

- 新增标准库离线测量入口，生成版本化、机器可读且不含凭据或绝对路径的执行后端基线证据。
- 为 performance、reliability、maintenance cost、compatibility、team capability、migration/rollback risk 六项指标分别记录 baseline、threshold、evidence、migration 和 rollback trigger。
- 对 trusted 与 restricted 路径执行同口径测量；container 只在真实 Docker daemon 与固定镜像可用时测量，不可用必须记为未验证而非通过。
- 形成是否允许后续单模块可回滚试验的明确 verdict；未达到阈值或证据不完整时保持现有 Python 实现。
- 增加离线契约测试、验证报告和 M43 里程碑记录。
- 不实现 Rust 后端，不新增运行时或开发依赖，不改变执行协议、sandbox、CLI、配置、schema 或发布状态。

## Capabilities

### New Capabilities

- `execution-backend-rewrite-readiness`: 定义 Python 执行路径六项基线、证据完整性、试验准入和停止/回滚契约。

### Modified Capabilities

无。

## Impact

影响范围限于离线测量脚本、其契约测试、评估文档、验证报告、OpenSpec 产物和里程碑账本。`src/forgeagent/executor.py`、`_sandbox_worker.py`、运行时依赖树和所有用户可见接口保持不变；不执行 PyPI、tag 或发布自动化。普通分支 push 只作为已授权的版本控制交接，不属于测量能力。

```

## openspec/changes/measure-executor-rewrite-baseline/design.md

- Source: openspec/changes/measure-executor-rewrite-baseline/design.md
- Lines: 1-77
- SHA256: 2833651059fce8dedff55ccf6b3fe873bd285b1ad3b9323b08fa7980158d0aee

```md
## Context

ForgeAgent 的 `TrustedBackend` 在宿主进程执行 Python，`RestrictedBackend` 为每个 block 启动隔离 Python worker，`ContainerBackend` 通过一次性 Docker container 执行相同 JSON worker 协议。现有测试证明主要正确性与安全边界，但缺少同一入口生成的启动延迟、吞吐、恢复、结构、兼容和迁移证据。M32 定义了六项治理字段，M41 曾为 CLI 重构实际应用该结构；M43 将同一治理结构应用于执行后端替换的 readiness 判断。

当前约束是：不修改执行后端、不引入 Rust 或新依赖、不读取凭据、不访问网络、不把 Docker 不可用视为通过，并保持所有 M42 及更早契约不变。主工作区存在 M43 之前的用户改动，M43 只选择性归属自身文件。

## Goals / Non-Goals

**Goals:**

- 用一个标准库离线入口产生版本化 JSON 原始证据。
- 对六项指标分别固定 baseline、threshold、evidence、migration 和 rollback trigger。
- 区分 `measured`、`not_available` 和 `failed`，不把未运行场景算成通过。
- 产生 `keep_python`、`eligible_for_single_module_experiment` 或 `insufficient_evidence` 的有界 verdict。
- 让未来试验只能通过独立 change、单模块、保留旧路径并具备确定回滚条件进入。

**Non-Goals:**

- 不实现或脚手架化 Rust/FFI 后端，不修改 `executor.py` 或 worker 协议。
- 不新增依赖、配置、CLI 命令、运行时 schema、数据迁移或遥测。
- 不把本机微基准声明为跨平台 SLA，也不把计时阈值接成易抖动的 CI 失败门禁。
- 不执行 PyPI、tag 或发布自动化；普通分支 push 不是测量能力，但可按已授权的版本控制交接执行。

## Decisions

### 1. 使用标准库离线测量器和冻结 JSON 证据

新增 `scripts/m43_executor_rewrite_baseline.py`。父进程负责环境摘要、结构统计、后端测量、故障恢复和 verdict；计时使用 `time.perf_counter_ns()`，聚合使用 `statistics`。报告固定 schema 与六个 metric key，公开内容不包含绝对路径、环境值、代码正文、raw exception 或 subprocess 原始输出。

替代方案 A 是仅记录手工命令，改动最少但难以同口径复测；方案 C 是将绝对时间接成 CI 硬门禁，自动化更强但会被共享 runner 和平台差异误报。选择离线测量器，在测试中只验证结构和判定纯函数，真实计时仅作为评审证据。

### 2. 三条执行路径按可验证边界分层

- trusted 与 restricted 必须真实测量构造、简单 block 延迟和顺序吞吐。
- restricted 必须验证 worker 异常退出与 timeout 后的下一次执行仍成功。
- container 只有 Docker daemon 和既定镜像本地可用时才真实测量；否则记录固定 `not_available` reason，不能进入性能比较或被计为可靠性通过。

不自动拉取镜像、不启动 daemon、不访问网络。容器缺证据不阻止建立 Python 主路径基线，但会让任何以 container 替换为目标的后续试验保持 `insufficient_evidence`。

### 3. 六项指标使用证据门与瓶颈门

每项指标都在 Markdown 基线表和 JSON evidence 中具备五个治理字段。performance、reliability、maintenance cost 用具体测量判断是否存在瓶颈；compatibility、team capability、migration/rollback risk 用可行性条件判断未来试验是否可控。

只有同时满足以下条件才输出 `eligible_for_single_module_experiment`：

1. 六项证据完整且没有 `failed`；
2. 至少一个真实使用相关的瓶颈阈值被越过；
3. compatibility、team capability、migration/rollback risk 三项均满足试验准入；
4. 对应边界有真实 verifier，不依赖未运行的 Docker 或推测数据。

否则输出 `keep_python`；关键证据缺失或测量失败则输出 `insufficient_evidence`。该 verdict 只决定是否可以另建试验 change，不会切换运行时。

### 4. 阈值不伪装成跨机器 SLA

性能阈值写成当前硬件上的操作预算和同机复测规则，并保留原始样本。未来若越阈，必须在干净环境用同一命令复测一次且结合真实任务需求；单次微基准越界不够启动重写。可靠性要求正常执行与故障后恢复零控制面失败。维护、兼容、团队能力和回滚阈值分别约束新增复杂度、旧契约、维护所有权和旧路径保留。

### 5. M43 只交付测量能力和结论

测量结果、阈值表、验证报告和里程碑属于 M43。若 verdict 允许试验，后续仍必须建立新的 full Comet change，明确单一目标模块、migration、rollback 和平台 verifier；M43 不预建候选实现。

## Risks / Trade-offs

- [微基准受机器负载影响] → 保存原始样本和环境摘要，使用中位数/p95；越阈必须同机干净复测并绑定真实需求。
- [trusted 与 restricted 成本量级不同] → 分别报告，不用一个平均数掩盖隔离成本。
- [Docker 不可用造成证据缺口] → 固定标记 `not_available`，不拉取镜像，不把 skip 写成 pass。
- [脚本本身变成新框架] → 单文件标准库实现，只保留测量与纯判定函数，不新增通用 benchmark 抽象。
- [工作区既有改动被误归属] → M43 只选择性暂存新增/明确修改文件，最终 diff 按 base-ref 和文件归因双审。

## Migration Plan

M43 没有运行时迁移。先以测试锁定报告 schema、脱敏和 verdict，再运行真实测量并冻结 evidence，最后验证文档与 OpenSpec 契约。回滚 M43 只需删除其脚本、测试和文档；执行后端、配置、数据和依赖树均保持原样。

未来单模块试验必须保留当前 Python 路径为默认或显式 fallback，不迁移持久化状态；出现兼容失败、恢复失败、性能改善未达目标、维护者无法排障或回滚需要数据转换时立即停止并回退旧路径。

## Open Questions

无。真实数值和最终 verdict 由 build 阶段同口径测量决定，不在设计阶段预判。

```

## openspec/changes/measure-executor-rewrite-baseline/tasks.md

- Source: openspec/changes/measure-executor-rewrite-baseline/tasks.md
- Lines: 1-21
- SHA256: c15c70b1dd3111dce151bdbc2959aae661a8ff47d96c9811c446d93806e68130

```md
## 1. 测量契约与测试

- [ ] 1.1 先新增报告 schema、六项 metric 完整性、脱敏和 verdict 纯判定的失败测试。
- [ ] 1.2 新增 trusted/restricted/container 可用性与故障恢复测量边界测试，锁定 `not_available` 不得算通过。

## 2. 离线测量实现

- [ ] 2.1 实现标准库 `scripts/m43_executor_rewrite_baseline.py`，采集性能、可靠性、维护、兼容、团队能力和迁移/回滚证据。
- [ ] 2.2 运行真实 trusted/restricted 测量；仅在本地 daemon 与固定镜像已可用时测 container，并生成版本化 JSON 原始证据。
- [ ] 2.3 根据同口径结果填写六项 baseline、threshold、evidence、migration、rollback trigger 与最终 readiness verdict。

## 3. 文档与规划同步

- [ ] 3.1 新增 M43 基线文档，记录原始样本、复现命令、平台边界、阈值判断和未来单模块试验门禁。
- [ ] 3.2 更新 canonical 评审/治理文档和 `ACTION_PLAN.md`，明确 M43 只完成测量且不授权重写、新依赖或发布。

## 4. 评审、验证与收尾

- [ ] 4.1 完成两轮 base-ref/文件归因自审，修复模糊、错误、过于保守、前后不一致和遗漏。
- [ ] 4.2 运行聚焦与全量 pytest、Ruff、format、diff check、OpenSpec strict 和 Comet verify，记录未验证的真实边界。
- [ ] 4.3 更新验证报告、`milestones/milestone_043.md` 与 `milestones/latest`，同步主规格并归档 change。

```

## openspec/changes/measure-executor-rewrite-baseline/specs/execution-backend-rewrite-readiness/spec.md

- Source: openspec/changes/measure-executor-rewrite-baseline/specs/execution-backend-rewrite-readiness/spec.md
- Lines: 1-50
- SHA256: dcb2ca4bc55ff84d8a756c43a859afa577599dbd20bc0dde59638c86f55c38fc

```md
## ADDED Requirements

### Requirement: Execution rewrite evidence is versioned and reproducible
ForgeAgent SHALL provide an offline, standard-library-only measurement entry point that records a versioned execution-backend report. The report MUST contain exactly the six governance metrics `performance`, `reliability`, `maintenance_cost`, `compatibility`, `team_capability`, and `migration_rollback_risk`, and every metric MUST contain baseline, threshold, evidence, migration, and rollback trigger information.

#### Scenario: A baseline report is generated
- **WHEN** the M43 measurement entry point runs against the current repository
- **THEN** it emits a versioned machine-readable report with all six metrics and the commands or observations needed to reproduce the evidence

#### Scenario: Sensitive runtime context exists
- **WHEN** environment values, repository paths, executed code, or subprocess failures are observed during measurement
- **THEN** the public report contains no environment value, absolute path, code body, raw exception, or raw subprocess output

### Requirement: Backend evidence distinguishes measurement from absence
The measurement SHALL exercise trusted and restricted Python execution paths with the same trivial workload shape. Restricted evidence MUST include recovery after a worker crash and timeout. Container evidence MUST run only when the local daemon and fixed image are already available; unavailable container evidence MUST be recorded as `not_available` and MUST NOT count as passed or measured.

#### Scenario: Restricted worker terminates unexpectedly
- **WHEN** a restricted execution worker exits or is killed by its timeout
- **THEN** the report records a structured failure and verifies that a subsequent block can execute successfully without replaying the failed block

#### Scenario: Container runtime is unavailable
- **WHEN** the configured local container runtime or fixed image cannot be verified without network access
- **THEN** the report records fixed `not_available` evidence and excludes container timing from rewrite eligibility

### Requirement: Rewrite eligibility requires evidence and a real bottleneck
The readiness evaluator MUST return only `keep_python`, `eligible_for_single_module_experiment`, or `insufficient_evidence`. It MUST return `eligible_for_single_module_experiment` only when all six metric records are complete, at least one measured real-use bottleneck crosses its declared threshold after required clean remeasurement, compatibility and team-capability constraints are satisfied, rollback remains deterministic, and the relevant real boundary has a verifier.

#### Scenario: Metrics remain within thresholds
- **WHEN** all required evidence is complete and no real-use bottleneck crosses its threshold
- **THEN** the verdict is `keep_python` and no rewrite or new dependency is authorized

#### Scenario: A timing sample alone crosses a threshold
- **WHEN** one noisy or unconfirmed microbenchmark sample crosses a performance threshold without clean remeasurement and a real-use requirement
- **THEN** the verdict is not `eligible_for_single_module_experiment`

#### Scenario: Critical evidence is incomplete
- **WHEN** a required metric fails measurement or a proposed target boundary lacks its real verifier
- **THEN** the verdict is `insufficient_evidence` rather than success

### Requirement: Any later experiment is isolated and reversible
M43 MUST NOT implement a Rust backend, add a dependency, alter an execution protocol, or switch a runtime path. A later experiment SHALL require a separate full Comet change, SHALL target one module, SHALL preserve the current Python path, and SHALL define migration and rollback triggers before implementation.

#### Scenario: M43 completes measurement
- **WHEN** the baseline and verdict are finalized
- **THEN** runtime source, dependencies, configuration, persisted data, sandbox behavior, and public interfaces remain unchanged

#### Scenario: A later experiment cannot retain the Python path
- **WHEN** a candidate requires irreversible state conversion, unconditional replay, or removal of the current Python path before verification
- **THEN** the candidate is rejected or rolled back without entering migration


```
