## 1. 通用提交终止协议

- [x] 1.1 为 ToolOutcome 和 ToolRegistry 增加通用 completion signal 与唯一 required tool 元数据
- [x] 1.2 以 TDD 实现 Step 的顺序截断、一次恢复和 single 兼容行为

## 2. Candidate 状态机

- [x] 2.1 以 TDD 新增零载荷 SubmitCandidate 及 Generator registry 组合
- [x] 2.2 让三个 Submit 工具原子计数并立即完成角色
- [x] 2.3 重构 Runner 成功/失败边界、verdict 判定和恢复路径，避免 attempt 双计

## 3. 协议与模式回归

- [x] 3.1 更新 Planner、Generator、Evaluator 提示与 required Submit 失败映射
- [x] 3.2 覆盖 Duo、Triad、Loop duo/triad、single、冻结计划、安全与审计回归

## 4. 验证

- [ ] 4.1 运行专项测试、ruff、完整 pytest 和 OpenSpec/Comet guard
- [ ] 4.2 在两个全新临时目录连续运行真实模型 Triad，并独立验证 pytest 与 calc.py CLI 输出
