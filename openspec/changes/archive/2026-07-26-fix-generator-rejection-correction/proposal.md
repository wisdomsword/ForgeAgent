## Why

M22 真实模型冒烟显示 Generator 可以在未创建任何要求文件时成功调用 `SubmitCandidate`，并在 Evaluator 明确报告文件不存在后连续原样重提，最终耗尽 rejection limit。现有状态机正确传递了逐项反馈，但拒绝修正提示对真实模型不够醒目。

## What Changes

- 强化 Generator 首次提交约束：要求文件不存在时不得调用 `SubmitCandidate`。
- 对 rejection attempt 注入独立的高优先级修正指令：必须先根据失败证据执行实质性 artifact 操作，缺文件必须先成功 `FileWrite`，不得原样重提。
- 保持零载荷 Candidate、Evaluator 独占验收、attempt/rejection 预算和人工计划确认不变。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`: 明确 rejection attempt 必须被提示先修正失败产物，再提交新 Candidate。

## Impact

影响 Generator 协作提示、拒绝轮次组装和对应离线测试；不改变公开接口、持久化 schema、工具权限或依赖。
