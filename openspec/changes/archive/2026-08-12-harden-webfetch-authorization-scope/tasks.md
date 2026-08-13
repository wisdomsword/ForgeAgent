## 1. 授权键

- [x] 1.1 写 RED 回归：同 path 不同 query 不共享授权，重复参数与顺序生成不同键，旧无版本键被拒绝。
- [x] 1.2 引入 v1 WebFetch 键和原始 query 的固定长度 SHA-256 摘要，不持久化 query 明文。

## 2. Redirect 与验证

- [x] 2.1 覆盖初始 URL 和合成 redirect；同路径不同 query 的 redirect 在第二跳请求前被拒绝。
- [x] 2.2 运行 headless/WebFetch/SSRF 聚焦测试、Ruff 和 OpenSpec strict。
