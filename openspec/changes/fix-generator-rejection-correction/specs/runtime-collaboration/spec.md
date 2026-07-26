## MODIFIED Requirements

### Requirement: 打回环有界且证据驱动
Evaluator 失败 SHALL 把有界、脱敏、逐项证据返回新的 Generator Task；每次修正 MUST 使用新的 Generator conversation，并保留原始目标与冻结计划。新的 Generator Task MUST 被明确要求先根据失败证据实质性修正 Candidate，再调用 `SubmitCandidate`；当失败证据报告要求文件不存在时，Generator MUST 被要求先成功执行对应 `FileWrite`，不得在 Candidate 未发生相应修正时原样重提。系统 MUST 支持可配置的最大打回次数，默认 2；达到上限、取消、角色失败或预算不足时 MUST 以稳定原因停止，不得无限重试。

#### Scenario: 缺失文件打回后先修正
- **WHEN** Evaluator 拒绝 Candidate 并明确报告冻结计划要求的文件不存在
- **THEN** 下一 Generator Task 的系统提示明确要求先成功创建对应文件、禁止原样调用 `SubmitCandidate`，且逐项拒绝证据继续作为有界 task data 提供
