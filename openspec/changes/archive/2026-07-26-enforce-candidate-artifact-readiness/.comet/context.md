# Comet Design Handoff

- Change: enforce-candidate-artifact-readiness
- Phase: design
- Mode: compact
- Context hash: a5d5a44a0f812a96fcd801606c9e6920edbcb93c0ddb67f5ca178912d2c78d6c

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/enforce-candidate-artifact-readiness/proposal.md

- Source: openspec/changes/enforce-candidate-artifact-readiness/proposal.md
- Lines: 1-29
- SHA256: 81682cbfb13d5381fed9dfcf7f581815803f54ae2220f8f43ea94a032290f762

```md
## Why

真实模型 M22 Triad 人类冒烟连续出现 Generator 在未创建任何目标文件时直接成功调用零载荷 `SubmitCandidate`。当前运行时把该空候选视为合法提交，只能由 Evaluator 事后拒绝；模型随后重复原样提交，最终稳定耗尽 rejection limit。提示词加固已经被真实运行证明不足，因此候选提交边界需要一个宿主可验证、默认关闭的最小就绪条件。

## What Changes

- 允许宿主为一次协作冻结一组有界的顶层候选文件名。
- `SubmitCandidate` 仅在这些名字都解析为 allowed root 下的非符号链接普通文件时成功；失败保持当前 phase、attempt 和 verdict 不变，并向当前 Generator Step 返回有界结构化反馈。
- 默认要求列表为空，保持现有 single、Duo、Triad、Loop、HTTP 与嵌入调用行为不变。
- M22 人类冒烟通过私有子进程环境配置要求 `calc.py` 和 `test_calc.py`，不新增公开 CLI 参数，也不取消 Planner 或 FileWrite 人工确认。
- 更新 README、ACTION_PLAN 与离线回归，明确该门禁只验证候选载体存在，不验收内容正确性。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`: 增加宿主冻结候选文件存在性门禁及其原子失败语义。
- `triad-human-smoke`: 一键脚本为固定编程任务注入 `calc.py`、`test_calc.py` 候选就绪要求。

## Impact

- 代码：`src/forgeagent/collaboration.py`、`src/forgeagent/cli.py`、`scripts/m22-triad-human-smoke.py`。
- 测试：协作工具/Runner、CLI 私有配置与 M22 脚本离线测试。
- 文档与规格：README、ACTION_PLAN、两个现有 OpenSpec capability。
- 不新增依赖、持久状态字段、公开 CLI 参数、SubmitCandidate payload 或 Evaluator 权限。

```

## openspec/changes/enforce-candidate-artifact-readiness/design.md

- Source: openspec/changes/enforce-candidate-artifact-readiness/design.md
- Lines: 1-66
- SHA256: d74e060a8207d27f6c2be223ec801d4c95057640a2d6ffdbbfe9133a1ced46aa

```md
## Context

`SubmitCandidate` 是 Generator 的零载荷原子提交边界：成功时切换到 evaluator phase、递增 attempt 并清空旧 verdict。它当前不知道工作目录里是否存在任何候选产物，因此真实模型可以把“没有执行任何 `FileWrite`”的空目录提交给 Evaluator。Evaluator 能准确拒绝，但无法让一个持续忽略提示词的 Generator 改变行为，最终会耗尽拒绝预算。

该问题已经经过三层实证：协作状态显示 `generator_attempts=3`、`evaluator_attempts=3`、`rejections=2`；Evaluator 三次只观察到 `.forgeagent`；Generator rejection prompt 加固后问题仍复现。因此修复必须落在成功提交的宿主边界，而不是继续依赖提示词。

## Goals / Non-Goals

**Goals:**

- 让宿主可选地冻结一组 Candidate 必须具备的顶层普通文件名。
- 在 `SubmitCandidate` 原子状态变更前安全检查这些文件；缺失或不安全时返回可恢复工具失败。
- 保持零载荷 Submit 协议、Evaluator 内容验收独占权、人工确认与默认兼容性。
- 让 M22 人类冒烟的固定任务声明 `calc.py` 和 `test_calc.py`，阻断真实模型空候选提交。

**Non-Goals:**

- 不检查文件内容、大小、语法、测试结果或验收正确性。
- 不新增 manifest、SubmitCandidate 参数、持久状态字段、公开 CLI 参数或通用产物推断。
- 不保证 Submit 后文件不可修改；Evaluator 仍验收当时可观察的实际产物。
- 不改变普通 single、未配置门禁的 Duo/Triad/Loop/HTTP 行为。

## Decisions

### 1. 使用宿主冻结的文件名列表，而不是提示词或 manifest

`required_candidate_files` 是一次 Runner 的宿主配置，默认空元组。它只表达“Candidate 具备最小外部载体”，不携带模型生成的证据，也不进入协作持久状态。M22 脚本通过私有子进程环境 JSON 传入固定列表，CLI 严格解析后装配到本次 Runner；不暴露新的用户命令面。

