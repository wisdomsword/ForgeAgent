# Comet Design Handoff

- Change: expose-task-execution-evidence
- Phase: design
- Mode: compact
- Context hash: 819fb0b40bf1bb3f31f80013e7c66dff0752021c5240b7e6e408d004b2dea962

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/expose-task-execution-evidence/proposal.md

- Source: openspec/changes/expose-task-execution-evidence/proposal.md
- Lines: 1-31
- SHA256: b8a5eb9dd490d9833fe9be49a738d411a6619ba9c39e0a76d91b9a71a0f1a2c5

```md
## Why

ForgeAgent 目前只在轮次内返回工具结果：`ToolOutcome` 和 `StoredBlock` 没有程序制品路径，解析得到的 `CodeBlock.path` 在存储时丢失，内联 Exec 及 restricted/container 执行也只通过内存或 stdin 传递代码。用户因此无法在任务终态确认 ForgeAgent 使用了哪些工具、工具是否成功，以及实际执行的生成程序位于何处。

## What Changes

- 为 M48 新增任务级执行证据契约，记录实际尝试的工具、稳定状态和关联程序制品，不暴露原始参数、凭据、prompt 或文件内容。
- 将所有实际执行的生成代码（包括命名代码块和内联 Exec）持久化到任务级制品目录，并为每次执行关联稳定制品引用。
- CLI 在任务终态汇总工具、状态和本地程序路径；纯 prose 且未调用工具时明确显示没有工具或程序执行。
- HTTP 只返回安全、相对的制品引用，禁止暴露宿主绝对路径；投影保持有界、脱敏且兼容既有字段。
- Loop、Duo、Triad 在终态聚合内部任务的有界执行证据；失败、停止和取消也保留已经尝试的证据。
- 终态汇总一次性输出，不在每轮重复刷屏。

## Capabilities

### New Capabilities

- `task-execution-evidence`：定义任务级工具尝试、稳定状态、程序制品持久化、入口投影和敏感信息边界。

### Modified Capabilities

- `http-task-service`：终态公开结果增加有界工具证据和安全相对制品引用，同时继续禁止宿主绝对路径。
- `loop-execution`：Loop 终态报告聚合各次任务已经尝试的有界执行证据。
- `runtime-collaboration`：Duo/Triad 终态报告聚合各角色已经尝试的有界执行证据。

## Impact

- 影响 protocol/block store、Exec 工具与 executor 边界、Task/Step 结果模型、CLI 渲染、HTTP public view、Loop 和 collaboration 报告。
- 新增任务级程序制品持久化与引用契约，但不新增外部依赖。
- 需要定义制品目录、命名、保留、失败写入和边界投影策略，并覆盖 single/HTTP/Loop/Duo/Triad。
- 不输出原始工具参数、凭据、完整 prompt、任意文件内容或 HTTP 宿主绝对路径；不逐轮增加终端噪声。

```

## openspec/changes/expose-task-execution-evidence/design.md

- Source: openspec/changes/expose-task-execution-evidence/design.md
- Lines: 1-53
- SHA256: 5ad56138e9f758d636598dfdb24c457e9b5a7c0ef3f62eb5291d4d02be95f545

