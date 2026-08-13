## Why

headless WebFetch 的静态授权键只绑定 scheme、host、port 和 path，丢弃 query。因此一个只批准 `?account=public` 的键也会错误放行同路径的 `?account=admin&include_secrets=true`，包括重定向的有效 URL。

## What Changes

- WebFetch 键升级为版本化格式，并附加原始 query 的固定长度摘要。
- 保留现有 scheme/host/port/path 规范化；query 不排序、不解码重编码，重复参数和顺序保持授权语义。
- 拒绝旧的无 query 摘要 WebFetch 键；审计和配置中不保留 query 明文。
- 用初始请求与真实合成重定向回归固定逐跳校验。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `tool-approval`：WebFetch 静态授权必须精确绑定 URL 的 query 组成；每次 redirect 都使用同一授权校验。

## Impact

- 代码：`src/forgeagent/headless.py`。
- 测试：`tests/test_headless.py`、`tests/test_web_file_tools.py`、`tests/test_ssrf_guard.py`。
- 不改变 WebFetch 的 GET 限制、SSRF 网络策略或交互确认语义。
