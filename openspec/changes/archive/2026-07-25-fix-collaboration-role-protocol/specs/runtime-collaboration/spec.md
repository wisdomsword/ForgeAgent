## ADDED Requirements

### Requirement: 协作角色使用结构化提交门完成工作
Planner、Generator 和 Evaluator MUST 分别通过本角色 registry 中唯一的结构化 Submit 工具完成
角色。成功 Submit MUST 在持久状态保存后立即完成当前角色，并 MUST 阻止同一响应中后续工具
执行。普通 prose 或 `task_status.completed` MUST NOT 代替 required Submit；运行时 MAY 对首次
缺失提交提供一次有界结构化恢复提示。未注册 required Submit 的 single 模式 MUST 保持既有
完成语义。

#### Scenario: 成功提交立即完成角色
- **WHEN** 协作角色在同一响应中先执行合法准备工具，再成功调用本角色 Submit 工具，并在其后声明其他工具调用
- **THEN** 运行时按 parser 的确定性工具顺序执行到 Submit，将持久状态保存并完成角色，且不执行或审计 Submit 后的工具

#### Scenario: 完成声明不能替代提交
- **WHEN** 协作角色声明 completed 但未成功调用 required Submit
- **THEN** 运行时首次返回精确的缺失工具恢复提示，重复绕过提交时以 `invalid_role_submission` 结束该协作

#### Scenario: Single 完成语义保持兼容
- **WHEN** single Task 使用未登记 required completion tool 的 registry
- **THEN** Step 保持既有工具、prose recovery 和 `task_status` 完成行为

### Requirement: Generator Candidate 与当前 attempt 原子绑定
在 Duo/Triad 中，Generator MUST 成功调用零载荷 `SubmitCandidate` 才能进入 Evaluator。
`SubmitCandidate` MUST 在同一次 revision-checked 保存中递增 `generator_attempts`、将 phase 切换为
`evaluator` 并清空旧 `last_evaluation`。Generator 的普通 Task completion MUST NOT 推进 phase。
Evaluator MUST NOT 在当前 Candidate 尚未提交时启动。

#### Scenario: 当前 Candidate 提交后进入验收
- **WHEN** Generator 在 generator phase 成功调用 `SubmitCandidate` 且 state revision 未过期
- **THEN** 状态原子变为 evaluator phase、Generator attempt 恰好增加一次、旧 verdict 被清空，Runner 才能启动 Evaluator

#### Scenario: Candidate 提交失败不推进 phase
- **WHEN** `SubmitCandidate` 在错误 phase、过期 revision 或无效调用中失败
- **THEN** phase、attempt 和 verdict 保持不变，工具返回结构化失败并允许当前角色在剩余轮次修正

### Requirement: Verdict 只属于当前已提交 Candidate
Evaluator MUST 只验收 evaluator phase 中当前已提交的 Candidate。`SubmitEvaluation` MUST 在同一次
revision-checked 保存中写入覆盖冻结计划的 verdict 并递增 `evaluator_attempts`，但 MUST NOT 自行
决定 pass、reject、rejection count 或协作终态。拒绝回到 Generator 时，运行时 MUST 暂存旧 verdict
用于恢复拒绝反馈；下一次 `SubmitCandidate` 成功时 MUST 清空该 verdict。恢复时 evaluator phase
中的空 verdict MUST 重跑 Evaluator，非空 verdict MUST 直接交由 Runner 判定且不得重复调用模型。

#### Scenario: 拒绝后恢复 Generator 反馈
- **WHEN** Evaluator 提交失败 verdict，Runner 未达 rejection limit 并在进入新 Generator 前发生恢复
- **THEN** generator phase 保留旧 verdict，新的 Generator Task 收到该有界拒绝证据，且旧 verdict 不能被当作新 Candidate 的结果

#### Scenario: 已提交 verdict 恢复时不重复验收
- **WHEN** collaboration 从 evaluator phase 且 `last_evaluation` 非空的持久状态恢复
- **THEN** Runner 直接执行 pass/reject 判定，不创建新的 Evaluator Task，也不重复增加 evaluator attempt

#### Scenario: 待验收 Candidate 恢复
- **WHEN** collaboration 从 evaluator phase 且 `last_evaluation` 为空的持久状态恢复
- **THEN** Runner 为当前已提交 Candidate 创建 Evaluator Task，并要求结构化 `SubmitEvaluation`
