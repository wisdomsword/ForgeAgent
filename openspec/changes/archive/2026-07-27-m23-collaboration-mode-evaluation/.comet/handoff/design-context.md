# Comet Design Handoff

- Change: m23-collaboration-mode-evaluation
- Phase: design
- Mode: compact
- Context hash: 44151d6161a63401a37da38723ac1db4816efc1aa4506a915d528188d52391c8

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/m23-collaboration-mode-evaluation/proposal.md

- Source: openspec/changes/m23-collaboration-mode-evaluation/proposal.md
- Lines: 1-27
- SHA256: b011827ad5a43035e6dcaf130cdb840d6115979edd021f032b7386837a335046

```md
## Why

ForgeAgent 已具备 Single、Duo、Triad 三种运行模式，但目前缺少在同一任务、模型版本、生成参数和环境下进行多轮重复对照的可审计证据。M23 需要建立独立评估能力，用原始机器记录和聚合报告呈现质量、成本与可用性指标，而不是从单次样本或角色数量推断模式优劣。

## What Changes

- 新增仓库外层的独立评估 harness，按固定顺序重复运行 Single、Duo、Triad，不修改协作运行时。
- 版本化固定任务、模型版本、生成参数、执行环境、重复次数与产物检查，并记录协议摘要和环境指纹。
- 为每次运行保存不含 prompt、回复正文或密钥的原始机器记录，覆盖完成状态、外部产物检查、验收循环、token、模型调用、延迟和 usage 完整性。
- 生成按模式聚合的机器报告与人工可读报告，明确分母、N/A 语义和小样本限制，不自动排名或宣称 Triad 优于 Single。
- 保持 credential 加载、CLI 产品入口和协作运行时行为不变。

## Capabilities

### New Capabilities

- `collaboration-mode-evaluation`: 固定协议、多轮执行、原始记录、聚合指标和中立报告的 Single/Duo/Triad 独立评估能力。

### Modified Capabilities

无。

## Impact

- 新增 `scripts/` 下的评估 harness、`tests/` 下的离线合同测试，以及 `docs/evaluation/m23/` 下的协议和评估证据。
- 更新 `README.md`、`ACTION_PLAN.md` 和 M23 里程碑记录。
- 不新增运行时依赖，不修改 `src/forgeagent/collaboration.py`、credential 配置或现有运行模式接口。

```

## openspec/changes/m23-collaboration-mode-evaluation/design.md

- Source: openspec/changes/m23-collaboration-mode-evaluation/design.md
- Lines: 1-76
- SHA256: 83e9c3bddc7bcfe147d7ffc7c5eb110f6d55a11e1d86aa7d1e4a9f809ee3f664

