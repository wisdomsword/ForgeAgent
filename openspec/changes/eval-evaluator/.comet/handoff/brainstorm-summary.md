# Brainstorm Summary

- Change: eval-evaluator
- Date: 2026-07-24

## 确认的技术方案

- 复用 `tests.golden.runner` 的 `forgeagent.golden.v1` JSON 与现有脱敏 `AuditEvent` JSONL，不引入数据库或服务。
- 新增 `src/forgeagent/evaluation.py` 作为纯函数聚合、严格安全投影、原子 record/index 持久化边界；CLI 只负责参数解析与展示。
- first-pass/correction 指标只接受明确的结构化 Task/golden outcome 投影；不从 LLM prose 或 audit 事件猜测。
- cache-hit-rate 只使用 `llm.outcome` 中已存在且有合法分母的 usage/cache 字段；缺失时返回 null。
- trusted-core manifest 增加仓库内 canonical fingerprint，runner preflight 先校验 fingerprint，再执行场景。
- Evaluator 通过显式 opt-in CLI facade 创建独立 Task，不传 Generator conversation、Memory、project Skills 或 Generator audit sink；产物只接受 evaluation-root 下的有界相对 manifest。

## 关键取舍与风险

- 不新增常驻服务、HTTP API、Planner、后台 scheduler 或默认模型调用。
- LLM Evaluator 非确定，只用于真实模型 opt-in；离线 CI 仍由 20 项脚本判定。
- 评估记录不得持久化 prompt、raw tool args、绝对路径或 secret；invalid historical records 固定诊断后跳过。
- 当前 CLI/Task 装配较集中，优先加最小 helper，不重构现有运行时。

## 测试策略

- 先为 manifest fingerprint、聚合公式、null 可用性、趋势比较、safe projection 写 RED 测试。
- 用 MockClient 验证 evaluator 与 Generator 上下文隔离、known-fail 100% 检出、缺凭证 fail-fast。
- 保持 golden 20/20、全量 pytest、ruff、build、OpenSpec strict 为最终门禁。

## Spec Patch

无。现有 delta spec 已覆盖上述边界；实现若发现中等范围接口变化，先停止并回写 spec。
