# Comet Design Handoff

- Change: bind-collaboration-completion-evidence
- Phase: design
- Mode: compact
- Context hash: 4b9db4c42b42a1a0bb09c6217c255b3048ce676bf3f31ff485abf61cb4ad39ee

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/bind-collaboration-completion-evidence/proposal.md

- Source: openspec/changes/bind-collaboration-completion-evidence/proposal.md
- Lines: 1-28
- SHA256: 6ec51937d0cc3f42de31e4109b865b4cbc0a8d3b184cc9f003fe39e3cd1f9551

```md
## Why

M25 真实评测暴露出 Duo/Triad 的完成判定可以仅依赖 Evaluator 自报的逐项 `pass`，即使宿主冻结检查未运行、失败或已经对应旧 Candidate，协作仍可能错误返回 `completed`。M26 需要把完成状态与当前 Candidate 的可验证检查证据绑定，优先降低 false completion。

## What Changes

- 当宿主注册 Evaluator 检查时，只有当前 Candidate 对应的全部冻结检查均已通过，且冻结验收项全部通过，`SubmitEvaluation` 才能提交全通过 verdict。
- 将 `RunCheck` 产生的结果绑定到当前 Generator attempt 和被检查的 Candidate 快照；Candidate 变化、证据缺失、检查失败或证据过期时拒绝全通过提交。
- 保留证据驱动的提前拒绝：Evaluator 发现任一验收项失败时，无需先运行全部检查即可提交失败 verdict。
- 恢复时采用 fail-closed 语义，不复用进程内旧检查证据；待验收 Candidate 重新运行 Evaluator 时必须重新取得检查证据。
- 未注册宿主检查时保持现有 Duo/Triad Evaluator 行为兼容。
- 增加结构化、脱敏的审计与验证覆盖，证明检查结果不能由模型伪造，也不能跨 Candidate 复用。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`: 将 Evaluator 的全通过 verdict 与当前 Candidate 的宿主冻结检查证据绑定，并规定失效、恢复和无检查兼容语义。

## Impact

- 主要影响 `src/forgeagent/collaboration.py` 中 Evaluator 工具注册、检查执行和提交门，以及 `src/forgeagent/check_runner.py` 中 Candidate 快照标识。
- 更新协作运行时 OpenSpec delta、相关单元测试、恢复/并发测试和 M26 独立验证证据。
- 不新增依赖，不改变 single 模式，不调整默认协作路由，不修改 M23/M25 历史评测产物。

```

## openspec/changes/bind-collaboration-completion-evidence/design.md

- Source: openspec/changes/bind-collaboration-completion-evidence/design.md
- Lines: 1-76
- SHA256: a05f91e1911a91b3f5e2d0c260f05cb6d3f1c6cd59dc0ecf5716d2d6c2db084e

```md
## Context

当前 Evaluator registry 会为一次待验收 Candidate 同时注册 `RunCheck` 和 `SubmitEvaluation`，但两者没有共享的可信状态。`RunCheck` 只把检查输出反馈给模型，`SubmitEvaluation` 只验证冻结计划 ID，因此模型可以不运行检查、忽略失败检查或复用旧检查描述后提交全通过 verdict。协作状态可以在 evaluator phase 恢复，这要求证据语义既能绑定当前 Generator attempt，又不能把不可验证的进程内执行结果错误复用到恢复后的 Task。

约束包括：检查命令和参数继续由宿主冻结；Evaluator 不获得写工具；检查仍在临时项目副本中运行；输出必须有界且脱敏；无检查配置保持兼容；不新增依赖或通用命令面。

## Goals / Non-Goals

**Goals:**