```md
## Context

现有 Single、Duo、Triad 都可通过公开的 Task/CollaborationRunner 组装运行，并通过 audit 事件提供逐次模型调用的 usage。CLI 面向人工交互，不适合冻结参数、自动确认 Triad 计划或生成结构化多轮证据；协作运行时本身也不应为了评估而增加产品行为。

评估的主要偏差风险来自任务、模型、执行顺序、环境、产物判定和指标分母不一致。另一个风险是把 Single 没有 Evaluator 的事实编码为零拒绝或百分百首次通过，从而制造不可比数字。

## Goals / Non-Goals

**Goals:**

- 用版本化 JSON 协议固定 3 个确定性编程任务、3 次重复、轮换模式顺序、同一模型 ID、同一生成参数、同一隔离环境和外部产物检查。
- 用独立 Python harness 直接组装现有公开 Task/CollaborationRunner，采集原始运行记录并生成可复算聚合结果。
- 覆盖任务完成率、首次验收通过率、rejection/correction 次数、四类 token、逻辑模型调用次数、端到端延迟和 usage 缺失率。
- 明确保留样本数、分母、失败原因和 N/A，不自动排序模式或得出 Triad 更优的结论。

**Non-Goals:**

- 不修改协作运行时、角色提示词、CLI 产品入口或模型客户端。
- 不新增或改变 credential 来源、配置回退或密钥管理。
- 不把 M23 变成统计显著性研究、性能压测或长期 CI 门禁。
- 不保存 prompt、模型回复正文、环境密钥或其他敏感内容。

## Decisions

### 独立 harness，而非 CLI shell 或运行时子命令

新增 `scripts/m23_mode_evaluation.py`。它复用公开 Task、CollaborationRunner、模型注册表和 audit 协议，但在仓库运行时包之外负责协议加载、临时工作区、调度、外部检查、原始记录和聚合。相比 shell 驱动 CLI，这避免交互式计划确认和文本解析；相比新增 `forgeagent evaluate`，它不扩大产品接口或协作运行时范围。

### 固定协议和轮换顺序

`docs/evaluation/m23/protocol.json` 固定：

- 模型 ID `claude-haiku-4-5`，并记录模型注册表文件哈希；所有角色使用同一 ID。
- `max_output_tokens=4096`、`temperature=0`、`thinking=off`、`effort=null`、`timeout_seconds=120`、`max_rounds=10`、`max_rejections=2`。
- `restricted` tier、关闭 memory/identity/skills/MCP、临时工作区、自动同意受工作区边界保护的文件操作和 Triad 计划。
- 3 个只依赖标准库/仓库测试依赖的确定性任务，每个模式重复 3 次。
- 每个任务按 Latin-square 风格轮换 `single/duo/triad` 首后顺序，降低时间漂移对单一模式的系统偏置。

协议以 SHA-256 标识。每个运行记录协议哈希、git commit、Python/平台信息、模型注册表哈希和固定参数；协议或环境不匹配时 harness 在模型调用前失败。

### 模式外完成判定与适用性

每个任务在独立临时工作区执行。运行结束后，无论模式内部状态如何，都执行同一个版本化外部检查。`solved` 只有在运行状态完成且全部外部检查通过时为真。

- `first_acceptance_passed`：仅 Duo/Triad 适用，表示第一次 Generator 候选被内部 Evaluator 接受；Single 为 `null`。
- `rejection_count` 和 `correction_count`：仅 Duo/Triad 适用；correction 是拒绝后新增的 Generator 尝试，Single 为 `null`。
- 原始记录保留模式状态与外部检查结果，避免将内部接受误当成任务完成。

### 调用、usage 与延迟口径

注入只在内存收集安全 audit 字段的 sink。`total_model_calls` 按 `llm.outcome` 逻辑调用计数；provider attempt 数另存为诊断字段，不替代主指标。每个有效 usage 必须包含非负整数的 input/output/cached/reasoning 四字段；缺失或无效视为该调用 usage 缺失。`usage_missing_rate` 的分母为逻辑模型调用数，零调用时为 `null`。

端到端延迟使用单调时钟，从模式运行开始到外部检查结束，包含协作轮次和产物验证。token 汇总只累加有效 usage，另保留缺失调用数，避免用零掩盖未知值。

### 证据布局与中立报告

每个运行完成后原子写入一个 `raw/*.json`，便于中断恢复；汇总器仅从这些原始文件复算 `summary.json` 和 `report.md`。原始记录只包含安全元数据、数值、状态、检查结果和产物哈希，不包含 prompt、回复正文或 credential。

报告按模式列出样本量、完成/首次验收/usage 分母、比例、token、调用数、rejection/correction 和延迟分布。模板禁止 winner/ranking/recommendation 字段，并固定写明“小样本描述性结果，不自动宣称 Triad 优于 Single”。

## Risks / Trade-offs

- [真实模型具有随机性且三次重复样本很小] → 固定协议、多轮重复、轮换顺序并只做描述性报告，不推断显著性。
- [canonical model ID 仍可能由服务端更新] → 记录 ID、注册表哈希、运行时间和环境指纹；报告明确这不是服务端权重哈希。
- [provider 不返回 usage] → 记录调用级缺失率和分母，不把缺失字段当零。
- [外部检查超时或异常] → 每项检查有固定超时，异常成为失败记录而不中断其他已排定运行。
- [真实运行可能因 auth/network 阻塞] → harness 在正式调度前做安全 preflight；失败不伪造评估结果，报告阻塞原因。
- [直接复用公开组装 API 可能随项目演进变化] → 离线合同测试覆盖协议、指标与记录结构；M23 不为未来兼容增加抽象层。

## Migration Plan

这是新增的仓库评估资产，无产品数据迁移。回滚时删除 harness、协议和 M23 证据即可，运行时行为不受影响。

## Open Questions

无。任务数、重复次数、模型、参数、环境、指标口径和非目标均在协议中冻结。

```

## openspec/changes/m23-collaboration-mode-evaluation/tasks.md

- Source: openspec/changes/m23-collaboration-mode-evaluation/tasks.md
- Lines: 1-23
- SHA256: 17fd9ef5074ade93db03420d66eed05cc13ba468f8c97a4c545a274b2e46d5c2

```md
## 1. 固定评估合同

- [ ] 1.1 新增版本化 `protocol.json`，固定 3 个任务、3 次重复、轮换模式顺序、模型、生成参数、环境和产物检查
- [ ] 1.2 新增离线合同测试，覆盖协议完整性、27 次排程、N/A 语义、usage 缺失和中立报告约束

## 2. 独立评估 Harness

- [ ] 2.1 实现协议校验、环境指纹、隔离工作区和固定任务夹具初始化
- [ ] 2.2 复用公开 Task/CollaborationRunner 运行 Single/Duo/Triad，不修改协作运行时或 credential 路径
- [ ] 2.3 实现安全 audit 采集、外部产物检查、指标口径和单次原始 JSON 原子写入
- [ ] 2.4 实现从原始记录复算 `summary.json` 和中立 `report.md` 的聚合器

## 3. M23 真实评估证据

- [ ] 3.1 执行模型/环境 preflight，并运行完整 3×3×3 固定调度
- [ ] 3.2 保存 27 份原始机器记录、协议/环境清单、聚合 JSON 和人工报告
- [ ] 3.3 核对聚合分母、失败/缺失语义、敏感信息排除和“不自动宣称 Triad 优于 Single”约束

## 4. 文档与验证

- [ ] 4.1 更新 README、ACTION_PLAN 和 M23 里程碑，区分描述性证据与产品结论
- [ ] 4.2 运行 ruff、目标/全量 pytest、OpenSpec strict 和 Comet verify
- [ ] 4.3 完成两轮自我评审，立即修复并复验所有发现

```

## openspec/changes/m23-collaboration-mode-evaluation/specs/collaboration-mode-evaluation/spec.md

- Source: openspec/changes/m23-collaboration-mode-evaluation/specs/collaboration-mode-evaluation/spec.md
- Lines: 1-78
- SHA256: 8a98157ec3119c034380d5ddec8066bf2b18b88e37af726b0e338a97553b78dc

```md
## ADDED Requirements

### Requirement: Versioned and fixed evaluation protocol
The evaluation system SHALL load a versioned machine-readable protocol that fixes the task suite, mode schedule, model identifier, generation parameters, execution settings, repeat count, and artifact checks before any model call.

#### Scenario: Protocol is valid
- **WHEN** an operator starts the M23 evaluation with the checked-in protocol
- **THEN** the system validates all fixed fields, records the protocol hash, and schedules every task-mode-repeat combination exactly once

#### Scenario: Protocol is incomplete or changed unexpectedly
- **WHEN** a required fixed field is missing, invalid, or conflicts with the expected environment
- **THEN** the system fails before invoking a model and reports the mismatched field

### Requirement: Repeated and order-balanced mode execution
The evaluation system SHALL run Single, Duo, and Triad on identical task fixtures and artifact checks for at least three repetitions per mode, using a fixed rotating mode order.

#### Scenario: Complete schedule
- **WHEN** the M23 protocol contains three tasks and three repetitions
- **THEN** the system creates twenty-seven independently isolated runs and follows the protocol's rotating mode order

### Requirement: Independent task completion checks
The evaluation system SHALL define task completion as a completed runtime outcome plus successful mode-independent artifact checks, and SHALL preserve both components in the raw record.

#### Scenario: Internal completion with a bad artifact
- **WHEN** a mode reports completion but an external artifact check fails
- **THEN** the raw record marks the task as not solved and preserves the failed check result

#### Scenario: Correct artifact after completed execution
- **WHEN** a mode reports completion and every external artifact check passes
- **THEN** the raw record marks the task as solved

### Requirement: Applicable acceptance-loop metrics
The evaluation system SHALL record first acceptance, rejection count, and correction count for Duo and Triad, and SHALL encode those fields as not applicable for Single.

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
The evaluation system SHALL record input, output, cached, and reasoning tokens; logical model call count; provider attempt diagnostic count; end-to-end latency; and call-level usage missingness without converting unknown usage into known zero.

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
The evaluation system SHALL atomically save one safe machine-readable record per run and SHALL derive machine and human aggregate reports only from those records.

#### Scenario: Run record is saved
- **WHEN** a scheduled run reaches a terminal state
- **THEN** its raw record contains protocol/environment identifiers, metrics, checks, statuses, and artifact hashes but no prompt, model reply body, or credential

#### Scenario: Aggregation is repeated
- **WHEN** the aggregator reads the same complete raw record set more than once
- **THEN** it produces equivalent metric values and denominators

### Requirement: Neutral descriptive report
The evaluation system SHALL report per-mode sample sizes, denominators, rates, counts, token totals, call counts, latency distributions, and usage missingness without automatically ranking modes or asserting that Triad is superior to Single.

#### Scenario: Human report is generated
- **WHEN** aggregation completes
- **THEN** the report states the small-sample limitation, renders non-applicable metrics explicitly, and contains no automatic winner or superiority conclusion

```