排除继续加固提示词：真实模型已多次无视同类约束。排除 Generator manifest：它会改变零载荷协议、增加非权威路径数据，并模糊 Evaluator 独占验收职责。排除运行时自动推断文件活动：无法可靠区分部分写入、目标文件和无关副作用。

### 2. 门禁属于 `SubmitCandidateTool`，失败不触碰持久状态

`CollaborationRunner` 把已规范化的文件名传给 generator registry，registry 构造配置化 `SubmitCandidateTool`。工具先验证当前 phase/revision，再检查要求文件；只有全部通过才执行现有 CAS 保存。检查失败返回 `ToolOutcome(success=False)`，Step 会把精确缺失文件反馈给同一个 Generator conversation；phase、attempt、verdict 和 rejection count 均不变。

这保留现有职责边界：Step 仍只理解通用 ToolOutcome，Runner 不识别文件系统细节，Evaluator 仍决定 Candidate 是否满足冻结计划。

### 3. 文件名和文件对象均采用 fail-closed 安全校验

配置最多 16 项，每项是 1-128 字符的 ASCII 顶层安全文件名，只允许字母、数字、点、下划线和连字符；拒绝重复、绝对路径、分隔符、`.`、`..` 与控制字符。CLI 对私有 JSON 使用稳定、无回显的配置错误；Runner/工具边界再次规范化，避免嵌入调用绕过。

提交检查以 allowed root 的目录描述符为锚，使用 `O_NOFOLLOW` 打开每个顶层目标并以 `fstat` 确认普通文件，同时在检查前后验证 root 的 device/inode 绑定。符号链接、目录、缺失、不可安全打开或 root 重绑定均按未就绪处理。反馈只列出已冻结的安全相对文件名，不包含绝对路径或文件内容。

### 4. M22 私有接线不改变人工确认

`scripts/m22-triad-human-smoke.py` 在已有 context-budget 私有环境旁增加候选文件 JSON。Planner 计划仍由终端人工批准；restricted `FileWrite` 仍走现有 confirmer。Generator 若先提交，会在同一 Task 收到“必须先创建 calc.py/test_calc.py”的工具反馈，随后正常调用 FileWrite 时仍会逐项请求人工确认。

## Risks / Trade-offs

- **[模型可能创建空文件再提交]** → 门禁只承诺载体存在；Evaluator 会拒绝内容错误。继续扩大到内容/大小检查会侵占 Evaluator 职责，本 change 不做。
- **[检查与 Evaluator 之间文件可能变化]** → 这是既有共享工作目录语义；门禁不是快照或冻结机制，Evaluator 以实际观察为准。
- **[私有环境被外部设置]** → 该配置只能收紧 Candidate 提交，不扩大权限；严格有界解析且不回显原值。
- **[平台缺少安全 open flags]** → 门禁 fail closed，SubmitCandidate 返回结构化失败；未配置门禁的现有路径不受影响。
- **[额外文件系统检查增加少量延迟]** → 仅配置时执行，最多 16 个顶层 metadata/open 操作，可忽略不计。

## Migration Plan

1. 先增加 RED 测试，证明空候选目前可成功提交及 M22 子进程未注入要求。
2. 实现内部规范化、SubmitCandidate 安全检查与 Runner/CLI 接线。
3. 更新 M22 脚本、文档和 delta specs，运行定向与全量验证。
4. 真实模型验证继续由人工执行一键脚本；本地自动验证不消耗凭证。

回滚只需移除 M22 私有环境注入和可选参数接线；默认空配置本身不改变状态 schema 或持久数据，无迁移步骤。

## Open Questions

无。文件集合、失败语义、兼容边界与验收职责均已在两轮自审中确定。

```

## openspec/changes/enforce-candidate-artifact-readiness/tasks.md

- Source: openspec/changes/enforce-candidate-artifact-readiness/tasks.md
- Lines: 1-17
- SHA256: 1ed140a4aa54142f548ccc1528b8ff1dfd1f5176173e0eaefa2a0e75f96b6786

```md
## 1. RED：冻结候选文件门禁合同

- [ ] 1.1 为 `SubmitCandidate` 增加缺失文件、符号链接/目录拒绝、状态不推进和默认兼容的失败测试
- [ ] 1.2 为 CLI 私有候选文件 JSON 增加缺省、合法、有界非法与无敏感值回显测试
- [ ] 1.3 为 M22 脚本增加子进程注入 `calc.py`/`test_calc.py` 且不改变人工确认的离线测试

## 2. GREEN：实现最小宿主门禁

- [ ] 2.1 实现有界顶层文件名规范化与基于目录描述符的普通文件检查
- [ ] 2.2 将可选要求从 `run_collaboration_once` 传入 Runner、generator registry 与 `SubmitCandidateTool`
- [ ] 2.3 在 CLI 解析私有环境配置，并由 M22 脚本仅对子进程注入固定要求

