## Context

`TaskStatus.completed` 已被 collaboration、Loop、evaluation 和 golden 当成经过执行验证的严格布尔值；`reason=answered_in_prose` 则是 soft success。最小兼容方案必须保留布尔读取，同时增加不会混淆两者的权威三态。

## Decisions

1. `completion_state` 是权威三态；`completed` 是只在 `verified_completed` 时为真的兼容投影。
2. 旧调用 `TaskStatus(completed=..., reason=...)` 继续接受，但在校验前转成三态；如果显式三态与旧布尔或 reason 矛盾则拒绝。
3. CLI 对 `answered_unverified` 显示 `answered (unverified)`，不得包含 `completed`。
4. HTTP 和 `task.outcome` audit 增加 `completion_state`；现有 `status/reason` 与 `completed` 字段保留兼容。
5. Loop/evaluation/golden 不改评分含义，继续读取 verified-only `completed`。

## Risks / Trade-offs

- [新增字段破坏严格消费者] -> 只在可扩展的 HTTP/audit 投影追加字段，保留旧字段。
- [旧测试构造矛盾状态] -> 修正测试 fixture，使其与生产三态一致，不为矛盾对象保留兼容。
- [prose 被误算完成] -> `completed` 只由 `verified_completed` 计算。
