# Comet Design Handoff

- Change: m25-programming-mode-evaluation
- Phase: design
- Mode: compact
- Context hash: 15490125223768741d07f47b32c01de1f13b0a379587a39af19d4a95ccfdb51d

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/m25-programming-mode-evaluation/proposal.md

- Source: openspec/changes/m25-programming-mode-evaluation/proposal.md
- Lines: 1-29
- SHA256: fbda2cf0ede57261d01a61cbc980a915639e033331082ddbb9e8008dd6ed8148

```md
## Why

M23 仅覆盖三个文件/数据任务、每组合三次重复、一个模型与一条 provider 路由，样本不足以支持 Single、Duo、Triad 的产品决策。M25 需要在不改写 M23 历史证据的前提下，用更多真实编程任务、更多重复以及第二模型/路由建立可复算的质量—成本证据。

## What Changes

- 新增独立、版本化的 M25 固定协议，保留 M23 三个基线任务并增加六个真实编程任务，覆盖 bugfix、功能实现和行为保持重构三个任务族。
- 对每个任务、模型和模式固定执行五次重复，并以轮换顺序平衡 Single、Duo、Triad 的运行次序。
- 固定使用 `claude-haiku-4-5` 与 `gpt-5.4-mini` 两个模型及各自解析出的 provider 路由，分别记录模型和路由环境指纹。
- 继续记录完成率、首次验收通过率、rejection/correction、四类 token、逻辑模型调用、provider attempts、端到端延迟和 usage 缺失率，并按模型、任务族、任务和模式生成可复算汇总。
- 保持报告中立，不生成模式排名、winner 字段或自动优越性结论。
- M23 的固定协议、27 份正式 raw、环境清单、汇总、报告和无效批次保持不变且不参与 M25 聚合。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `collaboration-mode-evaluation`: 将单模型、小任务集评估合同扩展为独立多模型协议、真实编程任务族、五次重复、分层聚合和历史证据隔离。

## Impact

- 评估层：新增 M25 协议、任务 fixtures、运行证据目录，并最小修改现有 M23 harness 或提取其通用部分以支持协议声明的多模型调度和分层汇总。
- 测试与文档：扩展离线协议、排程、完整性、聚合、安全和中立报告合同，更新 `ACTION_PLAN.md`、里程碑与评估说明。
- 运行时与依赖：不修改 ForgeAgent 协作运行时、公开 CLI、模型注册语义或 credential 机制；不新增产品依赖。
- 成本与环境：完整真实批次为 9 个任务 × 2 个模型 × 3 种模式 × 5 次重复，共 270 次运行，只作为显式授权的本机评估，不进入离线 CI。

```

## openspec/changes/m25-programming-mode-evaluation/design.md

- Source: openspec/changes/m25-programming-mode-evaluation/design.md
- Lines: 1-88
- SHA256: 3d0c7e13a519e70afdcf954d243f2e5a24e426e14255f89bfbd071f0b4a085fc

[TRUNCATED]

