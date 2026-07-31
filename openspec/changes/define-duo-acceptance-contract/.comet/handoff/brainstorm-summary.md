# Brainstorm Summary

- Change: define-duo-acceptance-contract
- Date: 2026-07-31

## 确认的技术方案

采用单项兼容方案：保留稳定计划项 ID `goal`，仅让 `_duo_plan(goal)` 根据 goal 的交付形态选择固定、可观察的 English-first 验收模板。分类顺序为产物/文件、验证/命令、文本/分析回退。模板不复制 goal 正文。

## 关键取舍与风险

- 保留单项计划避免旧 snapshot、digest、Evaluator 提交覆盖规则产生迁移。
- 不采用三个固定计划项，因为这会使旧单项 EvaluationItem 缺项并扩大测试与迁移面。
- 不采用自然语言拆句或 LLM 拆解器；关键词覆盖有限，但回退模板仍可观察且确定。
- 文件信号优先于验证信号；同时包含多类要求的复杂任务应使用 Triad Planner。

## 测试策略

至少三个 golden case 覆盖文件产物、测试验证、文本分析；额外断言禁止循环验收文案、相同 goal 计划稳定、计划不包含 raw goal、绝对路径或 secret，并验证旧持久化 snapshot 原样加载。

## Spec Patch

已在 runtime-collaboration delta spec 增加 Duo 默认计划可观察验收契约与四个场景。