```md
## Context

当前执行链路没有可持久引用的程序制品：`CodeBlock.path` 是模型提供的 markdown 元数据，`Step` 把代码写入 `StoredBlock` 时会丢弃该字段；`StoredBlock` 和 `ToolOutcome` 也没有 artifact 字段。命名块、内联 Exec、restricted worker 和 container worker 都以内存或 stdin 传递代码，终态结果无法证明具体执行了哪个程序。CLI 虽会渲染轮次工具结果，HTTP、Loop 和 collaboration 只保留既有有界公开投影。

该 change 是 M48 唯一需要完整设计的新能力。本 open 文档只固定跨模块契约和安全边界；具体数据模型、容量与生命周期在后续 full design 阶段通过 brainstorming 决定。交付顺序固定为先完成并分别 verify/archive 三个 port change，再基于已集成三项行为的 `main` 开始本 change 的 build；不得与 `port-task-filesystem-authority` 并行修改 `tools.py`、ToolContext 或 Exec 接入点。

## Goals / Non-Goals

**Goals:**

- 每个 Task 在终态提供实际尝试的工具、稳定状态和关联程序制品证据。
- 所有准备交给 executor 的生成代码在执行前写入任务级制品目录，包括命名块与内联 Exec。
- CLI、HTTP、Loop、Duo、Triad 都在终态一次性投影有界证据；失败、停止和取消保留已发生尝试。
- CLI 显示本地程序路径，HTTP 只显示安全相对制品引用。

**Non-Goals:**

- 不逐轮重复输出汇总，不暴露原始工具参数、凭据、prompt、文件内容或 HTTP 宿主绝对路径。
- 不把模型提供的 `CodeBlock.path` 直接信任为宿主写入路径。
- 不在本 change 中建立通用制品下载服务、远程对象存储或任意工具输出归档系统。
- 不改变工具成功/失败语义、sandbox tier 或任务完成完整性规则。

## Decisions

1. 在 Task 拥有的执行证据收集器中追加记录，而不是在终态重新扫描 rounds。记录点位于工具实际尝试边界，可覆盖成功、失败、停止和取消，并由 `TaskOutcome`、LoopReport 与 CollaborationReport 做加法式投影。
2. Exec 在调用任何 backend 前统一物化程序制品。命名块和内联代码都走同一写入路径；制品名由宿主生成安全任务内名称和语言扩展，不采用模型给出的绝对或相对 `CodeBlock.path` 作为落盘目标。
3. 程序制品必须先原子持久化再执行。若制品写入失败，该 Exec 返回稳定失败且不得把未留证据的代码交给 trusted/restricted/container backend。
4. 内部证据同时携带宿主本地路径和任务内相对引用。CLI 只在本地主机上下文渲染本地路径；HTTP、Loop 的 HTTP 投影和其他公共 JSON 只渲染安全相对引用。
5. 公开记录只包含有界工具名、稳定状态、可选安全 block 名和可选制品引用。原始 args、代码正文、stdout/stderr、绝对宿主路径和异常正文继续由现有投影边界排除。
6. Single Task 是证据所有权基本单元。Loop 按迭代聚合，Duo/Triad 按角色/attempt 聚合并应用全局上限；终态只渲染一次，普通 prose 明确投影空证据集合。
7. 程序制品固定写入 immutable project root 下的 `.forgeagent/execution-artifacts/<execution-id>/programs/`；`execution-id` 由宿主生成，不复用外部 task ID。每 Task 最多 100 个程序、单文件最多 1 MiB、合计最多 8 MiB；内部工具尝试保留 128 条，公开投影保留 32 条并报告 omitted 数量。
8. HTTP 只返回 `execution-artifacts/...` canonical relative POSIX 引用，不新增下载端点。测试必须从内部项目根验证引用对应已持久化文件，同时证明公开 JSON 不含绝对路径。引用仅在 terminal record 可查询期间作为结果元数据稳定，不承诺 HTTP 解引用能力。
9. M48 不实现自动 GC。Task、HTTP record、Loop 与 collaboration 关闭或过期都不删除已公开程序路径；项目/宿主运维者负责清理 `.forgeagent/execution-artifacts/`。目录权限为 0700、文件权限为 0600，单 Task 容量限制控制局部增长。

## Risks / Trade-offs

- [程序制品包含模型生成的敏感字面量] -> 终态和 HTTP 不展示代码内容；后续设计需明确本地文件权限、保留和清理策略。
- [证据写入使原本可执行的代码失败] -> fail closed，保证“执行过的程序一定有路径”契约，不产生不可审计执行。
- [Loop/协作聚合无限增长] -> 后续设计定义稳定排序、条目/字符/字节上限和截断标记。
- [与 HTTP record retention 生命周期不一致] -> 后续设计明确引用有效期和清理所有权；在此之前不承诺下载能力。
- [新增结果字段影响调用方] -> 只做带默认空集合的加法式字段，保留既有字段与终态枚举。
- [跨任务持久制品持续占用磁盘] -> 本 change 固定单 Task 数量/字节上限并明确项目运维清理所有权；自动 GC 作为独立后续能力，不与结果契约耦合。

## Migration Plan

open/design 的初始语义基准来自 `main` M47 提交 `3da54054d71e4afd8fc057b0b1804dfad6f73ff5`，不得使用旧分支 HEAD `3245a448` 判定改动归属。三个 port change 均已 verify/archive 并集成；本 change 的实现基线固定为集成提交 `d64f2dbf6d62c39dc362d1bf0ee5a467162b7f1d`，后续 build/verify 只比较该提交之后的执行证据差异。无旧数据迁移。实现按“Task 内部证据与制品 -> Exec 接入 -> Single CLI -> HTTP -> Loop/Collaboration”逐层推进，每层先建立失败测试。回滚可移除加法式字段和新制品写入，不改变现有任务状态数据。

## Resolved Questions

- 制品位于 immutable project root 的 `.forgeagent/execution-artifacts/<execution-id>/programs/`，角色与迭代只作为证据来源字段，不参与不受信任的路径命名。
- 固定上限为每 Task 100 个程序、单文件 1 MiB、总量 8 MiB；任何制品持久化或容量失败都返回稳定 `artifact_persistence_failed`，且不 dispatch backend。
- 制品持久保留，项目/宿主运维者负责清理；HTTP 引用仅在 terminal record 可查询期间作为元数据稳定，Task/record/runner close 不删除文件。
- HTTP 只提供安全相对引用，不增加下载端点；验收通过内部项目根解析确认引用与文件关联，并单独验证公开投影不泄露绝对路径。

```

