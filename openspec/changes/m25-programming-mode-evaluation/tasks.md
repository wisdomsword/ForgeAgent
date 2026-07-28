## 1. 历史证据保护与测试基线

- [x] 1.1 为 M23 protocol、正式 environment/raw/summary/report 建立不可变性回归检查，并确认现有 M23 专项测试通过
- [x] 1.2 为 M25 独立 schema、证据根和拒绝混入 M23 记录编写失败优先的离线合同

## 2. 多模型协议与固定排程

- [x] 2.1 扩展评估协议、RunSpec、raw 和 environment 模型，支持模型列表、provider route hash 和任务族，同时保持 M23 v2 向后兼容
- [x] 2.2 实现并测试 9 × 2 × 3 × 5 的 270-run 确定性排程、全局模式位置平衡、唯一 identity 和安全续跑

## 3. 真实编程任务族

- [x] 3.1 定义两个 bugfix、两个 feature 和两个 refactor 自包含 Python 项目 fixture，覆盖单文件与多文件修改
- [x] 3.2 为六个任务固定不可变文件、候选文件和模式无关外部检查，并完成可解性、歧义与检查强度两轮审计
- [x] 3.3 创建 `docs/evaluation/m25/protocol.json`，保留三个 M23 基线任务并固定两个模型、五次重复和九个任务

## 4. 分层聚合与中立报告

- [x] 4.1 扩展完整性校验和聚合，按模型、模式、任务族与任务复算全部质量、成本、调用、延迟和 usage 缺失指标
- [x] 4.2 扩展机器 summary 与人工报告，保留 Single 的 N/A 语义并禁止 rank、winner、best-mode 或自动优越性结论
- [x] 4.3 运行 M23/M25 专项、Ruff 和证据安全测试，确认 270 个 synthetic raw 可重复聚合且 M23 正式文件 hash 未变

## 5. 真实模型证据批次

- [x] 5.1 提交实现并执行双模型 credential/route、协议 hash、环境、tracked-clean 和 270-run/轮次/token 上限 preflight
- [x] 5.2 执行或安全续跑 270 次真实模型评估，保存 270 份终态 raw，任何不完整或混合批次均不聚合
- [x] 5.3 从完整 raw 独立复算 `summary.json` 和 `report.md`，核对所有分母、失败、usage 缺失、模型与任务族切片

## 6. 验证与里程碑收尾

- [x] 6.1 完成两轮最终自审，修复错误、前后不一致、遗漏、数据泄漏、隐式排名和 M23 漂移
- [x] 6.2 运行聚焦测试、全量 pytest、golden、Ruff、build、OpenSpec strict 和 `git diff --check`
- [x] 6.3 更新 `ACTION_PLAN.md`、评估文档与 M25 里程碑，记录真实证据范围、限制、验证输出和续接指引
