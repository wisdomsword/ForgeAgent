# Comet Design Handoff

- Change: triad-mode
- Phase: design
- Mode: compact
- Context hash: a3771257646c128b83aeb3dfcfe11b11a26c675c9c8c58cf2d7f2b45cabecfb3

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/triad-mode/proposal.md

- Source: openspec/changes/triad-mode/proposal.md
- Lines: 1-34
- SHA256: 6b0104e8a518fedc4826bce51973a8c844588483203e8d339beb5a7c642a77bf

```md
## Why

ForgeAgent 的单角色完成判定仍由执行任务的 Generator 自我声明；即使 M13 已修正完成声明的时机，错误产物仍可能被同一会话误判为完成。M22 需要把规划、生成与验收拆成隔离角色，并以冻结、可验证的任务契约和独立 Evaluator 结果决定协作模式的完成状态。

## What Changes

- 新增运行时 Duo 模式：Generator 提交后由独立 Evaluator 以只读产物访问权验收；失败证据有界打回 Generator，超过配置的打回次数后以逐项报告停止。
- 新增运行时 Triad 模式：Planner 先生成只描述可观察行为与验收标准的冻结清单，经确认后由 Generator 逐项实现、Evaluator 逐项验收；清单不得静默删项或降标。
- 新增确定性编程任务路由：显式 `/duo`、`/triad` 与 `--mode` 保留；直接指定的编程类任务至少进入 Triad，无法安全确认的 headless 请求必须使用服务端预授权策略或拒绝。
- Duo/Triad 下 Generator 的 `completed` 仅表示提交验收，最终 `completed` 由 Evaluator 判定；普通单角色 Task 的完成语义和公开结果字段保持兼容。
- CLI、REPL、既有 HTTP `/tasks` 与 Loop 入口接入同一协作模式、预算、确认和安全投影；不新增 endpoint、daemon、数据库或第三方编排依赖。
- 新增角色生命周期、确认、打回与终态审计事件；只记录稳定枚举、计数、模型标识和清单摘要，不记录目标、清单正文、反馈正文、工具参数、文件内容或 secret。
- 新增离线 mock replay、路由表、清单完整性、打回边界与普通路径隔离测试；真实模型质量对比保持显式 opt-in。

## Capabilities

### New Capabilities

- `runtime-collaboration`: 定义 Duo/Triad 角色隔离、冻结计划、独立验收、证据打回、预算停止、完成语义与兼容性边界。

### Modified Capabilities

- `completion-integrity`: 协作模式下 Generator 完成声明降级为提交验收，只有独立 Evaluator 通过才能形成最终完成状态。
- `repl-interactive-input`: 增加 `/duo <goal>` 与 `/triad <goal>`，并保持 slash 候选、帮助、历史与普通输入行为一致。
- `http-task-service`: 既有 `/tasks` 请求可选择协作模式并执行 headless Planner 确认策略，同时保持普通 Task/Loop 请求兼容。
- `loop-execution`: Loop 可冻结协作模式并复用 checkpoint/handoff 作为角色交接载体，恢复时不得改变计划或降级模式。
- `audit-logging`: 增加有界、脱敏的协作角色生命周期、计划确认、打回与终态事件。

## Impact

- 主要影响 Task 上层的新协作编排模块、角色提示词组合、CLI/REPL、HTTP task service、Loop 装配、配置和审计投影。
- 复用现有 `Task`、M20 Evaluator 的外部可观察验收原则、M21 checkpoint store、模型注册表、sandbox、Memory/Skills 与确认门；不修改 Provider client 或 Step 工具反馈状态机。
- Duo/Triad 会增加模型调用、token 成本和延迟，因此默认只对显式模式及确定性识别的编程任务启用；其他任务继续单角色直通。
- 基础 CI 保持无 API key 可运行，普通 Task、20 项 trusted golden core 与 M20 opt-in Evaluator 的既有契约保持不变。

```

## openspec/changes/triad-mode/design.md

- Source: openspec/changes/triad-mode/design.md
- Lines: 1-94
- SHA256: 9932213c95801871e05bd30d7490272d44b295bd0c38e372fde969c7850ffa79