## openspec/changes/expose-task-execution-evidence/tasks.md

- Source: openspec/changes/expose-task-execution-evidence/tasks.md
- Lines: 1-22
- SHA256: 2cf71fd0a55e98fc3c7d60bef5c5a1d21eff3d3ae5e6e47b20b47ec80ee47d32

```md
## 1. 完整技术设计

- [x] 1.1 在 full design brainstorming 的第一项决策中明确 HTTP 是否仅返回相对引用（默认且当前范围）或扩大为受认证读取端点；随后确定 Task 证据模型、制品根目录与命名空间、容量上限、保留/清理策略、HTTP 引用有效期和向后兼容策略，并关闭 design.md 的开放问题。
- [x] 1.2 确认三个 port change 均已 verify/archive 并集成到 `main`，从该集成提交建立隔离实现分支并将本 change 的 `.comet.yaml.base_ref` 更新为该提交；不得从旧分支 HEAD 构建或与 filesystem-authority 并行修改重叠区域。
- [ ] 1.3 为 Single、纯 prose、失败/取消、trusted/restricted/container、内联/命名 Exec、HTTP、Loop、Duo、Triad 建立可执行失败测试。

## 2. Task 证据与程序制品

- [ ] 2.1 实现 Task 拥有的有界执行证据记录及 `TaskOutcome` 加法式投影，准确区分已解析、已尝试、成功、失败和未执行工具。
- [ ] 2.2 实现安全任务级程序制品持久化：宿主命名、语言扩展、原子写入、路径逃逸拒绝、容量边界和稳定失败原因。
- [ ] 2.3 将命名块与内联 Exec 统一接入“先持久化、后 backend dispatch”，覆盖 trusted、restricted 和 container，保证持久化失败时不执行代码。

## 3. 入口终态投影

- [ ] 3.1 在 CLI/REPL 终态一次性汇总工具、状态和本地程序路径；纯 prose 明确显示没有工具或程序执行，避免逐轮重复汇总。
- [ ] 3.2 在 HTTP terminal public view 中增加有界工具状态和安全相对制品引用，验证绝对路径、代码、参数、prompt、secret 和异常正文不会泄露。
- [ ] 3.3 在 LoopReport 与 CollaborationReport 中按迭代、角色和 attempt 有界聚合证据，覆盖 completed/stopped/failed/cancelled 及恢复场景。

## 4. 验证与交付

- [ ] 4.1 运行新契约的聚焦测试、HTTP/Loop/collaboration 回归、sandbox backend 测试、Ruff、全量测试和 OpenSpec strict 校验。
- [ ] 4.2 完成安全边界评审、向后兼容评审和 whole-change 代码审查，记录实际工具与程序制品路径的端到端验收证据。

```

