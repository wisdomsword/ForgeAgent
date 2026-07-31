## 1. 投影契约测试

- [x] 1.1 为 Task/Loop 已知原因到 Collaboration status、stop reason 和 attention 的映射编写失败测试。
- [x] 1.2 为资源耗尽、needs input、blocked、cancelled、正常打回和失败类别补齐 Runner/模型回归测试。

## 2. 执行与公开目标边界

- [x] 2.1 为合法绝对路径在内部 role task data 中保留、在公开 handoff 中脱敏编写失败测试。
- [x] 2.2 为 handoff/report/audit 不泄漏 secret、raw goal、绝对路径或原始异常编写回归测试。

## 3. 最小实现

- [x] 3.1 实现单一确定性 stop projection helper，扩展 CollaborationState/Report 允许集合和安全 attention 字段。
- [x] 3.2 在角色失败边界应用投影，同时保持结构化提交、取消、状态失败和恢复语义。
- [x] 3.3 将内部 execution goal 与 `HandoffPacket.goal` 的 public projection 显式分离。

## 4. 验证与收尾

- [x] 4.1 运行 focused pytest、Ruff、format 和 OpenSpec strict，并修复回归。
- [x] 4.2 运行全量 pytest 与构建验证，记录不执行 PyPI、tag、push 或发布自动化。
- [x] 4.3 完成两轮代码/契约自评审并记录验证报告。