```md
## Context

M23 的 `scripts/m23_mode_evaluation.py` 已实现严格协议校验、隔离工作区、Single/Duo/Triad 运行、审计投影、外部检查、原子 raw、完整性聚合和中立报告。其当前 schema 将单一 `model_id`、三个任务、三次重复和 27 个 run 固定在 M23 v2，正式证据位于 `docs/evaluation/m23/`。

M25 要把样本扩大到九个任务、两个模型和五次重复，同时保持 M23 协议与所有历史证据逐字节不变。完整批次包含 270 个真实 run，必须允许中断后按固定 identity 续跑，并在不完整时拒绝聚合。

## Goals / Non-Goals

**Goals:**

- 提供独立的 `forgeagent.m25.mode-evaluation/v1` 协议和 `docs/evaluation/m25/` 证据根。
- 保留三个 M23 基线任务，新增 bugfix、feature、refactor 三个真实编程任务族，每族两个任务。
- 固定 `claude-haiku-4-5`、`gpt-5.4-mini`、五次重复及确定性顺序，生成 270 个唯一 run。
- 保留 M23 全部质量、成本、调用、延迟与 usage 完整性口径，并增加模型、路由和任务族维度。
- 保持运行时、credential、模型注册和依赖不变。

**Non-Goals:**

- 不修改 M23 的 protocol、raw、environment、summary、report 或无效批次。
- 不生成显著性检验、综合分数、winner、自动排名或产品默认模式建议。
- 不把真实 provider 调用加入 CI，不声称本机结果代表其他平台或未来模型权重。
- 不引入通用 benchmark 框架、数据库、并发调度器或新依赖。

## Decisions

### 1. 独立协议与证据命名空间

M25 使用独立 schema、协议文件和输出根。每份 raw 同时绑定协议 hash、环境 hash、模型 ID、provider route hash、任务族和 RunSpec hash；M25 聚合器拒绝任何 M23 schema 或跨协议、跨环境、跨路由记录。M23 文件不迁移也不重写。

备选是直接把 M23 protocol 升级到 v3；这会让历史命名空间与新证据混合，故拒绝。

### 2. 向后兼容扩展现有 harness

保留 M23 CLI 和 v2 行为，通过最小的通用数据模型与分支支持 M25 v1，而不是复制约千行执行与安全逻辑。M23 的现有 53 项合同继续作为兼容门禁；M25 新测试只覆盖新增 schema、模型维度、任务族、排程和分层汇总。

若直接扩展使 M23 代码出现重复分支，则只提取纯函数/通用模型，不新增 factory、manager 或第三方库。不得修改协作运行时来迁就评估。

### 3. 固定任务矩阵

M25 protocol 含九个任务：三个 M23 基线任务原样复制到新协议，另外六个任务以小型多文件 Python 项目 fixture 表达：

- `bugfix`：边界/状态错误与跨模块数据处理错误；
- `feature`：在既有 API 上实现有明确验收的功能；
- `refactor`：在保持行为和公开接口的前提下重组现有实现。

每族包含两个任务，至少一个任务涉及多个源文件。所有任务仅用 Python 标准库和仓库已有测试工具；初始 fixture、不可变文件、候选文件和外部检查均写入固定协议。完成仍定义为 runtime completed 且所有模式无关检查、fixture integrity 和 artifact 检查通过。

备选是直接从当前 ForgeAgent 源树抽取任务；这会引入许可证、版本漂移和 fixture 体积问题，故采用自包含的小型真实项目。

### 4. 两模型与顺序平衡

两个模型都承担每个角色，生成与执行设置保持同一协议声明；能力适配仍由现有 client 完成。preflight 分别解析并哈希 `[model_id, client_kind, base_url-or-provider-default]`，不保存 base URL 或 credential。

排程遍历九个任务、两个模型和五次重复；每次包含三种模式。三种 Latin 轮换顺序按“任务 × 模型”单元偏移，使全部 18 个单元上的模式位置计数相等。模型先后顺序也按任务和重复确定性交替，减少单一路由持续集中在批次前半段。协议和测试固定完整 270-run 顺序。

### 5. 安全续跑与严格聚合

每个 run 使用包含 model slug 的稳定文件名和独立临时工作区。已有 raw 必须通过完整 schema、identity、hash 和环境绑定校验后才能跳过；冲突记录使运行停止。每次终态原子写入 raw；聚合只接受 270/270 的完整集合，不提供 partial-summary 开关。

环境清单记录两个模型的安全 route hash、内置 registry/config hash、提交、tracked dirty、平台和固定参数。真实运行前要求 tracked 源码干净；本 change 规划/证据文件的预期状态按协议记录，不把无关未跟踪文件混入 environment 判定。

### 6. 分层且中立的输出

`summary.json` 的主要分母按模型和模式分开，并提供 task family 与 task 的样本计数及同口径指标。`report.md` 展示每个模型下的 Single/Duo/Triad 描述性数据以及各任务族结果，不计算跨模型综合分数，不包含 `rank`、`winner`、`best` 或优越性结论。

所有 M23 指标继续记录：solved、first acceptance、rejection/correction、input/output/cached/reasoning tokens、logical calls、provider attempts、端到端延迟和 usage missing rate；Single 的验收循环指标继续为 N/A。

## Risks / Trade-offs

- [270 次真实运行带来显著费用与耗时] → 固定上限、原子 raw 和严格续跑避免重复付费；preflight 与离线合同先通过后才调用 provider。
- [五次重复无法在单个任务/模型单元内让三个位置完全等频] → 在 18 个单元间轮换偏移，使全批次位置分布精确平衡，并保留每个 run 的顺序。
- [两个 provider 的服务端权重和负载不可固定] → 记录 UTC、commit、模型 ID、route hash、attempt、latency 和限制说明，只给描述性结论。
- [真实编程 fixtures 可能泄漏答案或偏向某种模式] → 任务目标只暴露公开合同；外部检查固定且模式无关；两轮离线任务审计检查可解性、歧义和检查强度。
- [兼容扩展可能回归 M23] → M23 protocol hash、正式证据文件 hash、现有专项测试和独立复算均作为回归门禁。
- [本机无第二路由 credential] → preflight 在任何模型调用前失败并报告缺失的模型路由；不得用单模型不完整集合替代正式报告。

## Migration Plan

1. 保存 M23 受保护文件 hash 基线并建立离线回归合同。
2. 先以测试驱动扩展 schema、排程、identity、环境和聚合逻辑。

```

