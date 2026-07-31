## Why

M36 已把 HTTP 远程动作审批绑定登记为第三类条件候选，但借鉴清单的“下一步”仍只列出 Memory 迁移和 Rewrite/依赖，造成同一规划在摘要与详细流程之间不一致。现在修正该文案可以避免后续把已确认的条件门槛遗漏掉。

## What Changes

- 在借鉴清单“下一步”中补充 HTTP 远程动作审批绑定条件候选。
- 保留当前 loopback-only 边界、真实 verifier 门槛和独立 change 要求。
- 增加离线断言，防止三类待触发工作再次退化为两类。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `borrowing-review-baseline`：要求摘要与详细条件候选列表保持一致。

## Impact

仅修改借鉴清单、OpenSpec delta 和文档契约测试；不修改源码、依赖、Memory、HTTP API 或发布 change。
