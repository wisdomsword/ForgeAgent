## Context

失败现场中 `generator_attempts=3`、`evaluator_attempts=3`、`rejections=2`，但 allowed root 始终只有 `.forgeagent`。终端没有出现 FileWrite 确认，证明三个 Generator attempt 都直接提交了空 Candidate；Evaluator 和拒绝反馈传递正常。

## Fix

保留现有通用 Generator prompt，并增加两层最小约束：

1. 通用提示明确要求：验收计划要求的文件尚不存在时，禁止调用 `SubmitCandidate`。
2. 仅当 Runner 已携带失败 verdict 启动新的 Generator Task 时，在 system prompt 末尾追加 rejection-correction 指令。该指令要求逐项处理失败证据；若证据报告文件缺失，必须先对该文件成功调用 `FileWrite`；不得在没有实质性 artifact 修正的情况下重新提交。

拒绝证据仍以 JSON task data 传递，Evaluator 仍独占验收。运行时不通过文件活动隐式判断 Candidate 是否有效，也不增加 manifest、payload、attempt 或重试预算。

## Excluded

- 不以文件系统活动作为 Submit 门，因为该信号无法可靠覆盖非文件任务、部分写入和回滚。
- 不提高 `max_rejections`，因为额外模型调用只会延迟同一协议错误。
- 不让 Generator 执行 Evaluator 的验收或提交证据。
