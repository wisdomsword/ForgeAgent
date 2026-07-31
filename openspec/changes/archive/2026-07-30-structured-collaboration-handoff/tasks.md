# 实施任务

## 1. 契约与投影

- [x] 1.1 增加严格、有界、可重建的 `HandoffPacket`、digest 和角色/phase/return-owner 枚举。
- [x] 1.2 从 CollaborationState、registry、checks 和可选 receipt store 生成 host-owned packet；为无 receipt store 或无绑定上下文明确 unavailable。
- [x] 1.3 增加 packet masking、路径/控制字符、重复重建、未决 receipt 和能力边界测试。

## 2. 角色交接与恢复

- [x] 2.1 将 Planner/Generator/Evaluator task data 统一改为包含 `handoff` 与 `handoff_digest`，保留旧字段和 loop_context 兼容。
- [x] 2.2 为 role start 发出有界 `collaboration.handoff` 审计事件；不得记录正文、命令、路径、secret 或完整 receipt id。
- [x] 2.3 增加 Duo/Triad、拒绝重试、evaluator resume、loop resume 和 Single 不变的回归测试。

## 3. 文档与验证

- [x] 3.1 更新 runtime-collaboration、threat-model 和协作使用文档，记录 handoff 的责任边界与明确不做项。
- [x] 3.2 运行专项测试、完整 pytest、Ruff、格式检查、build 和 OpenSpec strict。
- [x] 3.3 最终进行两轮自评，检查模糊、错误、过度保守、前后不一致和遗漏；发现问题立即修复并复验，保持 PyPI 发布暂停。
