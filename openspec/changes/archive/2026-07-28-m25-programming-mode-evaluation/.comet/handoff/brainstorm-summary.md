# Brainstorm Summary

- Change: `m25-programming-mode-evaluation`
- Date: 2026-07-27

## 确认的技术方案

- 使用同一个 `scripts/m23_mode_evaluation.py` 承载 M23 v2 与 M25 v1，保持现有 CLI；不复制大型 harness，也不预先拆共享框架。
- 保留 M23 的协议、任务、RunSpec、environment 和 raw Pydantic 类不变；为 M25 新增严格模型，并通过 schema 分派与少量 helper 共享执行、安全和统计逻辑，避免默认字段改变 M23 hash。
- M25 固定九个任务、两个模型、三种模式、五次重复。三种 Latin 模式顺序按 18 个任务—模型单元偏移，使每个模式在全批次三个位置各出现 30 次。
- M25 使用独立 protocol/raw/environment/summary schema 与 `docs/evaluation/m25/` 根；任何 M23 raw 或混合 route/environment 记录均被拒绝。
- 主要汇总按模型再按模式展示，并按任务族与任务切片；不生成跨模型综合分数、显著性检验、排名或 winner。

## 关键取舍与风险

- 选择“向后兼容扩展”而非“共享 core + 双 wrapper”或“复制 M25 harness”，以最小 diff 复用已经审计的执行与安全逻辑。
- M23 hash 是硬兼容边界；M25 新字段不得进入 M23 的 `model_dump()`。
- 五次重复在单个任务—模型单元内不能完全平衡三种位置，但 18 个单元可让全批次精确平衡。
- 真实费用无法在缺少稳定 provider 定价与预知 token 的情况下计算为可靠美元上限；协议以 270 run、固定轮次、rejection、输出 token 和 timeout 上限约束成本。
- 真实批次只允许在离线门禁、双路由 preflight、提交绑定和 tracked-clean 检查通过后开始；原子 raw 支持续跑，聚合拒绝不完整集合。

## 测试策略

- 先锁定 M23 protocol/hash、27-run schedule、正式 evidence hash 和现有 53 项专项合同。
- TDD 增加 M25 schema、270-run identity、位置平衡、双 route environment、续跑冲突、混合集拒绝与分层聚合测试。
- 六个编程任务各自运行外部检查的失败 fixture 与参考解，审计可解性、歧义、不可变文件和候选文件边界。
- 完成后运行 M23/M25 专项、Ruff、全量 pytest、golden、build、OpenSpec strict、独立复算与敏感字段扫描。

## Spec Patch

无。现有 delta spec 已覆盖独立 schema、历史隔离、270-run 排程、任务族、双模型指标、严格聚合与中立报告。
