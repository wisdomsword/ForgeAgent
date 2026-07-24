## 1. Loop 状态与持久化

- [x] 1.1 以严格 Pydantic 模型实现版本化 Loop budgets、checkpoint、终态报告和不变量校验
- [x] 1.2 实现 allowed-root/symlink/大小守卫与 sibling temp + fsync + replace 原子 checkpoint store
- [x] 1.3 实现 Loop 专用 Checkpoint 工具、边界限制和最小 system prompt 增量

## 2. Loop 执行与停止条件

- [x] 2.1 实现 Task 之上的 LoopRunner、新建/resume、冻结配置和有界 handoff 渲染
- [x] 2.2 实现累计 rounds/token/wall-clock/consecutive-failure/cancel 停止语义与稳定优先级
- [x] 2.3 实现有界失败摘要、不可恢复失败分类、Loop 生命周期审计和资源关闭

## 3. 运行入口

- [x] 3.1 新增 `forgeagent loop` 新建/resume CLI、参数校验、输出与退出码，并保持 `run`/REPL 不变
- [ ] 3.2 扩展现有 HTTP submit schema、runner factory、公开投影和 cancellation 以支持 Loop 模式
- [ ] 3.3 添加 cron/launchd/systemd 调用示例和只产出报告的端到端 Loop 示例

## 4. 验证与文档

- [ ] 4.1 添加 checkpoint 中断恢复、不重做已完成条目、损坏/逃逸/原子失败的确定性测试
- [ ] 4.2 添加每种停止条件、失败收敛、usage unavailable、并发隔离和审计最小披露测试
- [ ] 4.3 更新 README、文本协议、威胁模型、ACTION_PLAN 与 golden 候选/可信核心边界说明
- [ ] 4.4 运行专项/全量/golden/Ruff/build/OpenSpec strict 验证并完成技术、代码、验收三轮评审
