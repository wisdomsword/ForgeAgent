# Comet Design Handoff

- Change: calibrate-collaboration-routing
- Phase: design
- Mode: compact
- Context hash: 83a8175d1178722e75df2cc4fc9f9acdb12d1d4f4018dcd6e6cad3828975179b

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/calibrate-collaboration-routing/proposal.md

- Source: openspec/changes/calibrate-collaboration-routing/proposal.md
- Lines: 1-33
- SHA256: d9a953e8e7ccbbcbd6a25e4c584029acfe26d3fb5beeca982e97f809f787999b

```md
## Why

M25 的冻结评估显示，当前“编程任务自动 Triad”策略没有稳定带来更高完成率，却显著增加模型调用、延迟和 token 成本；M26 又证明 Triad 只有在宿主提供并绑定当前 Candidate 的冻结检查时，才能避免自报通过造成的误完成。继续把普通编程任务无条件升级为 Triad，会把尚未证明的收益当成默认产品策略。

同时，README 仍把项目 MEMORY 描述为只读身份文件，与 M18 已交付的可写、可审计 Memory runtime 不一致；公开验证基线与平台文档仍停留在 M24 数字，Linux verified 状态说明还含过期矛盾。M27 需要一次性校准运行时合同与派生证据，避免路由、Memory 和公开报告继续分叉。

## What Changes

- **BREAKING**：编程任务不再自动升级为 Triad；未显式选择模式且宿主未提供冻结检查时统一使用 Single。
- 用户显式选择 `single`、`duo` 或 `triad` 时直接尊重选择，不再要求“较弱模式覆盖”确认；兼容配置 `allow_weaker_override` 不再改变路由结果。
- 宿主在路由时提供非空冻结检查定义时，可把未显式选择模式的任务路由到 Triad；只有候选文件就绪要求不构成完成证据，不触发自动 Triad。
- 修正 README 的 Memory 行为说明：项目 `.forgeagent/MEMORY.md` 由 Memory runtime 在准入后原子更新，并可由用户直接编辑；`--no-identity` 仍按身份合同禁用所有自定义身份文件和 Memory，`--no-memory` 仍是只关闭 Memory 的独立开关。
- 基于已冻结的 M25 raw 记录生成新的派生分析，不改写协议、raw、environment、`summary.json` 或原中立报告；新增按 model/mode 和 task family 的误完成率、运行时终止原因分类，并同时呈现质量、延迟和调用成本，形成 M27 路由决策依据。
- 更新 README、ACTION_PLAN、当前 pytest/OpenSpec/Golden 基线和平台矩阵；保留 Pipeline 50 / Job 249 的 Linux Docker verified 证据，并删除“仍 configured”的过期矛盾描述。

## Capabilities

### New Capabilities

- `collaboration-routing-evaluation`: 定义如何从冻结 M25 证据派生误完成率、终止原因、质量、延迟和调用成本，并约束这些派生指标对自动 Triad 策略的使用边界。

### Modified Capabilities

- `runtime-collaboration`: 将默认路由改为 Single，显式选择直接生效，只有宿主冻结检查证据可触发自动 Triad。
- `continuous-verification`: 当前基线必须来自最新可复验结果，平台 verified 状态必须与已记录执行证据保持一致且不得出现自相矛盾的状态描述。

## Impact

- 运行时：`src/forgeagent/collaboration.py` 及 CLI/HTTP/Loop 路由装配。
- 测试：协作路由、CLI/HTTP/Loop 集成、持续验证合同和 M25 派生分析测试。
- 评估：新增只读派生脚本与 M27 派生报告；M25 原始证据树保持字节不变。
- 文档：README、ACTION_PLAN、平台矩阵、运行时协议、威胁模型和 M27 里程碑。
- 不新增第三方依赖，不修改 M26 冻结证据，不重跑或覆盖 M25 真实模型批次，不自动恢复任何任务类别的 Triad 默认路由。

```

## openspec/changes/calibrate-collaboration-routing/design.md

