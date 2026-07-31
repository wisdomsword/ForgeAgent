## Why

两份借鉴清单对“HTTP 动作审批绑定”的状态表述不一致：详细表指出目前只是部分覆盖，综合清单却把它排除在剩余触发项之外。当前 ForgeAgent 的 HTTP 服务仅允许 loopback，因此正确做法是登记为有明确触发条件的未来候选，而不是现在修改运行时。

## What Changes

- 将 HTTP 远程动作审批绑定登记为条件借鉴候选。
- 明确触发条件：出现需要外部访问的 HTTP 动作控制面，并能提供把审批绑定到具体动作摘要和范围的真实 verifier。
- 保持当前 loopback-only HTTP 边界和身份信任行为不变。
- 增加离线文档契约断言，锁定候选的触发条件和当前未触发状态。

## 能力范围

### 新增能力

- 无。

### 修改能力

- `borrowing-review-baseline`：记录 HTTP 动作审批绑定为条件候选，不宣称运行时已交付。

## 影响

只修改评审文档、借鉴清单 OpenSpec delta 和离线契约测试；不修改源码、依赖、Memory 数据、HTTP API、PyPI 制品、tag 或 active 发布任务。
