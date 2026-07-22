## ADDED Requirements

### Requirement: LLM outcome 记录 normalized cache hit rate
每个成功的 `llm.outcome` 审计事件 MUST 在保留既有原始 usage 计数的同时记录使用统一 total prompt denominator 计算的 `cache_hit_rate`。该指标 MUST 与 CLI 的计算语义一致，不得包含 prompt、工具参数、文件内容或其他新增敏感数据。

#### Scenario: 有可用分母的成功调用
- **WHEN** 一个成功 LLM 调用返回 cached tokens 和非零 normalized total prompt tokens
- **THEN** `llm.outcome.parameters.usage` 保留原始计数，且同级 `cache_hit_rate` 写入 0 到 1 范围内的数值

#### Scenario: 零分母或 provider 未报告 usage
- **WHEN** normalized total prompt token 分母为零或不可获得
- **THEN** `llm.outcome.parameters.cache_hit_rate` 写入 JSON `null`，审计序列化继续成功

#### Scenario: Provider 原始口径不同
- **WHEN** Anthropic 与 OpenAI-compatible 对等调用分别产生 usage
- **THEN** 两类事件使用各自 adapter 提供的 normalized denominator，而不是在审计层按模型名称猜测口径

#### Scenario: 审计写入降级
- **WHEN** 包含 cache hit rate 的审计事件写入失败
- **THEN** 任务执行继续遵循既有 fail-open 和 `audit_degraded` 语义，不因新增指标改变任务结果
