## Context

M36 的综合清单已经列出三类待触发工作，但借鉴清单“下一步”仍有旧的两类表述。当前没有新的 HTTP 远程控制面，因此本次只做规划文案一致性修正。

## Goals / Non-Goals

**Goals:**

- 让两份清单都列出 Memory、Rewrite/依赖和 HTTP 远程动作审批绑定三类条件候选。
- 保留 HTTP 仅 loopback、需要真实 verifier、另立 change 的边界。

**Non-Goals:**

- 不新增 HTTP 远程入口、审批 API、运行时协议或依赖。
- 不推进或修改 PyPI 发布 change。

## Decisions

- 只改“下一步”摘要和离线契约测试，不重复改 M36 已覆盖的详细表格。
- 继续使用 `borrowing-review-baseline` 主规格的文档契约，不新增运行时能力规格。

## Risks / Trade-offs

- [风险] 摘要再次滞后于详细表。 -> 测试同时要求三类候选和 loopback-only/真实 verifier 门槛。