## openspec/changes/expose-task-execution-evidence/specs/http-task-service/spec.md

- Source: openspec/changes/expose-task-execution-evidence/specs/http-task-service/spec.md
- Lines: 1-29
- SHA256: 5540a1aed67c71cb565af081acfb755fdf886814b59fb767a8ac849ed698e22b

```md
## MODIFIED Requirements

### Requirement: Task status and result retrieval

The service MUST expose authenticated queries for a task's lifecycle state and terminal result using the existing `TaskOutcome` semantics for ordinary tasks and bounded Loop and collaboration report projections for aggregate tasks. A terminal response MUST include bounded attempted-tool statuses and safe task-relative program artifact references when execution evidence exists. It MUST NOT expose internal exceptions, secrets, full prompts, raw tool arguments, checkpoint contents, file contents, generated code content, absolute host paths, or unbounded round or execution-evidence history.

#### Scenario: Running task query
- **WHEN** an authenticated client queries an ordinary task, Loop, or collaboration that has been accepted but is still running
- **THEN** the response identifies it as running, identifies the public execution mode, and does not fabricate a terminal result or execution evidence for unattempted work

#### Scenario: Terminal task query
- **WHEN** an authenticated client queries a completed, stopped, failed, refused, needs-information, or cancelled task
- **THEN** the response includes the stable terminal status, reason, safe detail, mode, available bounded result data, and bounded execution evidence already produced by that task

#### Scenario: Unknown task query
- **WHEN** an authenticated client queries an identifier that is not retained by the service
- **THEN** the service returns a not-found error without revealing other task, Loop, collaboration, or artifact identifiers or stored content

#### Scenario: Safe result projection
- **WHEN** an authenticated client queries a terminal task whose rounds, checkpoint, collaboration state, or execution evidence contain prompts, tool arguments, code, file contents, absolute paths, or handoff text
- **THEN** the response returns only bounded stable result fields, tool statuses, and safe task-relative artifact references with masking, truncation, and no host absolute path

#### Scenario: Artifact reference is metadata rather than a download capability
- **WHEN** a terminal task exposes an `execution-artifacts/...` program reference
- **THEN** the service can map that reference internally to the persisted regular file under the task project root, but this change adds no HTTP artifact read or download endpoint and discloses no absolute path

#### Scenario: Terminal record expiry does not delete program evidence
- **WHEN** a terminal HTTP record expires under the existing retention policy
- **THEN** the record becomes unqueryable under existing semantics while its already persisted project-local program artifact is not deleted by TaskService

```

## openspec/changes/expose-task-execution-evidence/specs/loop-execution/spec.md

- Source: openspec/changes/expose-task-execution-evidence/specs/loop-execution/spec.md
- Lines: 1-24
- SHA256: d13d49d5d9e7c30c8fecbcc485e1491ed04eebbf6415b2f3a27d9bb2f70d9e37

