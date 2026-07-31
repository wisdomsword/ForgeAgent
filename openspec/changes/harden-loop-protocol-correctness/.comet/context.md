# Comet Design Handoff

- Change: harden-loop-protocol-correctness
- Phase: design
- Mode: compact
- Context hash: ed19e36efb2fb2b9ebd612213e3397c4e888585ebbb301b2e3f812d4b8ebf343

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/harden-loop-protocol-correctness/proposal.md

- Source: openspec/changes/harden-loop-protocol-correctness/proposal.md
- Lines: 1-29
- SHA256: 78da22d47f21b22bf583d35e3ab088ae863114073a9f50b85e5d6346f1f8df4c

```md
## Why

Loop checkpoint/report、协议解析、工具反馈和协作审计路径仍有若干正确性接缝：schema 别名实现不一致；文本通道与原生通道的同一工具调用可能被重复分发；安全文本和反馈约定存在重复实现。这些问题会造成重复副作用、不稳定的 checkpoint JSON 或难以诊断的审计记录，因此需要在后续协作契约变更前先收紧。

## What Changes

- 使用 Pydantic 支持的 `schema_` 别名字段实现 `LoopCheckpoint` 与 `LoopReport`，保持磁盘上的 `"schema"` 键及旧数据加载能力。
- 在分发前按稳定调用 ID 合并文本协议和原生协议的工具调用；重复 ID 冲突时拒绝执行。
- 增加空正文和空白正文的 prose 完成回归测试，保持严格完成语义。
- 提取一个共享的内部 `_safe_text` 实现，并保留调用方原有的空值策略。
- 将工具 continuation 反馈改为 English-first，同时继续限制长度。
- 移除 `step` 对私有 `_apply_edit` 的再导出，测试从其定义模块导入。
- capability/receipt projection 失败时记录固定类型、有限长度的诊断，不输出原始异常或敏感载荷。
- 保持 M27 对旧 Duo/Triad collaboration source 的迁移语义，不扩大迁移推断。

## Capabilities

### New Capabilities

- `tool-call-identity`：定义跨协议通道的工具调用去重和冲突处理。

### Modified Capabilities

- `loop-execution`：补充 checkpoint/report 的 schema 别名兼容要求。
- `completion-integrity`：明确空 prose 正文不能完成任务。

## Impact

影响 `src/forgeagent/loop.py`、`protocol.py`、`step.py`、`tools.py`、`collaboration.py`、`external_actions.py` 及对应单元测试和 delta spec。不新增依赖，不改变公开发布、包上传、tag、push 或发布自动化。

```

## openspec/changes/harden-loop-protocol-correctness/design.md

- Source: openspec/changes/harden-loop-protocol-correctness/design.md
- Lines: 1-46
- SHA256: 0db5a6ca02e9fcd77fb2ac6867d4bed03637bf33fbcf892f052c79a66bac6016

