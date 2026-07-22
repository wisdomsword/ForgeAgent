## Why

ForgeAgent 的 `Step` 目前持续追加完整对话，工具反馈又只对部分路径使用无实测依据的 4096 字符尾截断；长任务因此可能耗尽模型上下文，并让模型把不完整结果误认为完整结果。M17 需要在 M21 长任务循环之前补齐统一、有界、可观测的上下文工程能力，同时保持 M16 的 HTTP 安全契约。

## What Changes

- 新增最小可插拔的 context policy 接口，并提供唯一的 sliding-window 实现；`Task` 注入配置，`Step` 在每次模型调用前应用策略。
- 使用本地、确定性、模型无关的近似 token 估算与安全余量限制历史窗口；允许保守地提前压缩，不增加 tokenizer 依赖或厂商调用。
- 统一所有工具反馈的可配置近似 token 限额；截断内容必须明确标注未完整、原始总量和可执行的继续读取方法。
- 审计 system prompt、工具定义和规则的稳定前缀顺序，并保证窗口处理不改写保留消息或破坏完整交互单元。
- 基于 provider-normalized total prompt denominator 计算 cache hit rate；CLI 在现有 task/session usage 行展示，`llm.outcome` 审计事件记录相同指标。
- 保持原始 `TokenUsage` 计数字段、HTTP usage 响应 schema、REPL 不跨 goal 保留历史的语义，以及 M16 的鉴权、安全结果投影、取消、审计降级和精确 headless allowlist 契约。
- 旧配置缺少 M17 字段时继续有效，并启用内置的有界安全默认值；阈值以下的普通任务保持现有消息行为。

## Capabilities

### New Capabilities

- `runtime-context-management`: 定义运行时 sliding-window 压缩、统一工具反馈截断、稳定 prompt-cache 前缀和跨 CLI/REPL/HTTP 的 cache hit rate 可观测性。

### Modified Capabilities

- `audit-logging`: `llm.outcome` 在保留原始 usage 计数的同时记录 normalized cache hit rate，并为零分母使用安全的空值语义。

## Impact

- 主要影响 `Task`/`Step` 消息循环、模型 usage 归一化、CLI usage 状态行、HTTP 服务端 `Task` 装配和核心审计事件。
- 新增 context 配置加载与策略模块，并更新相关文档、mock replay、golden、CLI、审计和 M16 HTTP 回归测试。
- 不新增运行时依赖，不调用厂商 tokenizer，不改变 HTTP endpoint 或响应 schema，不引入 importance/summary/hybrid、Memory、checkpoint 或 token stop policy。