```md
## MODIFIED Requirements

### Requirement: Loop 终态报告稳定、有界且可离线验证
每个 Loop MUST 产生包含 schema、Loop ID、终态、停止原因、迭代/轮次/token/墙钟计数、连续失败数、checkpoint 摘要计数和已尝试工具执行证据的稳定报告。公开 CLI/HTTP 投影 MUST 对执行证据按迭代稳定聚合、脱敏、限制条目和长度并标记截断；HTTP 只可包含安全任务相对程序制品引用。公开投影不得暴露完整 prompt、checkpoint 正文、tool 参数、生成代码、文件内容、绝对宿主路径或 secret；本地 CLI MAY 在专用本地路径字段显示程序制品绝对路径。Loop 报告 MAY additionally expose a bounded attention projection when its stop reason is `needs_input` or `blocked`; the attention projection MUST follow the attention-state-protocol contract and MUST NOT change the existing terminal status taxonomy. Loop 报告的公开 JSON 也 MUST 使用 `schema` 键，且与既有报告兼容。

#### Scenario: 成功完成报告
- **WHEN** 某次 Task 以严格 completed 终态结束
- **THEN** Loop 原子写入 completed 报告并返回累计预算、进度计数和有界执行证据，且 attention state 为 `ready`

#### Scenario: 预算停止报告
- **WHEN** 任一停止预算命中
- **THEN** 报告使用稳定枚举标识首个生效停止原因，保留停止前已尝试工具的有界安全证据，且不得伪装为 `needs_input` 或 `blocked`

#### Scenario: Attention stop report
- **WHEN** Loop 因需要用户输入或外部阻塞在安全边界停止
- **THEN** 报告使用 `status=stopped`、稳定 `stop_reason`（`needs_input` 或 `blocked`）、bounded attention metadata 和停止前的有界执行证据，resume 不得静默重放动作

#### Scenario: HTTP Loop evidence uses relative artifact references
- **WHEN** HTTP 查询的终态 Loop 包含一个或多个程序执行制品
- **THEN** Loop 公开 JSON 按迭代返回安全相对制品引用且不包含任何宿主绝对路径或生成代码内容

#### Scenario: 离线端到端恢复验证
- **WHEN** 测试使用 MockClient 在 checkpoint 后模拟中断并恢复
- **THEN** 恢复执行不重做已完成条目，每种停止条件、attention stop 和执行证据聚合均可由确定性断言验证且无需 API key

```

## openspec/changes/expose-task-execution-evidence/specs/runtime-collaboration/spec.md

- Source: openspec/changes/expose-task-execution-evidence/specs/runtime-collaboration/spec.md
- Lines: 1-30
- SHA256: ef51d6203dca91c4860712b49057aa994aac0fa58f7c9c3fb3a66e465c18588e

```md
## MODIFIED Requirements

### Requirement: 协作报告稳定、有界且兼容
协作执行 MUST 返回加法式稳定报告，包含 mode、终态、稳定原因、角色尝试计数、计划项计数、通过/失败计数、打回次数、累计轮次、normalized usage、按角色与 attempt 聚合的已尝试工具执行证据，以及可选的有界 attention。执行证据 MUST 使用稳定顺序、全局条目/文本上限和显式截断标记；HTTP 投影只可包含安全任务相对程序制品引用，本地 CLI MAY 在专用本地路径字段显示程序制品绝对路径。报告 MUST NOT 包含完整目标、计划正文、模型回复、工具参数、生成代码、任意文件内容、非本地投影的绝对路径、credential、原始异常或未掩码证据。普通 `TaskOutcome` 的既有字段与语义 MUST 保持兼容。

Task 与 Loop 的已知停止信号 MUST 使用确定性投影：正常打回上限保持 `stopped/rejection_limit`；`needs_info` 映射为 `stopped/needs_input`；`blocked` 和未决外部动作映射为 stopped 的阻塞原因；`max_rounds`、`wall_clock`、`token_budget`、`token_usage_unavailable` 与 `consecutive_failures` MUST 保留具体资源原因并映射为 stopped；`cancelled` 映射为 cancelled；auth、invalid-request、checkpoint/state/protocol 损坏与其他不可恢复角色错误映射为 failed。未知原因 MUST fail closed，不得成为任意公开枚举。

#### Scenario: 安全终态投影
- **WHEN** CLI 或 HTTP 输出协作终态
- **THEN** 输出只包含稳定枚举、计数、模型标识、可选安全 attention、经过掩码截断的逐项验收摘要和按角色/attempt 聚合的有界工具执行证据

#### Scenario: HTTP collaboration evidence uses relative artifact references
- **WHEN** HTTP 查询的 Duo 或 Triad 终态包含一个或多个角色程序执行制品
- **THEN** 公开 JSON 只返回安全任务相对制品引用，不包含宿主绝对路径、生成代码或角色对话

#### Scenario: 普通结果未改变
- **WHEN** single 任务结束
- **THEN** 现有调用方仍收到兼容的 `TaskOutcome` 既有字段与语义，并可选择读取加法式执行证据

#### Scenario: 资源耗尽原因透传
- **WHEN** 内层 Task 或外层 Loop 因 `max_rounds`、`wall_clock`、`token_budget`、`token_usage_unavailable` 或 `consecutive_failures` 停止
- **THEN** Collaboration 投影为 `stopped` 并保留该稳定原因和停止前已尝试的有界执行证据，不把它误报为 `rejection_limit` 或 `role_failed`

#### Scenario: 需要输入和阻塞保持可恢复
- **WHEN** 内层 Task 报告 `needs_info`，或 Task/Loop 报告 `blocked`、`external_action_pending`
- **THEN** Collaboration 投影为 `stopped`，分别使用 `needs_input` 或稳定阻塞原因，并附带不含敏感正文的匹配 attention 和停止前有界执行证据

#### Scenario: 不可恢复错误保持失败
- **WHEN** 角色遭遇 auth、invalid-request、状态损坏、checkpoint 损坏、无效结构化提交或其他不可恢复错误
- **THEN** Collaboration 报告为 `failed` 且只暴露固定失败原因和失败前有界执行证据，不包含原始异常正文

```