```md
## Context

本 change 收紧现有 loop、protocol、step、工具反馈和协作审计路径，不新增运行时依赖。当前实现已经具备有界 checkpoint/report、严格完成门禁以及文本/native 两套工具调用解析器，但部分边界依赖隐式行为。实现必须保留 M27 的旧 collaboration-source 迁移契约，并继续遵守 M38 的发布暂停。

## Goals / Non-Goals

**Goals：**

- 保持公开 JSON 的 `schema` 键，同时使用 Pydantic 正式 alias 机制。
- 让双通道工具调用身份确定、幂等；冲突时 fail-closed。
- 空 prose 不能完成，并有明确回归测试。
- 建立单一、有界的 `_safe_text` 实现和 English-first continuation 反馈。
- 明确私有 helper 的所有权，并让 capability/receipt projection 失败可观测但不泄漏。

**Non-Goals：**

- 不改变旧 Duo/Triad source 的迁移推断；缺失 source 继续遵循 M27。
- 不重设计 Loop handoff 结构；该内容留给后续独立 change。
- 不引入 LLM 自动拆解器、新依赖、发布自动化、tag、push 或 PyPI 工作。

## Decisions

1. **使用 Pydantic alias，移除告警压制。** 将两个 loop 模型的内部字段改为 `schema_`，设置 alias、按 alias 序列化和严格校验，以兼容旧 JSON。手工 serializer 或 warning filter 会产生版本敏感且可能静默漂移的行为，因此不采用。

2. **在 parser 层合并调用，冲突时拒绝。** 在 `Step` 分发前按显式稳定 ID 合并 text/native 调用。等价重复只保留首次确定顺序的一份；同一 ID 的工具名或规范化参数不同，则生成有界 parse error，并从可分发集合中移除该 ID。仅在 dispatch 层去重会让其他调用者看到不一致的 parsed state，因此不采用。

3. **共享安全 helper，显式传递空值策略。** 提取一个很小的内部模块，调用方传入已有的空值/default 语义，避免机械合并造成 checkpoint 或审计行为变化。

4. **English-first 反馈作为常量文本。** 将模型可见 continuation 常量改为简短英文并保持有界；不引入翻译框架，因为这会扩大范围且没有当前需求。

5. **projection 失败记录固定类型。** capability/receipt projection 失败只记录稳定事件名和异常类型，返回现有安全 fallback；不记录异常正文、工具参数、路径、secret 或 goal 正文。

## Risks / Trade-offs

- [风险] 历史测试从 `step` 导入 `_apply_edit`。→ 更新测试从 `tools` 导入，不保留运行时兼容别名。
- [风险] 模型可能省略稳定调用 ID。→ 只对显式相同 ID 去重，不做启发式参数匹配。
- [风险] 错误顺序影响快照。→ 保持首次出现顺序，并使用确定性的有界冲突消息。
- [风险] 既有测试依赖中文 continuation。→ 更新精确断言，保持反馈含义等价，不改变公开 API。

## Migration Plan

读取旧 checkpoint/report 时使用 `schema` alias，写出仍使用同一键；先运行兼容性 focused tests，再运行更大范围测试。不需要数据迁移或发布动作。遇到 parser 冲突时沿用 parse-error 反馈环，不执行有歧义的调用。

## Open Questions

无。本 change 明确把 Loop handoff 结构化和 Collaboration stop-reason projection 放到后续顺序 change。

```

## openspec/changes/harden-loop-protocol-correctness/tasks.md

- Source: openspec/changes/harden-loop-protocol-correctness/tasks.md
- Lines: 1-21
- SHA256: 5125674f879f0c2ae7c5aaa378e9b2c5a76298fbc07c06fe332659f324293920

```md
## 1. Loop 模型兼容性

- [ ] 1.1 将 `LoopCheckpoint` 和 `LoopReport` 改为正式 `schema_` alias 字段，并增加 `schema` 序列化和旧 JSON 加载测试。
- [ ] 1.2 增加旧 checkpoint/report 回归断言，确认 M27 collaboration-source 迁移语义不变。

## 2. 协议身份与完成语义

- [ ] 2.1 按显式 ID 实现 text/native 双通道工具调用的确定性去重。
- [ ] 2.2 对冲突重复 ID 生成有界 parse error，并确保不分发该 ID。
- [ ] 2.3 增加空正文和空白正文的 prose 完成回归测试。

## 3. 共享安全与反馈

- [ ] 3.1 提取共享 `_safe_text`，迁移 loop、collaboration、external-action 调用方且不改变语义。
- [ ] 3.2 将模型可见 continuation 常量改为 English-first 有界文本并更新 focused tests。

## 4. 所有权与可观测性

- [ ] 4.1 移除 `step` 对私有 `_apply_edit` 的再导出，更新历史测试从 `tools` 导入。
- [ ] 4.2 为 capability/receipt projection fallback 增加固定类型 warning 日志，不泄漏原始异常或 secret。
- [ ] 4.3 运行 focused tests、format、lint、OpenSpec strict，并记录仅由环境导致的全量测试失败。

```

