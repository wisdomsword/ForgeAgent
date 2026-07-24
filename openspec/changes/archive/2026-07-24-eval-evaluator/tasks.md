## 1. Comet 与基线准备

- [x] 1.1 初始化 `eval-evaluator` 的 Comet 状态，生成 OpenSpec handoff，并记录实施基准提交。
- [x] 1.2 为精确的 20 项可信核心 manifest 增加仓库内 canonical fingerprint 与表驱动漂移测试。

## 2. 评估证据与指标

- [x] 2.1 增加 `forgeagent.evaluation.v1` typed record、安全证据投影和纯函数指标聚合。
- [x] 2.2 增加原子本地 record 持久化、有界趋势索引、兼容性检查和 CLI/报告渲染。
- [x] 2.3 增加完整、缺失、无效及历史指标证据的离线表驱动测试。

## 3. 独立 Evaluator

- [x] 3.1 定义有界 evaluator 契约、产物 manifest 校验和固定安全结果投影。
- [x] 3.2 接入显式 opt-in CLI evaluator，使用不带 Generator 上下文、Memory 或 project Skills 的独立 Task 会话。
- [x] 3.3 增加 mock-client 隔离测试与已知失败产物 fixture，断言 100% 检出；所有真实模型调用保持 opt-in。

## 4. 文档与完成

- [x] 4.1 更新 README、威胁模型、文本协议或 CLI help、ACTION_PLAN 与 M20 里程碑证据。
- [x] 4.2 运行定向测试、完整离线回归、golden 20/20、lint/format/build/OpenSpec 校验，并完成验证报告。