[TRUNCATED]

```md
## Context

ForgeAgent 当前的 `Task.run()` 创建一个 `Step`，单角色在独立 conversation 中执行工具并通过严格两阶段协议声明完成。M20 提供显式 opt-in 的独立 Evaluator facade，已验证只读 File 工具、外部可观察产物和有界报告边界；M21 在 Task 上层提供版本化 checkpoint、fresh Task 迭代、预算、取消和 CLI/HTTP runner 协议。M22 需要组合这些边界，但普通 Task、M20 离线评测与 single Loop 必须保持零行为变化。

## Goals / Non-Goals

**Goals:**

- 交付串行 Duo 与 Triad 运行模式，以独立 Evaluator 而非 Generator 自评决定最终完成。
- 交付冻结的 Planner 验收清单、交互确认和 headless 预授权/拒绝语义。
- 让 CLI、REPL、HTTP 与 Loop 使用同一模式路由、报告、预算、取消和审计契约。
- 使用确定性、可测的编程任务规则强制 Triad，不增加分类模型调用。
- 保持角色输入、状态、工具权限和公开输出有界、脱敏且可离线验证。

**Non-Goals:**

- 不引入通用 Agent team、DAG/workflow engine、角色并行、自动模型路由、新 endpoint、daemon、数据库或新依赖。
- 不让 Evaluator 修改产物，不让 Evaluator 反馈自动改变 Planner 规格，不自动生成或降低验收标准。
- 不保证跨进程 exactly-once，不序列化角色 conversation/runtime/tool 内部状态。
- 不把 M20 golden Evaluator 自动接入普通 Task；运行时协作是独立显式能力。

## Decisions

### 1. 在 Task 上方新增单文件串行 `CollaborationRunner`

新增 `collaboration.py` 承载严格模型、`CollaborationStore`、`SubmitPlanTool`、`SubmitEvaluationTool`、模式路由和 runner。Runner 接收角色 Task builder，每个角色/每次打回都构造 fresh Task/client/runtime/registry。Generator 继续使用现有完整工具集；Planner 只有 `SubmitPlan`；Evaluator v1 只有 `FileRead`、`FileList` 和 `SubmitEvaluation`，不注册默认 `Exec` 或任何写/网络工具，且 Evaluator tier 不高于 restricted。

备选是修改 `Step` 加角色状态；这会污染 single 完成语义并共享 conversation。另一个备选是通用 workflow engine；v1 只有固定串行状态机，YAGNI。

### 2. 角色结果通过结构化 Tool 提交，不解析自由文本

Planner 用 `SubmitPlan` 提交 `items[{id, behavior, acceptance}]`；Evaluator 用 `SubmitEvaluation` 提交与冻结 ID 一一对应的 `results[{id, passed, observed, expected, location}]`。工具参数由现有协议/Pydantic 严格校验，成功提交后角色仍需独立 standalone `completed: true` 才结束 Task，防止同轮工具与完成声明绕过反馈。

Planner 规范化后拒绝空项、重复 ID、未知字段、控制字符、超限内容和明显 HOW-only 验收文本。Evaluator 必须覆盖所有且仅覆盖冻结 ID；Duo 使用系统生成的单一 `goal` 验收项，不额外调用 Planner。

### 3. 协作状态采用独立版本化原子 JSON

状态位于 `<allowed_root>/.forgeagent/collaborations/<32hex>.json`，schema 为 `forgeagent.collaboration.v1`。模型包含 mode、status/phase、revision、冻结 goal、计划与 digest、角色模型/tier、max rejections、attempt counters、normalized usage、最后有界 verdict 和 stable stop reason。store 使用 M21 已验证的固定目录 fd、`O_NOFOLLOW`、相对 open/replace/fsync、revision compare 与大小上限，但不提前抽象通用 repository。

状态在 Planner 确认、Generator 提交、Evaluator 判定和终态边界提交。它不保存 conversation、完整模型回复、tool args、文件内容、secret 或绝对路径。CLI 一次协作默认创建状态以支持中断诊断；M22 不新增独立 resume CLI，Loop resume 才恢复协作状态，避免扩张入口。

### 4. 完成、打回与停止状态机固定

状态机：

```text
single -> existing Task
duo: generator -> evaluator(pass -> completed | fail -> generator)
triad: planner -> confirmation -> generator -> evaluator(pass -> completed | fail -> generator)
```

`max_rejections` 默认 2，含义是允许 Evaluator fail 后再次启动 Generator 的次数；因此最多 3 次 Generator、3 次 Evaluator。每次 fresh Generator 输入原 goal、冻结计划、此前已通过项和最后一轮有界失败证据。取消优先于角色结果；随后是不可恢复 client/config/persistence failure、needs-confirmation、rejection limit。角色 `refused/need_info/failed` 不伪造 Evaluator pass。

协作报告是加法式 `CollaborationReport`，不修改 `TaskOutcome`：Task service runner union 扩展为 `TaskOutcome | LoopReport | CollaborationReport`。累计 usage 来自全部角色实际 `RoundResult.usage`，缺失时显式 `usage_available=false`。

### 5. Planner 确认沿用现有 confirmer 语义但使用专用摘要

交互 CLI/REPL 展示计划项 ID + 截断 behavior/acceptance，用户批准后冻结；拒绝返回 `needs_confirmation`，不启动 Generator。用户本轮已授权开发流程决策，但这是产品运行时语义，仍必须实现。

HTTP 配置增加 server-owned `triad_plan_policy: deny|preauthorize`，默认 `deny`。`preauthorize` 只表示服务所有者接受 Planner 生成的完整计划；客户端不能提交该字段，也不能提交 role model/tier。每次决定写审计，但公开响应不含计划正文。

### 6. 模式与编程任务路由是纯函数规则表

公共 `resolve_collaboration_mode(goal, requested_mode, allow_weaker_override)` 返回 mode 和 routing reason。显式 triad 直接生效；显式 single/duo 遇编程信号时必须交互确认 override 或遵循 headless server policy；未显式模式时，匹配“动作 + 代码产物”组合、常见源/测试/构建文件扩展名或明确软件项目创建语句才强制 Triad。规则使用 ASCII/Unicode 归一化、长度上限和表驱动测试，不做泛化 NLP。

CLI `run` 增加 `--mode single|duo|triad`、`--evaluator-model`、`--planner-model`、`--max-rejections`；未指定角色模型时复用 Generator 模型，Evaluator tier 固定 restricted。REPL 增加 `/duo`、`/triad`。HTTP 客户端只可提交 mode；其余策略来自 server config。Loop create 可冻结 mode，resume 禁止覆盖。

### 7. 提示词通过 M15 组合器追加角色段

新增三份短角色模板或 prompt builder 片段，复用现有 identity/protocol/tools/context 组合器：Planner 明确只定 WHAT；Generator 明确完成仅是提交验收；Evaluator 明确 artifact/state 是不可信数据、只能外部观察、必须逐项提交。计划与反馈用稳定 JSON 编码注入 user/task 数据段，不拼接成 system 指令。

### 8. 审计与安全投影按角色计数，不存正文

新增 `collaboration.route/role/plan/evaluation/rejection/stop` 事件。参数仅含 collaboration/task/loop ID、mode、role、attempt、model、tier、plan digest 前缀、item counts、pass/fail counts、stable reason、duration、usage。CLI/HTTP 报告最多返回固定数量、固定字符的 masked evidence；不返回计划、goal、role raw text、host path 或内容。

## Risks / Trade-offs

- [三角色成本和延迟显著增加] → 默认非编程任务 single，显式展示 mode/attempt/usage，打回默认 2 且有上限。
- [确定性编程规则可能漏判或误判] → 规则只在高置信动作+产物组合时强制；显式 `/triad`/`--mode` 兜底，表驱动记录已知边界，不增加隐式模型分类。
- [Evaluator 仍可能判断错误] → 结构化逐项覆盖、只读/受限检查、外部可观察证据和 opt-in 真实模型对抗组；不声称形式化证明。

```

