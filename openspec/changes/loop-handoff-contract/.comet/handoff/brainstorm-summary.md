# Brainstorm Summary

- Change: loop-handoff-contract
- Date: 2026-07-31

## 确认的技术方案

- 新 checkpoint 的 `handoff` 是唯一结构化事实源，包含冻结的 `completed_items`、`open_questions`、`summary`。
- 旧顶层完成项/问题项与旧字符串 `handoff` 仅在加载 validator 中迁移；代码层保留只读属性兼容旧调用，读取不执行文本。
- `CheckpointArgs` 只暴露候选字段；宿主从当前 checkpoint 保留 goal、budgets、permissions、collaboration、plan、attention、终态和恢复策略。
- required submission 允许最多两次纠正提示；提示只请求重新提交当前状态，不重放任何工具或外部动作。

## 关键取舍与风险

- 选择嵌套结构而非重复的顶层/嵌套双写，避免两个事实源漂移。
- 新写入 checkpoint 的 handoff 值形状改变，但旧 JSON 可读、`schema` 键保持不变，且不批量改写旧文件。
- `completed_items` 仍只允许追加；摘要和 open questions 可替换但有界并过滤危险 Unicode。

## 测试策略

- 先写失败测试覆盖结构化 round-trip、legacy migration、旧属性兼容、候选控制面拒绝、完成项删除拒绝、suffix 不可信标记和两次恢复/第三次失败。
- focused pytest 后运行全量 pytest、Ruff check/format、OpenSpec strict 和 `uv build`。

## Spec Patch

无。
