# Comet Design Handoff

- Change: eval-evaluator
- Phase: design
- Mode: compact
- Context hash: 72e6f036f5e9a9161d786652cfd91cfe2a68fa449b7fe759efbbd31d4916a732

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/eval-evaluator/proposal.md

- Source: openspec/changes/eval-evaluator/proposal.md
- Lines: 1-28
- SHA256: db2223922ce9518890c9fc6aa5d53495c44087a3adace10a3f49a03c945c8905

```md
## 为什么

ForgeAgent 已有确定性的 20 项 golden core 与审计记录，但还没有稳定方式比较不同运行的结果，或发现 Harness 变更让“模型 + Harness”组合变好还是退化。M20 增加离线优先的评估记录与显式 opt-in 的独立 Evaluator，同时不削弱可信核心。

## 变更内容

- 增加版本化机器可读的评估记录契约，从 golden suite 结果和兼容的审计事件聚合 `first_pass_correctness`、`correction_rounds`、`cache_hit_rate` 与 golden 通过率。
- 增加本地趋势记录与比较命令；不需要服务、网络或凭证。
- 增加 manifest 基线守卫，在报告前拒绝删除、替换或降低可信核心标准。
- 增加 opt-in 独立 Evaluator，以独立构造的 Task 会话检查声明的外部产物并输出 pass/fail 证据。
- 保持确定性的 20 项离线 golden core 作为 CI 权威；Evaluator 不进入离线 CI 或普通任务执行。

## 能力范围

### 新能力

- `evaluation-metrics`：离线聚合、持久化与比较 golden/audit 证据。
- `independent-evaluator`：对外部可观察任务产物进行 opt-in 隔离评估。

### 修改能力

- `golden-validation-core`：为可信核心 manifest 增加固定基线，拒绝删除或降低场景标准。

## 影响

- 影响 golden runner/manifest、审计事件投影、CLI 命令和新增评估模块。
- 更新评估用法、威胁边界、里程碑计划等文档。
- 不增加运行时服务、外部依赖、HTTP schema 或默认模型调用，不放宽现有 20 项可信核心要求。

```

## openspec/changes/eval-evaluator/design.md

- Source: openspec/changes/eval-evaluator/design.md
- Lines: 1-58
- SHA256: 9e0b04475c14e46a573d55768966fb2171a1e91cd2e4371b06c85835719cee2d

```md
## 上下文

现有 trusted golden runner 已输出 `forgeagent.golden.v1` JSON 报告，运行时已输出脱敏的 `AuditEvent` JSONL。两者足以支撑 M20 指标，但 schema 有意独立，报告目前也没有历史持久化。20 项 core 是离线 CI 权威；其中 5 项真实模型场景仍然单独 opt-in。

## 目标 / 非目标

**目标：**

- 将 golden 报告与审计事实规范化为确定性的 M20 evaluation record，保存并与上一条记录比较。
- 计算首轮正确率、修正轮数、cache 命中率和 golden 通过率趋势，不解释 prompt、源码或模型 prose。
- 用提交到仓库的 canonical baseline 拒绝 trusted-core manifest 漂移。
- 运行只接收外部契约和产物清单的 opt-in 独立真实模型 Evaluator。

**非目标：**

- 不增加常驻 Evaluator 服务、scheduler、HTTP endpoint、Planner 角色，也不改变普通 Task 完成语义。
- 离线 CI 不发 LLM 请求；不扩充或放宽 20 项 core；不自动更新 manifest baseline；Evaluator 不检查源码树。

## 决策

### Evaluation record 作为窄集成边界

从 golden 报告和可选的 audit JSONL 创建 `forgeagent.evaluation.v1` record。每次运行原子写入一个 JSON 文件，并维护有界索引，仅保留最近记录。聚合模块同时接受路径和纯 mapping，使表驱动测试不需要模型、用户 home 或 CLI。

相比评估数据库/服务，这更符合本地运行与离线 CI；相比把字段塞进 `GoldenSuite`，不会污染原本简洁的测试报告契约。

### 指标缺失时显式不可用

`first_pass_correctness` 是在一轮完成的已完成任务比例；`correction_rounds` 是已完成任务的额外轮数均值。cache 命中率仅在选中的成功 attempt 都有合法分母时按 token 加权计算。golden 通过率直接来自报告的 `passed`/`total`。空输入或不可用输入编码为 `null`，不伪造 `0` 或 `100`。

相比从 LLM 文本推导正确性，这保持了“机械终止”和“事实判断”分离的既有边界。

### Manifest 使用提交内 canonical baseline

Golden manifest 导出覆盖 scenario ID、title 和 real-model eligibility 的有序 fingerprint。仓库内 baseline fixture 保存批准的 20 项和 digest；runner preflight 遇到任意不一致就失败。更新 baseline 必须和 manifest、候选目录一起做显式源码变更，绝不能由 runner 自动写回。

仅检查 ID 集合不足以阻止替换函数或修改 real-model eligibility 后降低标准，因此采用完整 fingerprint。

### Evaluator 是独立、显式 opt-in 的 Task 会话

`evaluate` CLI 只有在用户显式选择配置模型后才解析并调用。它创建新的 Task，并使用专用 evaluator prompt；不带入 Generator conversation、Memory、project Skills 或 audit sink。输入契约只包含验收条件和位于显式 evaluation directory 下的有界相对产物清单。Evaluator 可复用现有只读/执行工具，但结构化结果必须给出观察证据，失败时指出未满足的期望。

相比传递 Generator 的 Task/Step 对象，这不会泄漏上下文；相比新增第二套服务协议，也不会在 M21/M22 前引入另一套编排系统。

## 风险 / 取舍

- [审计字段缺失或过旧] → 保留 `null`，报告跳过/无效事件，不声称有指标。
- [本地趋势记录损坏] → 严格 JSON 校验、有界文件名、原子写入；忽略无效历史并给出固定诊断。
- [产物可能包含 prompt injection] → 产物明确标注为不可信数据；Evaluator 不获得额外权限，且只在显式 opt-in 时运行。
- [LLM Evaluator 非确定] → 不进入 CI，并用已知 fail 注入做确定性检出测试；trusted core 仍由脚本判定。

## 迁移计划

无需迁移。既有 golden JSON 报告仍是合法输入；只有显式评估命令才写新记录。移除该能力时只需删除其专属评估目录，不影响既有运行。

## 未决问题

无。M20 范围和 opt-in 边界已由 `TECH_PATH.md` 与 M19 续接指引确定。

```

