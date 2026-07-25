## MODIFIED Requirements

### Requirement: Evaluator 独立验收并决定协作完成
在 Duo/Triad 模式中，Generator MUST 成功调用零载荷 `SubmitCandidate` 提交当前候选；普通 prose、
`task_status.completed` 或其他 Task 终态 MUST NOT 代替候选提交，也 MUST NOT 启动 Evaluator。
Evaluator MUST 使用结构化逐项结果判定外部可观察产物；只有所有要求通过时协作结果才能为
completed。Evaluator 默认 MUST 使用 restricted tier，写工具 MUST 不可用，且其模型和 tier MAY
与 Generator 独立配置但不得扩大服务端或 CLI 所有者授予的权限。

#### Scenario: Generator 未结构化提交被拦截
- **WHEN** Generator 声明完成但未成功调用当前 attempt 的 `SubmitCandidate`
- **THEN** 运行时不得启动 Evaluator，并在一次有界恢复仍失败后以 `invalid_role_submission` 结束协作

#### Scenario: Generator 候选验收失败
- **WHEN** Generator 成功调用 `SubmitCandidate`，但 Evaluator 发现至少一项外部可观察行为不满足
- **THEN** 协作结果保持未完成并生成有界、脱敏的实际行为、期望行为和定位证据

#### Scenario: 全部验收通过
- **WHEN** Evaluator 对冻结计划或 Duo 验收目标的全部项目返回 pass
- **THEN** 系统返回 completed，并保留 Generator 与 Evaluator 的轮次、usage 和验收计数投影

#### Scenario: Evaluator 无写权限
- **WHEN** Evaluator 尝试修改被验收产物
- **THEN** 请求被工具注册表、确认门或 sandbox 拒绝，且该尝试不能形成 pass