- 只有当前 Candidate 的全部宿主冻结检查通过且全部冻结验收项通过时，才允许提交全通过 verdict。
- 检查证据同时绑定当前 Generator attempt 与实际被检查的项目快照。
- Candidate 在检查后变化时使旧证据失效，并给 Evaluator 可恢复的结构化反馈。
- 恢复时 fail closed：不持久化或复用无法证明仍对应当前执行环境的旧检查证据。
- 保持提前拒绝、无检查兼容、隔离执行和脱敏审计语义。

**Non-Goals:**

- 不调整编程任务的 single/duo/triad 默认路由，该项留给 M27。
- 不重写 M23/M25 历史评测或把旧结果重新分类。
- 不引入任意命令执行、Evaluator 写能力、新依赖或通用证据框架。
- 不保证对拥有宿主文件系统写权限的恶意并发进程提供事务级文件快照；本变更保证检测正常的 Candidate 变更并 fail closed。

## Decisions

### 1. 在单次 Evaluator registry 内共享最小检查证据表

`build_evaluator_registry` 为当前待验收 Candidate 创建一份仅宿主持有的内存证据表，并将同一实例交给 `RunCheckTool` 与 `SubmitEvaluationTool`。`RunCheckTool` 只按冻结 ID 执行检查并覆盖该 ID 的最新结果；模型不能提交状态、摘要、命令或证据字段。

证据表的生命周期等于当前 Evaluator Task。新的 Generator attempt、进程恢复或重新构造 registry 都从空证据开始，因此旧 attempt 的结果不能被复用。

备选方案是把证据写入 `CollaborationState`。该方案会增加 schema、迁移、并发保存和恢复时环境一致性问题，而恢复后仍需要重新确认代码与解释器环境，持久化并不能安全省略重跑，因此不采用。

### 2. 用项目快照摘要绑定检查实际输入

检查 runner 在临时副本创建后，对与复制规则一致的非忽略文件树计算确定性 SHA-256 摘要，并把摘要作为仅供宿主门禁使用的结果元数据返回；Evaluator 反馈不展示摘要。一次全通过提交前，`SubmitEvaluationTool` 重新计算当前 allowed root 的同规则摘要。

所有要求检查的最新结果必须为 `passed`，必须具有同一摘要，且该摘要必须等于提交时的当前摘要。检查之间或检查后发生文件变化时，旧结果会因摘要不一致而失效，Evaluator 必须在当前快照上重新运行全部检查。

备选方案是在检查前后各计算宿主目录摘要而不绑定临时副本。该方案存在检查复制发生在两个摘要之间的歧义，不能证明实际执行输入，故不采用。另一个备选方案是让所有检查共享一个长期临时副本，会扩大 runner 生命周期和清理复杂度，M26 不需要。

### 3. 证据门只约束全通过 verdict

当 Evaluator 提交的任一冻结计划项为失败时，`SubmitEvaluation` 继续允许保存拒绝 verdict，不要求先运行所有检查。这保留了通过只读观察即可提前拒绝明显缺失或错误 Candidate 的能力。

当所有计划项均为通过时，存在冻结检查配置就必须通过证据门；缺失、失败、超时、取消、复制错误、启动错误、摘要缺失或摘要过期均返回结构化失败，且不保存 verdict、不递增 Evaluator attempt。没有冻结检查时沿用当前行为。

备选方案是在 `SubmitEvaluation` 内自动运行全部检查。该方案会隐藏检查成本，弱化模型根据检查反馈定位问题的能力，并把提交工具变成不可控的长操作，因此不采用。

### 4. 恢复时重新取得证据，不持久化执行结果

协作状态继续只持久化 Candidate attempt 和最终 verdict。若从 evaluator phase 且 verdict 为空恢复，Runner 构造新的空证据 registry，Evaluator 必须重新运行检查。若 verdict 已经成功保存，现有恢复逻辑直接处理 verdict；因为保存前已通过证据门，不需要重复运行模型或检查。

该选择保持状态 schema 兼容，也明确避免把旧进程、旧环境或中断前的部分检查误当作当前证据。

### 5. 审计只记录安全的检查元数据

