# Brainstorm Summary

- Change: triad-mode
- Date: 2026-07-24

## 确认的技术方案

- 在现有 `Task` 上方增加固定串行 `CollaborationRunner`，不修改 `Step` 状态机，不引入通用 workflow。
- Duo 执行 Generator → Evaluator；Triad 执行 Planner → 确认/冻结 → Generator ⇄ Evaluator。
- Planner 与 Evaluator 通过 `SubmitPlan`、`SubmitEvaluation` 结构化工具提交结果；每个角色和每次打回均使用 fresh Task/client/runtime/registry。
- 协作状态以 `forgeagent.collaboration.v1` JSON 原子写入 `.forgeagent/collaborations/`；Loop 只冻结引用、mode 与计划摘要。
- Evaluator registry 默认只有 FileRead/FileList/SubmitEvaluation，不复用可写 Exec；编程任务路由采用确定性规则表，非通用模型分类。
- CLI/REPL 支持显式 Duo/Triad，HTTP 只允许客户端选 mode，角色模型、tier、打回与 Planner 预授权保持 server-owned。

## 关键取舍与风险

- 三角色成本高：非编程任务默认 single，默认最多 2 次打回，公开 usage/attempt 计数。
- Evaluator 可能误判：要求逐项结构化覆盖、外部可观察证据、只读工具和离线对抗回放。
- Planner 标准不可信：交互确认或服务所有者预授权，冻结 digest，后续漂移 fail closed。
- 规则路由可能误判：只在动作与代码产物组合明确时强制，显式 mode 兜底，冲突走确认或 headless 拒绝。
- store 有少量安全代码重复：保持局部实现并复用 M21 测试向量，不为两个用例抽通用 repository。

## 测试策略

- TDD 覆盖严格模型、原子 store、计划/verdict 工具、路由纯函数和安全投影。
- Duo mock replay 覆盖错误完成拦截、拒绝后修复、上限停止、取消、角色错误和 usage 聚合。
- Triad mock replay 覆盖确认/拒绝、冻结计划禁删改、逐项验收、角色隔离和 headless 策略。
- 集成覆盖 CLI/REPL/HTTP/Loop、普通路径零变化、并发隔离、审计和旧配置/checkpoint 兼容。
- 完成门禁：专项/全量 pytest、golden 20/20、ruff、build、OpenSpec strict、diff check 和独立代码审查。

## Spec Patch

无。OpenSpec delta specs 已包含设计中发现的 Loop 旧边界替换、Evaluator 只读要求和计划冻结场景。