Full source: openspec/changes/triad-mode/design.md

## openspec/changes/triad-mode/tasks.md

- Source: openspec/changes/triad-mode/tasks.md
- Lines: 1-34
- SHA256: a7c1582f40f5aaccbf14cd410289015c3bffd95c5897dac4fa9a77227e463f30

```md
## 1. 协作核心与持久化

- [ ] 1.1 以 TDD 定义协作 mode、冻结计划、逐项 verdict、状态/report、usage 和 stable reason 的严格模型与不变量
- [ ] 1.2 实现 symlink-safe、revision-safe、原子且有界的 `CollaborationStore`，覆盖损坏、换绑、竞态和关闭路径
- [ ] 1.3 实现 `SubmitPlan`/`SubmitEvaluation` 结构化工具、角色专用 registry 与 prompt 数据投影
- [ ] 1.4 实现纯函数编程任务路由、显式模式冲突和表驱动中英文/文件产物边界测试

## 2. Duo 阶段

- [ ] 2.1 实现 fresh Generator/Evaluator Task builder、只读 Evaluator 能力和角色资源关闭
- [ ] 2.2 实现 Duo 提交验收、逐项判定、证据打回、默认 2 次 rejection 上限、取消和失败优先级
- [ ] 2.3 添加离线 mock replay：错误完成被拦截、拒绝后修复通过、反复拒绝停止、角色异常与 usage 聚合
- [ ] 2.4 完成 Duo 专项审查并修复 Critical/Important 问题后再进入 Triad

## 3. Triad 阶段

- [ ] 3.1 实现 Planner 计划生成、WHAT-only 校验、规范化 digest、交互确认和 headless deny/preauthorize
- [ ] 3.2 实现冻结计划完整性守卫、Triad 逐项 Generator/Evaluator 流转与计划漂移 fail-closed
- [ ] 3.3 添加离线 mock replay：确认/拒绝、禁删改降标、逐项通过、打回修复和 Planner/Generator/Evaluator 隔离
- [ ] 3.4 完成 Triad 核心专项审查并修复 Critical/Important 问题后再接入口

## 4. CLI、REPL、HTTP 与 Loop 接入

- [ ] 4.1 为 `run` 增加模式/角色模型/打回参数，为 REPL 增加 `/duo`、`/triad`、help/completion 和安全输出
- [ ] 4.2 扩展 HTTP strict schema、server-owned 协作策略、runner union、状态/终态投影、取消/容量/TTL 和安全错误
- [ ] 4.3 扩展 Loop checkpoint/runner 冻结协作 mode、state ID、计划 digest、累计预算和 resume 一致性，保持 single Loop 不变
- [ ] 4.4 添加 CLI/REPL/HTTP/Loop 集成、普通路径零变化、并发隔离和审计静态契约测试

## 5. 文档、评审与验证

- [ ] 5.1 更新 README、文本协议、HTTP 文档、威胁模型、配置示例、ACTION_PLAN 与 opt-in golden 对比说明
- [ ] 5.2 运行专项/全量 pytest、trusted golden 20/20、ruff、build、OpenSpec strict 与 diff check
- [ ] 5.3 委派独立 code review，对完整 M22 diff 做两轮自审，发现问题立即修复并重跑受影响门禁
- [ ] 5.4 产出 M22 验证报告与 `milestones/milestone_022.md`，更新 latest，完成主分支提交和 OpenSpec 归档

```