每次合法冻结检查执行额外发出结构化协作检查事件，仅记录 check ID、当前 Generator attempt、稳定状态和耗时；不记录 argv、绝对路径、文件内容、完整输出或快照摘要。现有 `tool.operation` 事件继续记录工具级成功/失败。

## Risks / Trade-offs

- **[大型项目摘要增加 I/O]** → 检查本身已经复制完整非忽略项目树；摘要复用相同范围，仅在检查和全通过提交时计算，不引入后台扫描或缓存。
- **[正常外部写入使已通过检查失效]** → 这是预期的 fail-closed 行为；反馈明确要求在稳定的当前快照上重跑检查。
- **[宿主级恶意并发写仍可能制造 TOCTOU]** → M26 不把应用层摘要升级为文件系统事务或安全边界；检查隔离和 allowed root 约束保持不变，并通过前后快照一致性覆盖正常变更。
- **[恢复后重复检查增加成本]** → 以可证明的完成完整性优先于复用不可靠证据；现有检查有冻结超时，成本有界。

## Migration Plan

1. 先增加快照摘要和证据门的失败测试，再实现最小运行时改动。
2. 保持 `CollaborationState` schema 和无检查路径不变，因此无需数据迁移。
3. 通过单元、恢复、并发、完整测试和 M26 小规模真实协作验证后归档 delta spec。
4. 如需回滚，可回退 M26 运行时改动；既有持久状态仍可由旧版本读取。

## Open Questions

无。M27 的模式路由校准和未来是否持久化可验证执行证明均不属于本变更。

```

## openspec/changes/bind-collaboration-completion-evidence/tasks.md

- Source: openspec/changes/bind-collaboration-completion-evidence/tasks.md
- Lines: 1-24
- SHA256: 638b4b9f8ce2313b13daa6c0f9f7d2a306c51a3c27c6989d89225b77eadbb40f

```md
## 1. 证据绑定基础

- [ ] 1.1 为检查临时副本计算与复制规则一致的确定性 Candidate 快照摘要，并补充摘要稳定性、忽略项和错误路径测试
- [ ] 1.2 增加当前 Evaluator Task 私有的检查证据表，按冻结检查 ID、Generator attempt、状态和快照记录最新结果

## 2. Evaluator 完成门

- [ ] 2.1 让 `RunCheck` 写入宿主证据表并只向模型返回既有有界脱敏结果
- [ ] 2.2 让 `SubmitEvaluation` 在全通过 verdict 前验证全部冻结检查均对同一当前 Candidate 通过
- [ ] 2.3 保留失败 verdict 提前提交、无检查兼容和恢复后强制重跑语义
- [ ] 2.4 增加不含命令、路径、输出或摘要的结构化检查审计元数据

## 3. 验证覆盖

- [ ] 3.1 增加未运行、失败、超时、旧 attempt、快照变化、跨检查快照不一致和全部通过场景的工具测试
- [ ] 3.2 增加 Runner 恢复与新 Generator attempt 不复用旧证据的集成测试
- [ ] 3.3 运行目标测试、完整 pytest、ruff、mypy、离线构建和 OpenSpec strict 验证并修复所有失败
- [ ] 3.4 运行 M26 小规模真实 Duo/Triad 验证，保存独立、可复现且不改写 M23/M25 的评测证据

## 4. 里程碑收尾

- [ ] 4.1 更新 M26 直接相关的运行时契约说明和 `ACTION_PLAN.md`
- [ ] 4.2 按 `MILESTONE_GUIDE.md` 生成 M26 记录并更新 `milestones/latest`
- [ ] 4.3 完成代码评审、两轮最终一致性审查、归档 delta spec 和分支收尾