## openspec/changes/eval-evaluator/tasks.md

- Source: openspec/changes/eval-evaluator/tasks.md
- Lines: 1-21
- SHA256: 4b7908dc41907788a34f9e40dc5ede7b93fc1ed449a9dc4c1a818cd5ca5172ca

```md
## 1. Comet 与基线准备

- [ ] 1.1 初始化 `eval-evaluator` 的 Comet 状态，生成 OpenSpec handoff，并记录实施基准提交。
- [ ] 1.2 为精确的 20 项可信核心 manifest 增加仓库内 canonical fingerprint 与表驱动漂移测试。

## 2. 评估证据与指标

- [ ] 2.1 增加 `forgeagent.evaluation.v1` typed record、安全证据投影和纯函数指标聚合。
- [ ] 2.2 增加原子本地 record 持久化、有界趋势索引、兼容性检查和 CLI/报告渲染。
- [ ] 2.3 增加完整、缺失、无效及历史指标证据的离线表驱动测试。

## 3. 独立 Evaluator

- [ ] 3.1 定义有界 evaluator 契约、产物 manifest 校验和固定安全结果投影。
- [ ] 3.2 接入显式 opt-in CLI evaluator，使用不带 Generator 上下文、Memory 或 project Skills 的独立 Task 会话。
- [ ] 3.3 增加 mock-client 隔离测试与已知失败产物 fixture，断言 100% 检出；所有真实模型调用保持 opt-in。

## 4. 文档与完成

- [ ] 4.1 更新 README、威胁模型、文本协议或 CLI help、ACTION_PLAN 与 M20 里程碑证据。
- [ ] 4.2 运行定向测试、完整离线回归、golden 20/20、lint/format/build/OpenSpec 校验，并完成验证报告。

```

## openspec/changes/eval-evaluator/specs/evaluation-metrics/spec.md

- Source: openspec/changes/eval-evaluator/specs/evaluation-metrics/spec.md
- Lines: 1-44
- SHA256: 2534d8ea651d485fa577ac4e4cfa02c5a6acb911b8235866a10ecf7445ba86a8