## openspec/changes/triad-mode/specs/audit-logging/spec.md

- Source: openspec/changes/triad-mode/specs/audit-logging/spec.md
- Lines: 1-21
- SHA256: 076dadcb04bf9898040e501bf76a0aeb6345a2d90faf96488ae89c999b4e39c0

```md
## ADDED Requirements

### Requirement: Collaboration lifecycle events are attributable and minimally disclosing
The collaboration path MUST emit audit events for mode routing, role start/outcome, plan submission/confirmation, evaluation verdict, rejection and terminal stop. Events MUST carry task/Loop correlation, stable mode/role/phase/model identifiers and bounded counters while omitting the goal, plan text, evaluation feedback text, prompts, tool arguments, artifact contents, credentials and absolute paths.

#### Scenario: Role lifecycle is audited
- **WHEN** Planner, Generator or Evaluator starts and reaches an outcome
- **THEN** events record role, mode, attempt, model identifier, stable status, duration and normalized usage without conversation content

#### Scenario: Plan confirmation is audited
- **WHEN** an interactive user or headless policy approves, denies or cannot confirm a Planner plan
- **THEN** one event records the decision, plan item count and digest prefix without plan text or goal

#### Scenario: Evaluation rejection is audited
- **WHEN** Evaluator rejects one or more acceptance items
- **THEN** one event records pass/fail counts, rejection number and bounded reason enums without actual/expected text or file contents

#### Scenario: Collaboration stops
- **WHEN** collaboration completes, exhausts rejection attempts, fails, needs confirmation or is cancelled
- **THEN** one event records mode, terminal reason and cumulative counters, and serialization failure follows existing audit-degraded behavior


```