```

## openspec/changes/bind-collaboration-completion-evidence/specs/runtime-collaboration/spec.md

- Source: openspec/changes/bind-collaboration-completion-evidence/specs/runtime-collaboration/spec.md
- Lines: 1-83
- SHA256: a205a8b6520766582b0ebecd16843cd2ef9b2884f54c596fbdc145dbb9ea84ed

[TRUNCATED]

```md
## MODIFIED Requirements

### Requirement: Evaluator 独立验收并决定协作完成
在 Duo/Triad 模式中，Generator MUST 成功调用零载荷 `SubmitCandidate` 提交当前候选；普通 prose、
`task_status.completed` 或其他 Task 终态 MUST NOT 代替候选提交，也 MUST NOT 启动 Evaluator。
Evaluator MUST 使用结构化逐项结果判定外部可观察产物；只有所有要求通过，且宿主为本次协作注册的全部冻结检查都对当前 Candidate 通过时，协作结果才能为 completed。Evaluator 默认 MUST 使用 restricted tier，写工具 MUST 不可用，且其模型和 tier MAY 与 Generator 独立配置但不得扩大服务端或 CLI 所有者授予的权限。宿主未注册检查时 MUST 保持仅依据冻结验收项判定完成的兼容行为。

#### Scenario: Generator 未结构化提交被拦截
- **WHEN** Generator 声明完成但未成功调用当前 attempt 的 `SubmitCandidate`
- **THEN** 运行时不得启动 Evaluator，并在一次有界恢复仍失败后以 `invalid_role_submission` 结束协作

#### Scenario: Generator 候选验收失败
- **WHEN** Generator 成功调用 `SubmitCandidate`，但 Evaluator 发现至少一项外部可观察行为不满足
- **THEN** 协作结果保持未完成并生成有界、脱敏的实际行为、期望行为和定位证据

#### Scenario: 全部验收与冻结检查通过
- **WHEN** Evaluator 对冻结计划或 Duo 验收目标的全部项目返回 pass，且本次注册的全部冻结检查都对当前 Candidate 返回 pass
- **THEN** 系统返回 completed，并保留 Generator 与 Evaluator 的轮次、usage 和验收计数投影

#### Scenario: Evaluator 无写权限
- **WHEN** Evaluator 尝试修改被验收产物
- **THEN** 请求被工具注册表、确认门或 sandbox 拒绝，且该尝试不能形成 pass

### Requirement: Evaluator 只能执行宿主冻结的隔离检查
协作运行时 MUST 允许宿主为 Evaluator 注册零个或多个稳定检查 ID。Evaluator 只能提交检查 ID，MUST NOT 提交或覆盖 argv、shell 文本、工作目录、环境变量、超时、输出上限、检查状态或快照证据。检查 MUST 在项目临时工作副本内以无 shell 子进程执行，使用宿主冻结的参数、最小环境、固定超时和有界输出；检查 worker MUST 能读取和枚举当前 Python 解释器环境以导入宿主已安装依赖，并 MUST 能读写当前平台固定的 null device 以支持测试框架捕获，但 MUST 继续拒绝项目副本和 Python 运行时之外的宿主目录枚举、其他宿主文件写入、网络与进程创建。检查结果 MUST 作为不含绝对路径和已知 secret 的结构化证据返回。

当 Evaluator 提交全部验收项通过的 verdict 时，运行时 MUST 要求每个已注册检查都有当前 Evaluator Task 内产生的最新 `passed` 结果，且所有结果 MUST 绑定当前 Generator attempt 和同一当前 Candidate 快照。检查缺失、失败、超时、取消、执行错误、属于旧 attempt、对应不同快照或 Candidate 在检查后变化时，`SubmitEvaluation` MUST 拒绝全通过 verdict且不得保存 verdict或递增 Evaluator attempt。Evaluator 提交至少一个验收项失败的 verdict 时 MAY 不运行全部检查。恢复待验收 Candidate 时 MUST 不复用中断前的进程内检查证据。未注册检查时 MUST 保持既有 Evaluator 工具集合与行为。