- Source: openspec/changes/calibrate-collaboration-routing/design.md
- Lines: 1-107
- SHA256: 79513a7c3abe777e8864323066432ff4843ae019761fd14c1cdbe33e06967ad0

[TRUNCATED]

```md
## Context

M21 为具备编程特征的目标引入了确定性的自动 Triad 路由。M25 随后冻结了 Single、Duo、
Triad 共 270 次真实模型运行；M26 又增加了宿主拥有的冻结检查，把 Evaluator 裁决绑定到当前
Candidate。当前默认行为仍会在不知道是否具备这类证据时升级编程任务，并要求用户确认才能采用
显式选择的较弱模式，同时暴露 `allow_weaker_override` 兼容配置。

M25 raw 是不可变的历史证据。M27 可以从中生成新派生分析，但不得修改 protocol、raw、
environment、summary 或原中立报告。公开文档另有三处陈旧状态：MEMORY 被描述为只读、当前
测试基线仍停留在 M26 之前、Linux 表格在证据未同时记录两种架构时宣称 `amd64/arm64`，且同一
文档末尾仍残留 Linux 为 `configured` 的旧结论。

## Goals / Non-Goals

**目标：**

- 用户未选择模式且宿主没有绑定非空冻结检查时，一律默认 Single。
- 用户显式选择 Single、Duo 或 Triad 时直接尊重选择。
- 可信宿主拥有冻结检查定义时，可以不依赖模型或文本分类器选择 Triad。
- 生成可复算、加法式的 M25 派生结果，覆盖误完成、终止原因、质量、延迟与调用成本，并记录
  M27 路由裁决。
- 修正文档中的 MEMORY、当前基线和 Linux 证据表述，不改变对应运行时和历史证据。

**非目标：**

- 不修改 M26 check runner、Evaluator 完成门禁或冻结检查安全边界。
- 不增加意图分类器、额外模型调用、新配置面或新依赖。
- 不重跑 M25，也不重写任何 M25 冻结产物。
- 不为 solved rate 未超过 Single 的任务类别恢复自动 Triad。
- 不改变 M18 Memory runtime 或 `--no-identity`、`--no-memory` 合同。

## Decisions

### 1. 只根据显式选择与宿主证据路由

`resolve_collaboration_mode` 保留已有 goal 和兼容关键字参数，并增加一个表示宿主是否绑定非空
冻结检查的布尔事实。解析顺序如下：

1. 显式 `single`、`duo` 或 `triad` 原样返回，原因为 `explicit`。
2. 未显式选择且存在冻结检查时返回 Triad，原因为 `bound_checks`。
3. 其他情况返回 Single，原因为 `default`。

原编程文本分类器不再参与路由。继续保留无效的私有策略会增加误用风险和正则复杂度，因此删除
对应常量与 helper。`allow_weaker_override` 为源码和配置兼容继续接受，但不再影响结果。
`ModeDecision.override_required` 保留在稳定报告形状中，新路由下始终为 false。

未采用的方案：

- 保留编程分类但令其输出 Single：仍维护一个不影响决策的复杂组件。
- 把候选文件要求当作证据：文件存在不能证明验收行为通过，会削弱 M26 边界。
- 让冻结检查覆盖显式 Single 或 Duo：这与尊重用户显式选择冲突。

### 2. 路由器只接收证据事实

路由器只接收布尔值，不接收检查 argv、环境、路径、输出或快照。可信宿主仍负责创建并向 M26
runner 注册 `CheckDefinition`。这样可以保持路由审计有界，并避免 mode resolver 变成第二个
检查注册表。现有 CLI、REPL、Loop 和 HTTP 在初始路由点都没有冻结检查，因此普通默认行为变为
Single；已经拥有冻结检查的 library 或 harness 宿主可以传入该事实，显式模式始终优先。

### 3. 从不可变 M25 raw 派生 M27 指标

一个仅用标准库的脚本读取冻结 M25 protocol 和 terminal raw，复用 M25 独立验证边界，并在
M27 派生目录输出 JSON 投影与 Markdown 报告。它按 model/mode 和 task-family/mode 汇总：

- scheduled、runtime-completed 与 solved 运行数；
- 误完成：`runtime_completed == true && solved == false`，同时报告 scheduled 与
  runtime-completed 两种分母；
- 原样统计稳定 `runtime_reason`，不主观合并类别；
- logical model calls、provider attempts、延迟和 token 的总计与均值。

是否恢复某类自动 Triad，先判断该类别的 Triad solved rate 是否严格高于 Single。冻结 M25 中
没有类别通过该质量门：baseline 持平，bugfix、feature 和 refactor 均更低。因此 M27 不恢复
任何自动类别；延迟和调用成本作为支持证据报告，不引入任意权衡阈值。M25 早于 M26 证据绑定，
报告必须把误完成标记为历史结果，不得声称其衡量当前 evidence-bound Triad 的质量。

### 4. 把公开文档收窄到可证明结论

README 描述 M18 已有的 Memory runtime，而不是改代码。当前测试数字只在最终验证后更新。
Linux 平台行继续把 Pipeline 50 / Job 249 的 Linux Docker runner topology 记为 `verified`，但
不在缺少对应架构记录时宣称同时覆盖 amd64 与 arm64，并删除文末过期的 `configured` 句子。

```