## openspec/changes/triad-mode/specs/completion-integrity/spec.md

- Source: openspec/changes/triad-mode/specs/completion-integrity/spec.md
- Lines: 1-21
- SHA256: b40b222cd884545cb19818f99a20dae68bef28930abc370143edbc76a03a7a37

```md
## MODIFIED Requirements

### Requirement: Completion requires a standalone final response
ForgeAgent SHALL mark a single-role task complete only from a response that explicitly declares completion and contains neither tool calls nor protocol parse errors. In Duo/Triad mode, the same standalone Generator response SHALL mean only "submitted for evaluation"; ForgeAgent MUST mark the collaborative execution complete only after an independent Evaluator returns a valid structured pass for every frozen acceptance item.

#### Scenario: Standalone completion after tool feedback
- **WHEN** a tool-bearing response has been processed and a later response contains no tools, no parse errors and declares `completed: true` in single mode
- **THEN** ForgeAgent marks the task complete using the later response

#### Scenario: Standalone response does not declare completion
- **WHEN** a response contains no tools and no parse errors but does not declare completion
- **THEN** ForgeAgent does not fabricate a completed status

#### Scenario: Collaborative Generator submits for evaluation
- **WHEN** a Duo/Triad Generator produces an otherwise eligible standalone `completed: true` response
- **THEN** ForgeAgent starts an isolated Evaluator and does not yet report the collaborative execution as completed

#### Scenario: Evaluator rejects submitted work
- **WHEN** the independent Evaluator reports one or more frozen acceptance items as failed
- **THEN** ForgeAgent keeps the collaborative execution incomplete and either starts a bounded correction attempt or stops with a rejection report


```

## openspec/changes/triad-mode/specs/http-task-service/spec.md

- Source: openspec/changes/triad-mode/specs/http-task-service/spec.md
- Lines: 1-54
- SHA256: 6fd56d7205aae730a7a2ea2265fe1cfbe692e54ed4c63c4c35af796adf8d0fa5