## openspec/changes/harden-loop-protocol-correctness/specs/completion-integrity/spec.md

- Source: openspec/changes/harden-loop-protocol-correctness/specs/completion-integrity/spec.md
- Lines: 1-20
- SHA256: 93c1db214657787a1c2e693a4609e5f4573b6f31b4a02c74e723153ede4619fe

```md
## MODIFIED Requirements

### Requirement: Completion requires a standalone final response
ForgeAgent SHALL mark a single-role task complete only from a response that explicitly declares completion, contains neither tool calls nor protocol parse errors, and has a non-empty body after protocol whitespace normalization. In Duo/Triad mode, the same standalone Generator response SHALL mean only "submitted for evaluation"; ForgeAgent MUST mark the collaborative execution complete only after an independent Evaluator returns a valid structured pass for every frozen acceptance item.

#### Scenario: Standalone completion after tool feedback
- **WHEN** a tool-bearing response has been processed and a later response contains no tools, no parse errors, a non-empty body and declares `completed: true` in single mode
- **THEN** ForgeAgent marks the task complete using the later response

#### Scenario: Empty standalone response does not complete
- **WHEN** a response declares `completed: true` but its body is empty or whitespace-only
- **THEN** ForgeAgent keeps the task incomplete and emits the existing empty-response correction feedback

#### Scenario: Collaborative Generator submits for evaluation
- **WHEN** a Duo/Triad Generator produces an otherwise eligible standalone `completed: true` response with a non-empty body
- **THEN** ForgeAgent starts an isolated Evaluator and does not yet report the collaborative execution as completed

#### Scenario: Evaluator rejects submitted work
- **WHEN** the independent Evaluator reports one or more frozen acceptance items as failed
- **THEN** ForgeAgent keeps the collaborative execution incomplete and either starts a bounded correction attempt or stops with a rejection report

```

## openspec/changes/harden-loop-protocol-correctness/specs/loop-execution/spec.md

- Source: openspec/changes/harden-loop-protocol-correctness/specs/loop-execution/spec.md
- Lines: 1-47
- SHA256: 3e6717faef801b5bb7127993ad3e701ab41277b270ed88ff07dddd70c8adde1d