Full source: openspec/changes/calibrate-collaboration-routing/design.md

## openspec/changes/calibrate-collaboration-routing/tasks.md

- Source: openspec/changes/calibrate-collaboration-routing/tasks.md
- Lines: 1-24
- SHA256: c7a6a186ff9c16a9a5d1e98a2548291777cf4dee1f1dc3f244f4d59e9528bee6

```md
## 1. 路由合同

- [ ] 1.1 添加 RED resolver 与审计测试，覆盖显式模式、默认 Single、冻结检查 Triad 和兼容输入
- [ ] 1.2 添加 RED CLI、REPL、Loop 与 HTTP 集成测试，证明无宿主证据的编程目标默认 Single
- [ ] 1.3 简化协作路由，删除过期编程分类，并使较弱模式覆盖确认不可达

## 2. 冻结 M25 派生分析

- [ ] 2.1 添加 RED 测试，覆盖不可变输入、误完成双分母、精确终止原因、分组成本指标和路由裁决
- [ ] 2.2 实现标准库 M27 派生脚本，并生成加法式 JSON 与 Markdown 产物
- [ ] 2.3 独立复算派生产物，并确认全部 M25 冻结输入保持字节不变

## 3. 文档与证据

- [ ] 3.1 修正 README Memory 行为，不改变 M18 runtime 语义
- [ ] 3.2 将 Linux verified 文字收窄到 Pipeline 50 / Job 249 证据，并删除过期 configured 矛盾
- [ ] 3.3 用 M27 策略、裁决和最终当前基线更新 README、ACTION_PLAN、威胁模型和平台文档

## 4. 验证与收尾

- [ ] 4.1 运行路由、集成、派生分析与文档合同定向测试
- [ ] 4.2 运行全量 pytest、OpenSpec strict、Golden 20/20、Ruff check/format、打包和 diff 检查
- [ ] 4.3 完成两轮最终自审与独立代码评审，修复全部确认问题并重复受影响验证
- [ ] 4.4 创建并归档 M27，更新 milestones/latest，并完成已授权的分支收尾流程

```

## openspec/changes/calibrate-collaboration-routing/specs/collaboration-routing-evaluation/spec.md

- Source: openspec/changes/calibrate-collaboration-routing/specs/collaboration-routing-evaluation/spec.md
- Lines: 1-34
- SHA256: 69e51f46203109562766ed71c6fb225e8a9466d086ec0a771a46c0e412ef1e95

