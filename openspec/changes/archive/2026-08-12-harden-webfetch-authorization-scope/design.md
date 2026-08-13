## Context

`operation_key(WebFetchArgs)` 过去生成 `web/<scheme>/<host>/<port>/<path>`，而 `urlsplit()` 解析的 `query` 未参与键。`HeadlessConfirmer.allows_web_url()` 同时服务初始请求和 `guarded_urlopen()` 的 redirect validator，故键必须覆盖完整有效 URL 的授权差异。

## 决策

1. WebFetch 键使用 `web/v1/<scheme>/<host>/<port>/<path>/<sha256(query)>`。摘要恒为 64 位小写十六进制，配置和审计只含摘要，不含 query 明文。
2. 摘要输入是 `urlsplit(url).query` 的原始字符串，不排序、不 URL 解码或重编码。因此 `tag=one&tag=two` 与 `tag=two&tag=one` 是不同授权范围；无 query 也使用空字符串摘要。
3. allowlist 解析只接受 v1 格式，旧的 `web/<scheme>/...` 键直接报无效配置，避免旧键意外扩权。
4. 初始请求和 redirect 不引入第二套逻辑，继续共用 `HeadlessConfirmer.allows_web_url()`；SSRF guard 在创建下一跳请求前调用它。

## 风险与边界

- SHA-256 摘要不是机密存储保证，但不会把 query 明文持久化到 allowlist 或 audit key；交互审批展示完整 URL 的既有行为不变。
- query 语义由服务端定义，故不做排序或规范化。
- 不修改动态 MCP approval 或其他操作键格式。
