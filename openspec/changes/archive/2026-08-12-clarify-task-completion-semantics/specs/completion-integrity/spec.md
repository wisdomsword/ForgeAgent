## ADDED Requirements

### Requirement: 任务终态公开一致的完成语义
ForgeAgent MUST 把任务终态归类为 `verified_completed`、`answered_unverified` 或 `stopped`，并 MUST 仅在 `verified_completed` 时把兼容布尔 `completed` 投影为 true。

#### Scenario: prose 回答不得显示为已验证完成
- **WHEN** 模型给出非空 prose 回答但没有执行工具或程序
- **THEN** Task、CLI、HTTP 与 audit 都把该终态标为 `answered_unverified`，CLI 不得显示 `completed`，兼容布尔 `completed` 为 false

#### Scenario: 已验证完成保持兼容
- **WHEN** 任务按协议声明并达到 verified completion
- **THEN** 三态为 `verified_completed`，兼容布尔 `completed` 为 true，既有 verified-only 消费方行为不变

#### Scenario: 矛盾状态被拒绝
- **WHEN** 调用方同时提供互相矛盾的完成三态、布尔投影或终止原因
- **THEN** ForgeAgent 在状态构造时拒绝该输入，而不是序列化相互冲突的结果