Full source: openspec/changes/m25-programming-mode-evaluation/design.md

## openspec/changes/m25-programming-mode-evaluation/tasks.md

- Source: openspec/changes/m25-programming-mode-evaluation/tasks.md
- Lines: 1-33
- SHA256: 3805183da65496807062cc3e5a7d8458a5a8594da41e1ce42f90fd38f8ffd937

```md
## 1. 历史证据保护与测试基线

- [ ] 1.1 为 M23 protocol、正式 environment/raw/summary/report 建立不可变性回归检查，并确认现有 M23 专项测试通过
- [ ] 1.2 为 M25 独立 schema、证据根和拒绝混入 M23 记录编写失败优先的离线合同

## 2. 多模型协议与固定排程

- [ ] 2.1 扩展评估协议、RunSpec、raw 和 environment 模型，支持模型列表、provider route hash 和任务族，同时保持 M23 v2 向后兼容
- [ ] 2.2 实现并测试 9 × 2 × 3 × 5 的 270-run 确定性排程、全局模式位置平衡、唯一 identity 和安全续跑

## 3. 真实编程任务族

- [ ] 3.1 定义两个 bugfix、两个 feature 和两个 refactor 自包含 Python 项目 fixture，覆盖单文件与多文件修改
- [ ] 3.2 为六个任务固定不可变文件、候选文件和模式无关外部检查，并完成可解性、歧义与检查强度两轮审计
- [ ] 3.3 创建 `docs/evaluation/m25/protocol.json`，保留三个 M23 基线任务并固定两个模型、五次重复和九个任务

## 4. 分层聚合与中立报告

- [ ] 4.1 扩展完整性校验和聚合，按模型、模式、任务族与任务复算全部质量、成本、调用、延迟和 usage 缺失指标
- [ ] 4.2 扩展机器 summary 与人工报告，保留 Single 的 N/A 语义并禁止 rank、winner、best-mode 或自动优越性结论
- [ ] 4.3 运行 M23/M25 专项、Ruff 和证据安全测试，确认 270 个 synthetic raw 可重复聚合且 M23 正式文件 hash 未变

## 5. 真实模型证据批次

- [ ] 5.1 提交实现并执行双模型 credential/route、协议 hash、环境、tracked-clean 和 270-run/轮次/token 上限 preflight
- [ ] 5.2 执行或安全续跑 270 次真实模型评估，保存 270 份终态 raw，任何不完整或混合批次均不聚合
- [ ] 5.3 从完整 raw 独立复算 `summary.json` 和 `report.md`，核对所有分母、失败、usage 缺失、模型与任务族切片

## 6. 验证与里程碑收尾

- [ ] 6.1 完成两轮最终自审，修复错误、前后不一致、遗漏、数据泄漏、隐式排名和 M23 漂移
- [ ] 6.2 运行聚焦测试、全量 pytest、golden、Ruff、build、OpenSpec strict 和 `git diff --check`
- [ ] 6.3 更新 `ACTION_PLAN.md`、评估文档与 M25 里程碑，记录真实证据范围、限制、验证输出和续接指引

```

## openspec/changes/m25-programming-mode-evaluation/specs/collaboration-mode-evaluation/spec.md

- Source: openspec/changes/m25-programming-mode-evaluation/specs/collaboration-mode-evaluation/spec.md
- Lines: 1-106
- SHA256: 23cce73e350cc18fe5dd56e8c1cf5a0f86396775b42c4e33e1cb5db9f67517ec

[TRUNCATED]