```md
## ADDED Requirements

### Requirement: M25 派生分析保持冻结输入不可变
M27 派生分析 MUST 只读取冻结的 M25 protocol、terminal raw、environment、summary 和原报告，MUST 将新结果写入独立的 M27 派生目录，且 MUST NOT 修改、覆盖或重跑任何 M25 冻结输入。

#### Scenario: 生成 M27 派生报告
- **WHEN** 分析脚本针对冻结 M25 证据成功运行
- **THEN** 它生成新的机器可读投影和 Markdown 报告，而 M25 原 protocol、raw、environment、summary 与报告保持不变

#### Scenario: 冻结输入不完整或不一致
- **WHEN** M25 记录缺失、身份重复、字段类型无效或与冻结 summary 不一致
- **THEN** 派生分析非零退出且不得发布看似完整的结果

### Requirement: 误完成率与终止原因可复算
派生分析 MUST 将 `runtime_completed == true` 且 `solved == false` 定义为误完成，并 MUST 同时以全部调度运行和 runtime-completed 运行作为分母报告误完成率。终止原因 MUST 按原始稳定 `runtime_reason` 精确分类，不得主观合并不同原因。

#### Scenario: runtime 完成但任务未解决
- **WHEN** terminal raw 记录的 `runtime_completed` 为 true 且 `solved` 为 false
- **THEN** 该记录计入一次误完成，并进入两个明确标注分母的比率

#### Scenario: runtime 未完成
- **WHEN** terminal raw 记录的 `runtime_completed` 为 false
- **THEN** 该记录不计为误完成，但其 `runtime_reason` 仍进入终止原因分类

### Requirement: 路由决策比较质量、延迟与调用成本
派生分析 MUST 至少按 model/mode 与 task-family/mode 汇总 scheduled、runtime-completed、solved、误完成、`runtime_reason`、逻辑模型调用、provider attempts、延迟和 token 指标。自动 Triad 任务类别只有在冻结证据中 Triad solved rate 严格高于 Single 时才可进入恢复评估；未满足该质量门时 MUST 保持 Single 默认，并报告延迟和调用成本差异。

#### Scenario: 没有任务类别提高 solved rate
- **WHEN** 每个任务类别的 Triad solved rate 均低于或等于 Single
- **THEN** M27 不恢复任何任务类别的自动 Triad，并保留显式 Triad 与宿主冻结检查 Triad

#### Scenario: 历史证据早于 M26 绑定
- **WHEN** 报告解释 M25 的误完成与终止数据
- **THEN** 它明确标注 M25 早于 M26 冻结检查绑定，不把该结果表述为当前 evidence-bound Triad 的质量证明

```

## openspec/changes/calibrate-collaboration-routing/specs/continuous-verification/spec.md

- Source: openspec/changes/calibrate-collaboration-routing/specs/continuous-verification/spec.md
- Lines: 1-33
- SHA256: e55ef62f87eee62d97faf03bccfd0d05f2755f976c43c53d0921ad8f4e8b9176

```md
## MODIFIED Requirements

### Requirement: Evidence-driven platform matrix
The repository SHALL maintain a platform matrix that records release priority, current support state, evidence, prerequisites, limitations, and the next validation trigger for Linux Docker, Linux Podman, Windows, and local macOS Docker evidence. A `verified` claim MUST be limited to the operating system, architecture when recorded, runtime, and runner topology established by the cited execution, and the document MUST NOT contain a conflicting status for that same evidence.

#### Scenario: Platform has complete evidence
- **WHEN** the required commands pass on the named operating system, recorded architecture, runtime, and runner topology
- **THEN** the matrix may record only that proven platform tuple as verified with a dated evidence reference

#### Scenario: Evidence does not record every advertised architecture
- **WHEN** a successful platform run does not establish every architecture named by a broader matrix row
- **THEN** the verified row is narrowed to the recorded runner tuple rather than implying unverified architectures

#### Scenario: Platform has no complete evidence
- **WHEN** a platform is only planned, partially exercised, or blocked by known runtime assumptions
- **THEN** the matrix records it as scheduled, deferred, or unsupported and does not imply release support

#### Scenario: Release target changes
- **WHEN** maintainers promote Podman or Windows to a release target
- **THEN** a separate Comet change MUST define and verify the required compatibility work before the matrix status becomes verified

## ADDED Requirements

### Requirement: Public verification baseline reflects the latest completed run
README and the platform support document MUST state the latest completed full pytest, OpenSpec strict, and Golden results as the current repository baseline, MUST distinguish environment-dependent skips from passes, and MUST NOT present a historical milestone count as current.

#### Scenario: M27 verification completes
- **WHEN** the final M27 full verification commands finish
- **THEN** public baseline statements are updated from those command results and agree with each other

#### Scenario: Historical evidence remains referenced
- **WHEN** a milestone-specific older count is retained for audit history
- **THEN** it is labeled as historical and is not represented as the current repository baseline

```

