## Decisions

1. Store 同时接收 wall clock 与 monotonic clock。生产默认分别为 `time.time` 和 `time.monotonic`；显式旧 `clock` 注入且未给 monotonic clock 时，兼容地作为测试 TTL 时钟。
2. `issued_at`/`expires_at` 由 wall clock 生成；内部 `_deadlines` 仅由 monotonic now + TTL 生成。
3. ToolCall 扫描器先匹配完整 `<!-- ... -->` comment，再仅处理 `ToolCall:` 前缀的 payload。未闭合 comment 不匹配，不影响后续 comment。
4. Pydantic/JSON/YAML 解析错误只产生稳定类别和首个字段位置；provider 错误只产生稳定 transport kind。完整异常不写入反馈对象。
5. 调试日志先经过 secret/path 投影，再截断到固定长度；普通请求和 streaming 共用同一日志出口。

## Non-Goals

- 不改变 CodeBlock/Memory marker 的成功解析协议。
- 不改变 provider 重试次数或 streaming 中途失败不重试的契约。