```md
## MODIFIED Requirements

### Requirement: Authenticated task submission
The service MUST expose an asynchronous task submission endpoint that accepts a strict JSON request schema containing a goal and only explicitly approved low-risk run options, and MUST require a configured static bearer token for every task-management request. The request MAY select ordinary Task, Duo, Triad, or M21 Loop mode and MAY request resume by a strict server-owned Loop identifier. Collaboration model/tier policy, Planner confirmation policy, security-sensitive execution policy, sandbox/path authority, checkpoint paths, identity, confirmer, credentials, and frozen resume budgets MUST remain server-owned.

#### Scenario: Valid submission
- **WHEN** a client sends a valid bearer token and a JSON body containing a non-empty goal without Loop or collaboration mode
- **THEN** the service creates one ordinary task unless deterministic programming-task routing requires Triad, returns a unique task identifier, and does not wait for completion

#### Scenario: Valid collaborative submission
- **WHEN** a client sends a valid bearer token, non-empty goal and allowed `duo` or `triad` mode
- **THEN** the service creates one collaborative task using server-owned role models, tiers, rejection limits and confirmation policy, returns a unique task identifier, and does not wait for completion

#### Scenario: Headless Triad confirmation is unavailable
- **WHEN** a Triad request requires Planner confirmation and the server has not configured preauthorization for the submitted plan
- **THEN** the service rejects or terminates the task with a stable needs-confirmation result without starting Generator

#### Scenario: Valid Loop submission
- **WHEN** a client sends a valid bearer token, a non-empty goal, Loop mode, frozen collaboration mode if any, and valid low-risk Loop budgets
- **THEN** the service creates one Loop task, assigns a server-owned Loop identifier and checkpoint location, returns a unique task identifier, and does not wait for Loop completion

#### Scenario: Valid Loop resume submission
- **WHEN** a client submits Loop resume with a syntactically valid server-owned Loop identifier and no conflicting goal, collaboration mode or budgets
- **THEN** the service resolves only the matching checkpoint under its configured Loop directory and asynchronously resumes that Loop with its frozen mode and plan

#### Scenario: Missing or invalid token
- **WHEN** a client sends a task-management request without the configured token or with a different token
- **THEN** the service returns an authentication error and does not disclose task, Loop, plan or configuration existence, values, or the expected token

#### Scenario: Invalid request body
- **WHEN** an authenticated client submits a body with a missing, empty, or invalidly typed goal for a new task, an unknown mode, or combines resume with a new goal, mode or budgets
- **THEN** the service returns a structured client error and creates no task

#### Scenario: Security-sensitive request option is rejected
- **WHEN** an authenticated client submits role model/tier, rejection limit, Planner approval, backend, allowed_root, checkpoint_path, container_image, identity/trust, confirmer, credential fields, or attempts to override frozen resume configuration
- **THEN** the service rejects the request without creating a task or changing server-owned policy

#### Scenario: Service starts without a usable token or with a non-loopback bind
- **WHEN** the configured token is missing/blank or the configured bind address is not loopback
- **THEN** the HTTP service refuses to start and exposes no task-management listener

## ADDED Requirements

### Requirement: Collaborative task results use a safe bounded projection
The service MUST identify `duo` and `triad` as public execution modes and project collaborative terminal reports without exposing full plans, rejection feedback, prompts, artifact contents or role conversations.

#### Scenario: Running collaborative task query
- **WHEN** an authenticated client queries an accepted collaboration that is still planning, generating or evaluating
- **THEN** the response reports running state, public mode and current stable phase without fabricating acceptance results

#### Scenario: Terminal collaborative task query
- **WHEN** a collaboration completes, exhausts rejection attempts, needs confirmation, fails or is cancelled
- **THEN** the response contains stable status/reason/mode, role and acceptance counters, normalized usage and bounded masked evidence summaries


```

## openspec/changes/triad-mode/specs/loop-execution/spec.md

- Source: openspec/changes/triad-mode/specs/loop-execution/spec.md
- Lines: 1-21
- SHA256: 5899939a9d71156b2d637e5fadeb35fae4aa49baab2014ec6724fc3ae3cf9465

```md
## MODIFIED Requirements

### Requirement: 失败反馈环按冻结模式有界收敛
每个 Loop 迭代 SHALL 按 checkpoint 中冻结的运行模式执行一个普通 Task 或一个 Duo/Triad 协作 runner；非完成结果 SHALL 生成脱敏、有界的失败摘要并与最近 checkpoint 交接信息一起进入下一迭代。Loop MUST 在停止预算内尝试修正，MUST 对明确不可恢复的配置、鉴权、checkpoint、计划完整性或策略错误立即停止，并 MUST NOT 在 resume 时改变协作模式、已确认计划、角色安全策略或完成标准。

#### Scenario: 可恢复失败后修正成功
- **WHEN** 一个普通 Task 或协作 runner 因工具失败、Evaluator 拒绝、上下文限制或轮次耗尽而未完成，但尚未命中 Loop 停止条件
- **THEN** 下一迭代收到有界失败证据和继续要求，最终按冻结模式完成时 Loop 写入 completed 终态

#### Scenario: 反复失败不无限重试
- **WHEN** 每个迭代均未完成且达到连续失败、轮次、token 或墙钟任一上限
- **THEN** Loop 停止并留下可诊断报告，不再调用模型

#### Scenario: Single Loop 保持既有边界
- **WHEN** Loop checkpoint 冻结为 single 模式
- **THEN** 系统不实例化 Planner 或 Evaluator，Loop 完成仍以现有 Task 的严格 completed 语义为准

#### Scenario: Collaborative Loop resume 保持计划
- **WHEN** Duo/Triad Loop 从有效 checkpoint 恢复
- **THEN** 系统验证冻结 mode 与计划摘要，继续角色打回/迭代计数，且不允许调用方覆盖完成标准


```