## openspec/changes/calibrate-collaboration-routing/specs/runtime-collaboration/spec.md

- Source: openspec/changes/calibrate-collaboration-routing/specs/runtime-collaboration/spec.md
- Lines: 1-35
- SHA256: f5cdd7f7994c7cf0c82b401c5bfe6d7b01445004281f827c4fd3ef0a7ed7b182

```md
## MODIFIED Requirements

### Requirement: 协作模式使用隔离角色与串行编排
ForgeAgent SHALL 提供 `single`、`duo` 和 `triad` 三种运行模式。Duo MUST 按 Generator → Evaluator 串行执行；Triad MUST 按 Planner → 确认 → Generator ⇄ Evaluator 串行执行。每个角色 MUST 使用独立 Task、conversation、runtime、tool registry 与模型 client，不得共享另一角色的模型历史或可变执行状态。

#### Scenario: Duo 角色隔离
- **WHEN** 用户以 Duo 模式执行任务
- **THEN** Generator 与 Evaluator 分别创建独立 Task，Evaluator 只接收原始目标、冻结验收输入与允许根目录中的外部可观察产物

#### Scenario: Triad 严格串行
- **WHEN** 用户以 Triad 模式执行任务
- **THEN** Planner 完成且计划确认后才创建 Generator，Generator 提交后才创建 Evaluator，v1 不并行运行角色

#### Scenario: 单角色兼容
- **WHEN** 任务选择 single
- **THEN** 系统沿用既有单 Task 路径，不创建 Planner、Evaluator 或协作状态

### Requirement: 编程任务使用确定性路由且显式模式可审计
系统 MUST 在不调用额外模型或通用意图分类器的前提下确定协作模式。用户显式 `/single`、`/duo`、`/triad` 或 `--mode` MUST 直接生效；用户未显式选择且宿主为本次任务绑定非空冻结检查定义时 MUST 使用 Triad；其余任务，包括编程任务，MUST 默认使用 Single。候选文件就绪要求或任务文本分类不得单独触发自动 Triad。路由审计 MUST 记录稳定模式与原因，但不得记录目标、检查命令、路径或检查内容。

#### Scenario: 编程任务默认 Single
- **WHEN** 普通入口收到编程任务，用户未显式选择模式且宿主未绑定冻结检查
- **THEN** 系统选择 Single，不创建 Planner 或 Evaluator，也不为分类额外调用模型

#### Scenario: 宿主冻结检查触发 Triad
- **WHEN** 用户未显式选择模式且可信宿主为本次任务绑定至少一个冻结检查定义
- **THEN** 系统选择 Triad，并以不含检查内容的稳定原因记录该路由

#### Scenario: 显式模式直接生效
- **WHEN** 用户显式选择 Single、Duo 或 Triad
- **THEN** 系统直接使用该模式，不要求较弱模式覆盖确认，且显式选择优先于宿主证据默认值

#### Scenario: 候选文件要求不是完成证据
- **WHEN** 任务只配置候选文件就绪要求而没有冻结检查定义
- **THEN** 该配置不得触发自动 Triad

```
