## 1. Context 配置与估算基础

- [x] 1.1 完成 Superpowers 技术设计，裁决窗口交互单元、估算公式与安全余量、配置 schema/default、continuation 规则和 normalized denominator 承载方式
- [ ] 1.2 实现集中验证的 context 配置及旧配置缺失字段兼容测试，确保 CLI/REPL 与 HTTP 服务端装配使用同一语义
- [x] 1.3 实现无外部依赖的本地近似 token 估算，并覆盖中英文、代码、JSON、emoji、多模态元数据和 message framing 边界

## 2. Sliding-window Context Policy

- [x] 2.1 实现最小 ContextPolicy 契约和唯一 SlidingWindowContextPolicy，不增加未使用的策略占位、registry 或 factory
- [x] 2.2 将 policy 从 Task 注入 Step，并在每次 complete/stream 调用前构造非破坏性的有界 request view
- [x] 2.3 覆盖阈值以下完全兼容、system/goal 保留、首次调用前不可淘汰请求超预算的 fail-fast、完整交互单元淘汰、ToolCall/feedback 配对和 provider context error 语义

## 3. 统一工具反馈限额

- [x] 3.1 用统一的可配置 limiter 替换固定 4096 字符分支逻辑，覆盖成功/失败 Exec、MCP、Survey、File、WebFetch 和其他 ToolOutcome
- [x] 3.2 为每种工具实现诚实的截断标记、原始总量、展示范围与真实 continuation，并验证不会虚构分页或持久结果
- [x] 3.3 验证 request feedback 截断不改写原始 ToolOutcome、任务终态、CLI 本地结果或 HTTP 安全投影

## 4. Cache 指标与审计

- [x] 4.1 在 Anthropic 与 OpenAI-compatible adapter 边界提供 normalized total prompt denominator，同时保持既有原始 TokenUsage 值
- [x] 4.2 在 CLI 最终 task/session usage 行增加累计 cache hit rate，并覆盖零分母 `n/a` 与 REPL 不跨 goal 继承历史
- [x] 4.3 在成功 `llm.outcome` 中增加同语义 `cache_hit_rate`，覆盖数值、JSON null、掩码、序列化失败和 audit_degraded 回归
- [ ] 4.4 验证 HTTP usage 响应 schema 不暴露 cache hit rate 或内部 denominator

## 5. Prompt-cache 顺序与跨入口回归

- [ ] 5.1 增加稳定 system 前缀与动态尾部排序审计，验证阈值以下纯追加及窗口滑动后保留消息不被改写
- [ ] 5.2 增加 CLI、REPL、HTTP Task factory 的 policy wiring 测试，并完整回跑 M16 鉴权、严格 schema、取消、安全投影、审计和 exact allowlist 契约

## 6. 长任务验收与文档

- [ ] 6.1 增加超过窗口的长对话 mock replay，验证压缩后任务仍完成且截断协议文本可观察
- [ ] 6.2 更新配置、CLI usage、审计格式、上下文限制和威胁模型文档，并明确近似估算与 sliding window 的已知权衡
- [ ] 6.3 运行聚焦测试、完整 pytest、Ruff、离线 golden、OpenSpec strict validation 和 diff check，记录 M17 验证证据