## openspec/changes/triad-mode/specs/repl-interactive-input/spec.md

- Source: openspec/changes/triad-mode/specs/repl-interactive-input/spec.md
- Lines: 1-17
- SHA256: 8d919bb861df7ac4c876c2ce31df8168edf0cc9ba44481e9ca78ec046269c7f3

```md
## ADDED Requirements

### Requirement: REPL exposes explicit Duo and Triad commands
The REPL command table SHALL include `/duo <goal>` and `/triad <goal>` using the same completion, help, history and input compatibility paths as existing slash commands. Missing goals MUST produce bounded usage guidance without starting a task.

#### Scenario: Duo slash command
- **WHEN** a user submits `/duo verify this report`
- **THEN** the REPL removes the command prefix and runs the remaining goal in Duo mode

#### Scenario: Triad slash command
- **WHEN** a user submits `/triad implement the parser`
- **THEN** the REPL removes the command prefix and runs the remaining goal in Triad mode, including Planner confirmation

#### Scenario: Slash candidates and help
- **WHEN** a user types `/d`, `/t`, or requests `/help duo`
- **THEN** candidates and help are derived from the shared command table and describe the collaboration cost and semantics


```

## openspec/changes/triad-mode/specs/runtime-collaboration/spec.md

- Source: openspec/changes/triad-mode/specs/runtime-collaboration/spec.md
- Lines: 1-88
- SHA256: b71f3682bfe11700be6d66eceb225e15ecbea9bd1a8c2831cd92348c49ffefe8

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: 协作模式使用隔离角色与串行编排
ForgeAgent SHALL 提供 `single`、`duo` 和 `triad` 三种运行模式。Duo MUST 按 Generator → Evaluator 串行执行；Triad MUST 按 Planner → 确认 → Generator ⇄ Evaluator 串行执行。每个角色 MUST 使用独立 Task、conversation、runtime、tool registry 与模型 client，不得共享另一角色的模型历史或可变执行状态。

#### Scenario: Duo 角色隔离
- **WHEN** 用户以 Duo 模式执行任务
- **THEN** Generator 与 Evaluator 分别创建独立 Task，Evaluator 只接收原始目标、冻结验收输入与允许根目录中的外部可观察产物

#### Scenario: Triad 严格串行
- **WHEN** 用户以 Triad 模式执行任务
- **THEN** Planner 完成且计划确认后才创建 Generator，Generator 提交后才创建 Evaluator，v1 不并行运行角色

#### Scenario: 单角色兼容
- **WHEN** 任务选择 single 且未命中强制 Triad 路由
- **THEN** 系统沿用既有单 Task 路径，不创建 Planner、Evaluator 或协作状态

### Requirement: Planner 生成冻结且不可降级的验收清单
Triad Planner MUST 只定义 WHAT：每个清单项包含稳定 ID、可观察行为与验收标准，不得指定实现步骤。计划提交后系统 MUST 规范化并计算摘要；确认后的条目、顺序和标准 MUST 冻结，后续角色不得删除、替换、重排或降低标准。

#### Scenario: 合法计划确认
- **WHEN** Planner 提交非空、唯一 ID 且全部字段有界的计划，并由交互用户确认或由 headless 预授权策略接受
- **THEN** 系统冻结规范化计划和摘要并允许 Generator 开始

#### Scenario: Planner 尝试定义实现方法
- **WHEN** Planner 清单把工具调用、库选择或具体实现步骤当作验收标准
- **THEN** 系统通过结构化反馈要求其改写为外部可观察行为，不接受该版本计划

#### Scenario: 后续角色改变计划
- **WHEN** Generator、Evaluator、Loop resume 或打回轮次提供缺项、改项、重排或不同摘要的计划
- **THEN** 系统拒绝变更并保持已确认计划不变