## openspec/changes/expose-task-execution-evidence/specs/task-execution-evidence/spec.md

- Source: openspec/changes/expose-task-execution-evidence/specs/task-execution-evidence/spec.md
- Lines: 1-88
- SHA256: f8ece2e03f61f03d867e50ba171e24ff6f0eabc671c0fe897aeef5f816a425ca

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Task terminal outcomes disclose attempted tools
Every ForgeAgent Task MUST maintain an ordered, task-scoped record of tools that reached an execution attempt and MUST expose a bounded terminal projection containing each tool's stable name and stable outcome status. The projection MUST remain available when the Task completes, answers in prose, stops, fails, refuses, needs information, or is cancelled, and MUST NOT claim that a tool ran when it was only parsed but never attempted.

#### Scenario: Successful and failed tools are reported
- **WHEN** a Task attempts one tool successfully and a later tool fails before the Task terminates
- **THEN** the terminal evidence lists both attempted tools in deterministic order with distinct stable success and failure statuses

#### Scenario: Parsed tool after a terminal submission is not reported as attempted
- **WHEN** a response contains a terminal structured submission followed by another parsed tool that the runtime intentionally does not execute
- **THEN** terminal evidence includes the submission attempt but does not represent the skipped later tool as executed

#### Scenario: Direct prose uses an empty evidence projection
- **WHEN** a Task terminates as `answered_in_prose` without attempting any tool or program
- **THEN** the terminal projection explicitly represents that no tools or programs were executed and does not fabricate evidence

### Requirement: Executed generated code has a task-owned program artifact
Before ForgeAgent dispatches generated code to any trusted, restricted, or container execution backend, it MUST persist the exact code selected for that execution attempt as a regular file in a host-owned task artifact directory and associate the tool attempt with a stable task-relative artifact reference. This requirement applies to both stored named blocks and inline Exec code. Model-supplied block path metadata MUST NOT select or escape the host-owned artifact directory.

#### Scenario: Named block execution is persisted
- **WHEN** Exec resolves and prepares to run a stored named code block
- **THEN** ForgeAgent atomically writes the selected block version to the Task's program artifact directory before backend dispatch and associates that execution attempt with its artifact reference

#### Scenario: Inline Exec is persisted
- **WHEN** Exec receives inline generated code rather than a stored block name
- **THEN** ForgeAgent atomically writes the inline code to the same Task-owned program artifact contract before backend dispatch and associates that execution attempt with its artifact reference

#### Scenario: Restricted and container execution retain a file artifact
- **WHEN** generated code is delivered to a restricted or container worker through an in-memory or stdin payload
- **THEN** the host still retains the corresponding task-owned program file and reports its reference independently of the worker transport