```md
## MODIFIED Requirements

### Requirement: Versioned and fixed evaluation protocol
The evaluation system SHALL load a versioned machine-readable protocol that fixes the task suite, task families, mode schedule, model identifiers, generation parameters, execution settings, repeat count, artifact checks, and evidence namespace before any model call, and SHALL keep each protocol's historical evidence immutable and isolated.

#### Scenario: M25 protocol is valid
- **WHEN** an operator starts the M25 evaluation with the checked-in protocol
- **THEN** the system validates every fixed field, records the protocol hash, and schedules every task-model-mode-repeat combination exactly once

#### Scenario: Protocol is incomplete or changed unexpectedly
- **WHEN** a required fixed field is missing, invalid, conflicts with the expected environment, or references another protocol's evidence namespace
- **THEN** the system fails before invoking a model and reports the mismatched field

#### Scenario: Historical M23 evidence exists
- **WHEN** the M25 protocol or aggregator is used in a repository containing M23 evidence
- **THEN** the system neither reads M23 raw records into M25 aggregation nor modifies any M23 protocol or evidence file

### Requirement: Repeated and order-balanced mode execution
The evaluation system SHALL run Single, Duo, and Triad on identical task fixtures and artifact checks for five repetitions per model, using a fixed deterministic schedule that balances mode position across the complete task-model matrix.

#### Scenario: Complete M25 schedule
- **WHEN** the M25 protocol contains nine tasks, two models, three modes, and five repetitions
- **THEN** the system creates 270 independently isolated runs with unique identities and equal aggregate position counts for Single, Duo, and Triad

#### Scenario: Evaluation resumes
- **WHEN** a scheduled run already has a valid terminal raw record bound to the same protocol, environment, route, and RunSpec hashes
- **THEN** the system skips that run without invoking a model and continues with the next fixed schedule entry

### Requirement: Independent task completion checks
The evaluation system SHALL define task completion as a completed runtime outcome plus successful mode-independent artifact checks, SHALL preserve both components in the raw record, and SHALL apply the same checks to every model and mode for a task.

#### Scenario: Internal completion with a bad artifact
- **WHEN** a mode reports completion but an external artifact check fails
- **THEN** the raw record marks the task as not solved and preserves the failed check result

#### Scenario: Correct artifact after completed execution
- **WHEN** a mode reports completion and every external artifact check passes
- **THEN** the raw record marks the task as solved

#### Scenario: Immutable fixture is modified
- **WHEN** a candidate changes, removes, or replaces a protocol-declared immutable fixture
- **THEN** an independent fixture-integrity check fails and the raw record marks the task as not solved

#### Scenario: Real programming task is scheduled
- **WHEN** the task belongs to the bugfix, feature, or refactor family
- **THEN** the isolated workspace contains the fixed multi-file fixture and its protocol-declared checks without access to another run's workspace

### Requirement: Applicable acceptance-loop metrics
The evaluation system SHALL record first acceptance, rejection count, and correction count for Duo and Triad for every model and task family, and SHALL encode those fields as not applicable for Single.

#### Scenario: Single run
- **WHEN** the system records a Single run
- **THEN** first acceptance, rejection count, and correction count are null rather than zero or a fabricated percentage

#### Scenario: Collaboration run accepted immediately
- **WHEN** the first Generator candidate is accepted by the Evaluator
- **THEN** first acceptance is true and both rejection and correction counts are zero

#### Scenario: Collaboration run requires correction
- **WHEN** the Evaluator rejects a candidate and the Generator tries again
- **THEN** the raw record preserves the rejection and correction counts and first acceptance is false

### Requirement: Complete quality and cost telemetry
The evaluation system SHALL record input, output, cached, and reasoning tokens; logical model call count; provider attempt diagnostic count; end-to-end latency; and call-level usage missingness for each model, task family, task, and mode without converting unknown usage into known zero.

#### Scenario: Usage is present
- **WHEN** a logical model call emits four valid non-negative token fields
- **THEN** the system adds those tokens to the run totals and counts the call as usage-present

#### Scenario: Usage is absent or invalid
- **WHEN** a logical model call lacks a valid usage payload
- **THEN** the system increments the missing-usage numerator, excludes unknown tokens from totals, and retains the logical call in the denominator

#### Scenario: No logical model call occurs
- **WHEN** a run fails before the first model call
- **THEN** the system records zero calls and a null usage missing rate

### Requirement: Safe raw records and reproducible aggregation
The evaluation system SHALL atomically save one safe machine-readable record per run and SHALL derive machine and human aggregate reports only from the complete raw record set for one protocol and environment.


```

Full source: openspec/changes/m25-programming-mode-evaluation/specs/collaboration-mode-evaluation/spec.md
