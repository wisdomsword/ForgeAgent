## 为什么

ForgeAgent 已有确定性的 20 项 golden core 与审计记录，但还没有稳定方式比较不同运行的结果，或发现 Harness 变更让“模型 + Harness”组合变好还是退化。M20 增加离线优先的评估记录与显式 opt-in 的独立 Evaluator，同时不削弱可信核心。

## 变更内容

- 增加版本化机器可读的评估记录契约，从 golden suite 结果和兼容的审计事件聚合 `first_pass_correctness`、`correction_rounds`、`cache_hit_rate` 与 golden 通过率。
- 增加本地趋势记录与比较命令；不需要服务、网络或凭证。
- 增加 manifest 基线守卫，在报告前拒绝删除、替换或降低可信核心标准。
- 增加 opt-in 独立 Evaluator，以独立构造的 Task 会话检查声明的外部产物并输出 pass/fail 证据。
- 保持确定性的 20 项离线 golden core 作为 CI 权威；Evaluator 不进入离线 CI 或普通任务执行。

## 能力范围

### 新能力

- `evaluation-metrics`：离线聚合、持久化与比较 golden/audit 证据。
- `independent-evaluator`：对外部可观察任务产物进行 opt-in 隔离评估。

### 修改能力

- `golden-validation-core`：为可信核心 manifest 增加固定基线，拒绝删除或降低场景标准。

## 影响

- 影响 golden runner/manifest、审计事件投影、CLI 命令和新增评估模块。
- 更新评估用法、威胁边界、里程碑计划等文档。
- 不增加运行时服务、外部依赖、HTTP schema 或默认模型调用，不放宽现有 20 项可信核心要求。