#### Scenario: Model path metadata cannot redirect persistence
- **WHEN** a parsed code block supplies an absolute path, traversal path, symbolic-link target, or other path metadata outside the Task artifact directory
- **THEN** ForgeAgent ignores that metadata for program persistence, generates a safe host-owned artifact name, and does not write outside the artifact directory

#### Scenario: Artifact directories are replaced or linked
- **WHEN** any `.forgeagent/execution-artifacts` directory component is a symbolic link or is rebound while a program is being published
- **THEN** ForgeAgent fails the Exec attempt without backend dispatch and does not write through the linked or replacement directory

### Requirement: Program artifact persistence fails closed
ForgeAgent MUST NOT dispatch generated code to an execution backend when its required program artifact cannot be created atomically as a safe regular file. The failed Exec attempt MUST remain in terminal evidence with a stable artifact-persistence failure status and MUST NOT expose a misleading program path.

#### Scenario: Artifact directory is unavailable
- **WHEN** ForgeAgent cannot create or safely open the Task program artifact directory before an Exec attempt
- **THEN** Exec fails without dispatching code to any backend and terminal evidence reports a stable persistence failure without a fabricated artifact reference

#### Scenario: Artifact write fails before replacement
- **WHEN** writing or atomically publishing a program artifact fails
- **THEN** ForgeAgent does not execute a partial or unrecorded program and does not expose a partial file as a valid artifact

#### Scenario: Per-task program capacity is exceeded
- **WHEN** an Exec would exceed 100 programs, 1 MiB for one program, or 8 MiB across one Task
- **THEN** ForgeAgent returns the stable `artifact_persistence_failed` evidence status, does not dispatch that code, and does not expose a fabricated artifact reference

### Requirement: Execution evidence projections are entrypoint-safe
ForgeAgent MUST render one terminal execution-evidence summary for CLI, HTTP, Loop, Duo, and Triad task operations. Local CLI output SHALL show the local path for every persisted program artifact available on that host. HTTP output MUST expose only bounded safe task-relative artifact references and MUST NOT expose host absolute paths. Loop and collaboration reports MUST aggregate child Task evidence with stable origin metadata and global bounds.

#### Scenario: CLI displays local program paths once
- **WHEN** a local CLI or REPL Task terminates after executing generated code
- **THEN** the terminal result contains one summary of attempted tools and statuses plus each available local program path, without repeating the summary after every round

#### Scenario: HTTP displays only relative references
- **WHEN** an authenticated HTTP caller queries a terminal Task that executed generated code
- **THEN** the response contains bounded tool statuses and safe task-relative artifact references but no host absolute path or code content

#### Scenario: Loop aggregates attempted evidence
- **WHEN** a Loop terminates after one or more iterations attempted tools or programs
- **THEN** its terminal report includes a bounded deterministic aggregation that identifies the originating iteration without exposing child prompts, raw arguments, code, or absolute host paths

#### Scenario: Collaboration aggregates attempted evidence
- **WHEN** a Duo or Triad terminates after one or more role attempts used tools or programs
- **THEN** its terminal report includes a bounded deterministic aggregation that identifies the originating role and attempt without exposing role conversations, raw arguments, code, or absolute host paths

#### Scenario: Cancellation retains prior attempts
- **WHEN** a Task, Loop, Duo, or Triad is cancelled after some tools were attempted
- **THEN** the terminal evidence retains those prior attempts and does not fabricate evidence for work prevented by cancellation

### Requirement: Public execution evidence is bounded and minimally disclosing
Every public execution-evidence projection MUST enforce a deterministic 32-item bound, fixed text bounds, stable ordering, masking, and explicit truncation and omitted-count fields. It MUST NOT include raw tool arguments, credentials, full prompts, generated code content, arbitrary file contents, unbounded stdout or stderr, raw exceptions, or host absolute paths outside a local CLI path field.

```

Full source: openspec/changes/expose-task-execution-evidence/specs/task-execution-evidence/spec.md