### Requirement: Evaluator 独立验收并决定协作完成
在 Duo/Triad 模式中，Generator 的严格 `completed` SHALL 仅表示提交验收。Evaluator MUST 使用结构化逐项结果判定外部可观察产物；只有所有要求通过时协作结果才能为 completed。Evaluator 默认 MUST 使用 restricted tier，写工具 MUST 不可用，且其模型和 tier MAY 与 Generator 独立配置但不得扩大服务端或 CLI 所有者授予的权限。

#### Scenario: Generator 错误完成被拦截
- **WHEN** Generator 声明完成但 Evaluator 发现至少一项外部可观察行为不满足
- **THEN** 协作结果保持未完成并生成有界、脱敏的实际行为、期望行为和定位证据

#### Scenario: 全部验收通过
- **WHEN** Evaluator 对冻结计划或 Duo 验收目标的全部项目返回 pass
- **THEN** 系统返回 completed，并保留 Generator 与 Evaluator 的轮次、usage 和验收计数投影

#### Scenario: Evaluator 无写权限
- **WHEN** Evaluator 尝试修改被验收产物
- **THEN** 请求被工具注册表、确认门或 sandbox 拒绝，且该尝试不能形成 pass

### Requirement: 打回环有界且证据驱动
Evaluator 失败 SHALL 把有界、脱敏、逐项证据返回新的 Generator Task；每次修正 MUST 使用新的 Generator conversation，并保留原始目标与冻结计划。系统 MUST 支持可配置的最大打回次数，默认 2；达到上限、取消、角色失败或预算不足时 MUST 以稳定原因停止，不得无限重试。

#### Scenario: 一次打回后修复通过
- **WHEN** 首次 Evaluator 拒绝且下一 Generator 根据证据修复产物，随后 Evaluator 全部通过
- **THEN** 系统返回 completed，并报告一次 rejection 和两次 evaluation attempt

#### Scenario: 打回次数耗尽
- **WHEN** Evaluator 连续拒绝达到最大打回次数后仍有未通过项目
- **THEN** 系统以 `rejection_limit` 停止，返回逐项有界报告且不再调用 Generator

#### Scenario: 角色调用失败或取消
- **WHEN** 任一角色返回鉴权错误、不可恢复失败或收到协作取消
- **THEN** 系统在下一安全边界停止，以稳定角色和原因标识终态，并关闭已创建资源

### Requirement: 编程任务使用确定性路由且显式模式可审计
系统 MUST 使用有界、表驱动的产物类型与动作规则识别直接要求创建或修改代码、测试、构建配置或软件项目的任务，并将其路由到 Triad。用户显式 `/duo`、`/triad` 或 `--mode` MUST 被识别；显式 single 与强制 Triad 冲突时 MUST 提示确认，headless 无确认且无预授权时 MUST 拒绝。该规则不得调用额外模型或充当通用意图路由器。

#### Scenario: 编程任务强制 Triad
- **WHEN** 普通入口收到确定性规则明确识别的编程任务且用户未显式选择更强模式
- **THEN** 系统选择 Triad 并在 Planner 确认后执行

#### Scenario: 非编程任务默认 single
- **WHEN** 任务不匹配编程规则且用户未显式选择 Duo/Triad
- **THEN** 系统保持 single，不为分类额外调用模型

#### Scenario: 显式 single 冲突
- **WHEN** 用户显式要求 single 但任务匹配强制 Triad
- **THEN** 交互入口要求明确确认风险；headless 入口仅在服务端预授权该覆盖时允许，否则拒绝

### Requirement: 协作报告稳定、有界且兼容
协作执行 MUST 返回加法式稳定报告，包含 mode、终态、稳定原因、角色尝试计数、计划项计数、通过/失败计数、打回次数、累计轮次与 normalized usage。报告 MUST NOT 包含完整目标、计划正文、模型回复、工具参数、文件内容、绝对路径、credential 或未掩码证据。普通 `TaskOutcome` 的既有字段与语义 MUST 保持兼容。


```

Full source: openspec/changes/triad-mode/specs/runtime-collaboration/spec.md
