## 1. 契约与兼容性

- [x] 1.1 新增冻结的 `LoopHandoff` 与仅供模型提交的候选校验，复用有界安全文本规则并保持完成项只增不减。
- [x] 1.2 加载时迁移旧字符串 `handoff`，不得执行其中内容，并保持 `schema` JSON 别名往返兼容。
- [x] 1.3 更新 Loop checkpoint 与下一轮上下文注入以使用结构化 handoff，同时保持公开报告计数字段不变。

## 2. 恢复边界

- [x] 2.1 将 `CheckpointTool` 写入限制为候选拥有的 handoff 字段，并在持久化前拒绝控制面字段。
- [x] 2.2 增加宿主拥有的有限提交恢复上限，只请求纠正提交，不重放历史工具或外部动作。
- [x] 2.3 保持恢复期间待处理/未知外部收据的停止门禁。

## 3. 验证与文档

- [x] 3.1 增加回归测试：合法更新、旧数据迁移、schema 别名、控制面拒绝、完成项只增、上下文投影和有限非重放恢复。
- [ ] 3.2 运行专项测试、全量 pytest、Ruff check/format、OpenSpec strict 校验和 `uv build`；修复回归但不发布。
- [ ] 3.3 记录 M40 验收证据，更新 `ACTION_PLAN.md`，创建 `milestones/milestone_040.md`，更新 `milestones/latest` 并归档 Comet change。