#### Scenario: Evaluator 运行已注册检查
- **WHEN** Evaluator 调用 `RunCheck` 并选择宿主已注册的检查 ID
- **THEN** 运行时在临时工作副本中执行该检查的冻结 argv，并返回稳定状态、退出码、耗时和有界脱敏输出，同时由宿主记录该结果对应的当前 attempt 与 Candidate 快照

#### Scenario: 检查导入宿主已安装依赖
- **WHEN** 宿主冻结的 Python 检查通过当前解释器导入 pytest 等已安装包及其子模块
- **THEN** check worker 允许只读枚举当前 Python 运行时目录并正常执行检查，不把合法子模块误报为缺失

#### Scenario: Evaluator 请求未知检查
- **WHEN** Evaluator 提交不存在或未向本次协作注册的检查 ID
- **THEN** 运行时返回结构化失败且不启动任何子进程

#### Scenario: 检查超时
- **WHEN** 已注册检查超过其冻结超时
- **THEN** 运行时终止对应子进程组、返回稳定的 timeout 结果，并清理临时工作副本

#### Scenario: Evaluator 不能注入命令或证据
- **WHEN** 模型输出尝试携带 argv、shell、路径、环境、检查状态、快照摘要或其他未定义字段
- **THEN** 协议校验拒绝该调用，普通 `Exec` 仍不在 Evaluator registry 中

#### Scenario: 未运行检查时不能全通过
- **WHEN** 宿主注册至少一个检查，而 Evaluator 未运行全部检查就提交所有验收项通过
- **THEN** `SubmitEvaluation` 返回列出缺失检查 ID 的有界失败，持久状态和 Evaluator attempt 不变

#### Scenario: 失败检查不能被自报通过覆盖
- **WHEN** `RunCheck` 对当前 Candidate 返回 failed、timeout、cancelled、copy_error 或 start_error，而 Evaluator 仍提交所有验收项通过
- **THEN** `SubmitEvaluation` 拒绝该 verdict，模型不能通过参数覆盖宿主记录的检查状态

#### Scenario: Candidate 变化使检查证据失效
- **WHEN** 一个或多个检查通过后 Candidate 文件树发生变化，或多个检查对应不同 Candidate 快照
- **THEN** `SubmitEvaluation` 拒绝全通过 verdict，并要求在同一当前快照上重新运行全部冻结检查

#### Scenario: 新 attempt 不能复用旧证据
- **WHEN** Evaluator 拒绝 Candidate，Generator 提交新的 attempt，且新 Evaluator 尚未重新运行冻结检查
- **THEN** 新 Evaluator 的证据集合为空，旧 attempt 的通过结果不能满足全通过门禁

#### Scenario: 待验收 Candidate 恢复后重新检查
- **WHEN** 协作从 evaluator phase 且 verdict 为空的持久状态恢复
- **THEN** Runner 为当前 Candidate 创建新的 Evaluator Task，且中断前未持久化的检查结果不能满足全通过门禁

#### Scenario: 只读观察支持提前拒绝
- **WHEN** Evaluator 通过只读观察已确定至少一个冻结验收项失败
- **THEN** Evaluator 可以不运行全部冻结检查而提交包含失败项的 verdict

#### Scenario: 检查审计不泄露执行内容
- **WHEN** Evaluator 运行宿主冻结检查
- **THEN** 审计只记录检查 ID、当前 Generator attempt、稳定状态和耗时，不记录 argv、绝对路径、文件内容、完整输出或 Candidate 快照摘要

#### Scenario: 未配置检查保持兼容
- **WHEN** 宿主没有为本次协作注册任何检查
- **THEN** Evaluator registry 仍只包含既有只读文件与提交验收工具，不广告 `RunCheck`，全部冻结验收项通过时可沿用现有完成路径


```

Full source: openspec/changes/bind-collaboration-completion-evidence/specs/runtime-collaboration/spec.md