```md
## ADDED Requirements

### Requirement: Evaluation metrics are aggregated from machine evidence
ForgeAgent SHALL create a versioned evaluation record by aggregating a golden runner
machine report and optional masked audit JSONL evidence. The record SHALL expose
golden pass rate, first-pass correctness, correction rounds, and cache-hit rate with
an explicit `null` value whenever its required input is unavailable or invalid.

#### Scenario: Complete machine evidence produces all metrics
- **WHEN** a valid golden report and completed-task audit events with valid token
  denominators are aggregated
- **THEN** the record contains deterministic values for all four M20 metrics and
  identifies the source report schema

#### Scenario: Missing metric inputs do not fabricate a value
- **WHEN** audit evidence is absent, malformed, or lacks a valid metric denominator
- **THEN** the affected metric is `null` and the golden pass rate remains derived
  solely from the valid golden report

### Requirement: Evaluation trends are local, bounded, and comparable
ForgeAgent SHALL atomically persist evaluation records to a caller-selected local
directory, retain a bounded chronological index, and compare a new record with the
latest compatible prior record without requiring a service, network request, or
model credential.

#### Scenario: A newer record is compared to its predecessor
- **WHEN** a valid record follows a valid record with the same evaluation schema
- **THEN** the trend output contains per-metric deltas and identifies both run IDs

#### Scenario: A corrupt historical record is encountered
- **WHEN** the trend directory contains an invalid or incompatible record
- **THEN** aggregation ignores that record with a fixed diagnostic and preserves
  valid current-record output

### Requirement: Evaluation data remains a safe projection
ForgeAgent SHALL accept only finite JSON scalar/container values in evaluation
records and SHALL NOT store prompts, model messages, raw tool arguments, absolute
paths, secret values, or unbounded audit detail.

#### Scenario: Unsafe audit payload is excluded
- **WHEN** an audit event includes an unrecognized parameter or a value outside the
  evaluation projection
- **THEN** the stored record contains no copy of that value and continues to report
  the independently available metrics

```

## openspec/changes/eval-evaluator/specs/golden-validation-core/spec.md

- Source: openspec/changes/eval-evaluator/specs/golden-validation-core/spec.md
- Lines: 1-23
- SHA256: 8268966a71fdb06ff96fb2b29da388f00a935e42a75c4a7538b6bcbeeda90f92

```md
## ADDED Requirements

### Requirement: Trusted-core standards are baseline protected
ForgeAgent SHALL validate the trusted-core manifest against a checked-in canonical
baseline before executing a suite or creating a report. The baseline SHALL cover the
ordered scenario IDs, titles, and real-model eligibility for exactly the approved
twenty scenarios. A mismatch SHALL fail preflight and SHALL NOT create a successful
report.

#### Scenario: A core scenario is removed or substituted
- **WHEN** the manifest differs from the approved baseline by an ID removal,
addition, substitution, or order change
- **THEN** golden preflight rejects the run before any scenario executes

#### Scenario: A scenario standard is lowered without changing its ID
- **WHEN** a trusted-core scenario title or real-model eligibility differs from the
approved baseline while its ID remains present
- **THEN** golden preflight rejects the run before any result is reported

#### Scenario: Approved manifest matches the baseline
- **WHEN** the checked-in trusted-core manifest matches its canonical baseline
- **THEN** existing offline and opt-in real-model preflight behavior remains
available without changing the approved 20-scenario set

```

## openspec/changes/eval-evaluator/specs/independent-evaluator/spec.md

- Source: openspec/changes/eval-evaluator/specs/independent-evaluator/spec.md
- Lines: 1-43
- SHA256: a5e44a3afe6a9429cd8acf85227004cacca029d551458249fc3a40b93651ad9e

```md
## ADDED Requirements

### Requirement: Independent evaluation is explicitly opt-in
ForgeAgent SHALL invoke an Evaluator only through an explicit command with a selected
configured real model. Offline golden CI and ordinary Task execution SHALL NOT
invoke, configure, or depend on the Evaluator.

#### Scenario: Offline golden validation runs without an Evaluator
- **WHEN** the trusted-core golden command runs without a real-model option
- **THEN** it performs only deterministic script checks and no Evaluator model call
is made

#### Scenario: Explicit evaluator invocation lacks credentials
- **WHEN** a user explicitly requests an evaluation but the selected model is not
usable
- **THEN** the command fails before inspecting artifacts or writing a pass result

### Requirement: Evaluator uses an isolated observable-artifact contract
ForgeAgent SHALL construct the Evaluator in a separate task session and provide only
the declared acceptance criteria plus a bounded manifest of artifacts rooted in the
evaluation directory. The Evaluator SHALL NOT receive the Generator's conversation,
Memory, Skill registry, implementation source tree, or an expanded tool permission.

#### Scenario: Evaluator receives no Generator session context
- **WHEN** evaluation runs after a Generator task
- **THEN** the Evaluator request contains the external contract and declared
artifacts but no Generator prompt, round feedback, or memory entries

### Requirement: Evaluator reports machine-readable acceptance evidence
ForgeAgent SHALL require an Evaluator outcome to state pass or fail and to include
bounded observed evidence. A failed outcome SHALL identify the unmet expected
behavior without leaking secrets or absolute host paths.

#### Scenario: Known incorrect artifact is rejected
- **WHEN** a deliberately incorrect artifact is evaluated against its declared
acceptance criterion
- **THEN** the Evaluator reports failure with the observed behavior and unmet
criterion

#### Scenario: Known fail injections are detected
- **WHEN** the opt-in evaluator verification fixture supplies each known failing
artifact case
- **THEN** every injected case is reported as failed

```