## 3. 文档与验证

- [ ] 3.1 更新 README、ACTION_PLAN 与相关规格，说明门禁职责和真实人工复测方法
- [ ] 3.2 运行定向测试、完整 pytest、Ruff、build、OpenSpec strict 与 diff check
- [ ] 3.3 完成标准代码审查、修复 findings，并记录真实模型验证仍需人工批准执行

```

## openspec/changes/enforce-candidate-artifact-readiness/specs/runtime-collaboration/spec.md

- Source: openspec/changes/enforce-candidate-artifact-readiness/specs/runtime-collaboration/spec.md
- Lines: 1-20
- SHA256: 68e1adac747c7e0d9625786aa2bf5771f4cb090675b82f8856ffc46b3459add6

```md
## ADDED Requirements

### Requirement: 宿主可冻结 Candidate 最小文件就绪门
协作宿主 SHALL 能为一次 Duo/Triad Runner 冻结零个或多个有界的顶层候选文件名。配置非空时，`SubmitCandidate` MUST 在原子状态变更前确认每个名字在 allowed root 下对应非符号链接普通文件；任一文件缺失、类型不安全、无法安全打开或 project root 绑定变化时，提交 MUST 返回结构化失败并保持 phase、Generator attempt、旧 verdict 与 rejection count 不变。该门禁 MUST NOT 读取或判断文件内容，Evaluator 仍独占冻结计划的逐项验收权。未配置文件时 MUST 保持现有 Candidate 提交行为。

#### Scenario: 空 Candidate 被当前 Generator Step 拦截
- **WHEN** 宿主要求 `calc.py` 和 `test_calc.py`，Generator 在两个文件尚未成为 allowed root 下普通文件时调用 `SubmitCandidate`
- **THEN** 工具返回列出缺失安全相对文件名的有界失败，协作保持 generator phase 且 attempt/verdict/rejection 均不改变，当前 Generator 可在剩余轮次调用 `FileWrite` 后重试

#### Scenario: 文件就绪后原子提交
- **WHEN** 所有宿主冻结文件都已是 allowed root 下的非符号链接普通文件，且当前 phase/revision 有效
- **THEN** `SubmitCandidate` 沿用既有原子语义切换到 evaluator phase、递增一次 Generator attempt 并清空旧 verdict

#### Scenario: 符号链接或目录不能满足门禁
- **WHEN** 任一要求名字对应符号链接、目录或 project root 在检查期间发生重绑定
- **THEN** 运行时按 Candidate 未就绪处理且不推进持久状态，不跟随链接读取或泄露宿主路径

#### Scenario: 默认协作路径保持兼容
- **WHEN** single 模式运行，或 Duo/Triad/Loop/HTTP 宿主未配置候选文件要求
- **THEN** 系统不执行额外 Candidate 文件门禁，既有提交、恢复与完成语义保持不变

```

## openspec/changes/enforce-candidate-artifact-readiness/specs/triad-human-smoke/spec.md

- Source: openspec/changes/enforce-candidate-artifact-readiness/specs/triad-human-smoke/spec.md
- Lines: 1-12
- SHA256: 62cb8d71bac7c68e6d4153a49862b57bc6a4f338c25ac4178d9ba444ddb8a526

```md
## MODIFIED Requirements

### Requirement: 一键脚本运行真实模型 Triad 并保留人工计划确认
仓库 MUST 提供单命令人类冒烟入口，在隔离工作目录中使用现有 ForgeAgent CLI 运行真实模型 Triad。脚本 MUST 保留 Planner 计划与 restricted `FileWrite` 的终端人工确认，不得隐式批准；默认模型 MUST 可通过有界、明确的环境变量覆盖，且脚本不得打印 API key 或其他 credential。脚本 MUST 为本次验收隔离足够的 context feedback 预算，不得因用户全局低 feedback 限额而让 Evaluator 对完整短文件产生截断假拒绝，也不得修改或复制用户配置中的 credential。脚本 MUST 仅为本次子进程冻结 `calc.py` 与 `test_calc.py` 候选文件就绪要求，使缺少目标文件的 `SubmitCandidate` 在进入 Evaluator 前返回当前 Generator 可恢复的结构化失败。

#### Scenario: 用户配置低 feedback 限额
- **WHEN** 用户全局配置的 `tool_result_max_tokens` 和 `round_feedback_max_tokens` 低于本冒烟验收所需值
- **THEN** 一键脚本仅在本次 ForgeAgent 子进程中使用固定的足够预算，用户配置文件保持不变，Planner 人工确认和模型路由仍正常工作

#### Scenario: Generator 先提交空 Candidate
- **WHEN** 真实 Generator 尚未创建 `calc.py` 或 `test_calc.py` 就调用 `SubmitCandidate`
- **THEN** 本次子进程的宿主门禁拒绝提交并精确反馈缺失文件，Evaluator 不启动且人工 FileWrite 确认不被绕过

```
