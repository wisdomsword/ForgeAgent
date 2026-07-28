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