```md
## MODIFIED Requirements

### Requirement: Loop checkpoint 是版本化、原子且有界的耐久状态
Loop SHALL 将 schema 版本、Loop 身份、原始目标、预算配置、累计预算、迭代计数、连续失败数、已完成条目、未解问题、下轮交接信息、最近安全失败摘要和终态写入 checkpoint。checkpoint MUST 位于允许根目录内，MUST 使用原子替换写入，MUST 拒绝符号链接逃逸、未知字段、超限内容、无效状态组合和不支持的 schema 版本。每个 Loop ID 的 create 与 save MUST 使用稳定 lock file 的跨进程排他锁，将存在性或 expected revision 校验与原子替换纳入同一临界区；同一旧 revision 的重叠提交最多一个成功。Checkpoint 的 Pydantic 字段名 MAY 使用内部保留名，但序列化和反序列化 MUST 保持公开 JSON 键 `schema`，并兼容既有 checkpoint。

#### Scenario: 模型提交进度 checkpoint
- **WHEN** Loop 专用 `Checkpoint` 工具收到合法的已完成条目、未解问题和交接信息
- **THEN** 系统在返回工具成功反馈前原子持久化新状态，并保留此前已提交完成条目

#### Scenario: 旧 checkpoint 使用 schema 键加载
- **WHEN** 旧 checkpoint JSON 使用 `schema` 键且其他字段有效
- **THEN** 系统成功加载并继续以 `schema` 键序列化，不要求调用方改写文件

#### Scenario: checkpoint 写入失败
- **WHEN** checkpoint 目录不可写、目标发生路径逃逸、lock file 不安全、加锁失败或原子替换失败
- **THEN** `Checkpoint` 工具返回结构化失败，Loop 不声称进度已持久化，且失败可进入现有 Task 反馈环

#### Scenario: checkpoint 内容或版本无效
- **WHEN** resume 读取到未知 schema、额外字段、超限文本、无效计数或互相矛盾的终态
- **THEN** 系统在调用模型或工具前拒绝恢复，并保留原文件不变

#### Scenario: 同一旧 revision 跨进程重叠提交
- **WHEN** 两个进程都读取 revision N 并以 `expected_revision=N` 提交不同 checkpoint
- **THEN** 第一个锁内提交写入 revision N+1，第二个锁内重读后收到 stale revision 错误且不得覆盖第一份状态

#### Scenario: 不同 Loop ID 并行提交
- **WHEN** 两个进程同时保存不同 Loop ID
- **THEN** 它们使用不同稳定 lock file，不因全目录锁而互相串行化

### Requirement: Loop 终态报告稳定、有界且可离线验证
每个 Loop MUST 产生包含 schema、Loop ID、终态、停止原因、迭代/轮次/token/墙钟计数、连续失败数和 checkpoint 摘要计数的稳定报告。公开 CLI/HTTP 投影 MUST 脱敏、限制长度且不得暴露完整 prompt、checkpoint 正文、tool 参数、文件内容、绝对宿主路径或 secret。Loop 报告 MAY additionally expose a bounded attention projection when its stop reason is `needs_input` or `blocked`; the attention projection MUST follow the attention-state-protocol contract and MUST NOT change the existing terminal status taxonomy. Loop 报告的公开 JSON 也 MUST 使用 `schema` 键，且与既有报告兼容。

#### Scenario: 成功完成报告
- **WHEN** 某次 Task 以严格 completed 终态结束
- **THEN** Loop 原子写入 completed 报告并返回累计预算与进度计数，且 attention state 为 `ready`

#### Scenario: 预算停止报告
- **WHEN** 任一停止预算命中
- **THEN** 报告使用稳定枚举标识首个生效停止原因，并保留不超过上限的安全诊断，且不得伪装为 `needs_input` 或 `blocked`

#### Scenario: Attention stop report
- **WHEN** Loop 因需要用户输入或外部阻塞在安全边界停止
- **THEN** 报告使用 `status=stopped`、稳定 `stop_reason`（`needs_input` 或 `blocked`）和 bounded attention metadata，resume 不得静默重放动作

#### Scenario: 离线端到端恢复验证
- **WHEN** 测试使用 MockClient 在 checkpoint 后模拟中断并恢复
- **THEN** 恢复执行不重做已完成条目，每种停止条件及 attention stop 均可由确定性断言验证且无需 API key

```

## openspec/changes/harden-loop-protocol-correctness/specs/tool-call-identity/spec.md

- Source: openspec/changes/harden-loop-protocol-correctness/specs/tool-call-identity/spec.md
- Lines: 1-16
- SHA256: 256709e15c5888017e7a570c371084ae36790fff7ca1617941e02a2a305963e8

```md
## ADDED Requirements

### Requirement: Tool-call identities are unique across protocol channels
ForgeAgent SHALL merge text-protocol and native tool calls by stable call ID before dispatch. Identical duplicates MAY be retained once, but a call ID whose tool name or normalized arguments differ across channels MUST be marked as a protocol conflict and MUST NOT be dispatched.

#### Scenario: Identical dual-channel call
- **WHEN** text and native channels contain the same call ID, tool name, and equivalent arguments
- **THEN** the parser exposes one dispatchable call for that ID

#### Scenario: Conflicting dual-channel call
- **WHEN** text and native channels contain the same call ID with different tool names or arguments
- **THEN** the parser records a bounded conflict error and no call with that ID is dispatched

#### Scenario: Distinct calls remain independent
- **WHEN** channels contain different call IDs
- **THEN** each valid call remains dispatchable exactly once

```
