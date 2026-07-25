## ADDED Requirements

### Requirement: 搜索消费者使用固定受限的引擎 fallback
`/search` MUST 把配置引擎视为首选而非单点依赖。当首选引擎网络失败、返回非成功状态、或成功页面解析为零条结果时，运行时 MUST 最多再尝试一次另一个内置引擎。每次请求 MUST 独立经过既有无代理、SSRF、redirect 和 scheme 校验；不得根据页面内容或用户输入构造第三方 host。若所有尝试失败，公开错误仍 MUST 使用既有稳定最小披露状态。

#### Scenario: 首选引擎不可用时 fallback
- **WHEN** 首选引擎请求因网络错误或非成功状态失败
- **THEN** 运行时尝试另一个固定内置引擎，并在备用引擎成功时返回其结果

#### Scenario: 首选页面解析失效时 fallback
- **WHEN** 首选引擎返回成功页面但解析器得到零条结果
- **THEN** 运行时尝试另一个固定内置引擎，以避免单一 HTML 结构变化导致永久空结果

#### Scenario: 每个 fallback hop 独立受网络策略约束
- **WHEN** 首选或备用引擎的任一有效目标、redirect 或解析前请求违反网络策略
- **THEN** 该请求被既有 guard 拒绝，fallback 不绕过 scheme、proxy、redirect 或 SSRF 限制

#### Scenario: 所有引擎失败
- **WHEN** 两个固定引擎均不可用或均解析不到结果
- **THEN** `/search` 返回既有 unavailable 或零结果公开语义，不披露内部 URL、异常、credential 或代理信息
