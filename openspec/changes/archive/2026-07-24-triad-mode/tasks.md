## 1. 协作核心与持久化

- [x] 1.1 以 TDD 定义协作 mode、冻结计划、逐项 verdict、状态/report、usage 和 stable reason 的严格模型与不变量
- [x] 1.2 实现 symlink-safe、revision-safe、原子且有界的 `CollaborationStore`，覆盖损坏、换绑、竞态和关闭路径
- [x] 1.3 实现 `SubmitPlan`/`SubmitEvaluation` 结构化工具、角色专用 registry 与 prompt 数据投影
- [x] 1.4 实现纯函数编程任务路由、显式模式冲突和表驱动中英文/文件产物边界测试

## 2. Duo 阶段

- [x] 2.1 实现 fresh Generator/Evaluator Task builder、只读 Evaluator 能力和角色资源关闭
- [x] 2.2 实现 Duo 提交验收、逐项判定、证据打回、默认 2 次 rejection 上限、取消和失败优先级
- [x] 2.3 添加离线 mock replay：错误完成被拦截、拒绝后修复通过、反复拒绝停止、角色异常与 usage 聚合
- [x] 2.4 完成 Duo 专项审查并修复 Critical/Important 问题后再进入 Triad

## 3. Triad 阶段

- [x] 3.1 实现 Planner 计划生成、WHAT-only 校验、规范化 digest、交互确认和 headless deny/preauthorize
- [x] 3.2 实现冻结计划完整性守卫、Triad 逐项 Generator/Evaluator 流转与计划漂移 fail-closed
- [x] 3.3 添加离线 mock replay：确认/拒绝、禁删改降标、逐项通过、打回修复和 Planner/Generator/Evaluator 隔离
- [x] 3.4 完成 Triad 核心专项审查并修复 Critical/Important 问题后再接入口

## 4. CLI、REPL、HTTP 与 Loop 接入

- [x] 4.1 为 `run` 增加模式/角色模型/打回参数，为 REPL 增加 `/duo`、`/triad`、help/completion 和安全输出
- [x] 4.2 扩展 HTTP strict schema、server-owned 协作策略、runner union、状态/终态投影、取消/容量/TTL 和安全错误
- [x] 4.3 扩展 Loop checkpoint/runner 冻结协作 mode、state ID、计划 digest、累计预算和 resume 一致性，保持 single Loop 不变
- [x] 4.4 添加 CLI/REPL/HTTP/Loop 集成、普通路径零变化、并发隔离和审计静态契约测试

## 5. 文档、评审与验证

- [x] 5.1 更新 README、文本协议、HTTP 文档、威胁模型、配置示例、ACTION_PLAN 与 opt-in golden 对比说明
- [x] 5.2 运行专项/全量 pytest、trusted golden 20/20、ruff、build、OpenSpec strict 与 diff check
- [x] 5.3 委派独立 code review，对完整 M22 diff 做两轮自审，发现问题立即修复并重跑受影响门禁
- [x] 5.4 产出 M22 验证报告与 `milestones/milestone_022.md`，更新 latest，完成主分支提交和 OpenSpec 归档
