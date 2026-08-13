## 1. TTL

- [x] 1.1 写 RED：wall clock 前跳和后跳不改变 TTL，monotonic 到期才撤销权限。
- [x] 1.2 以独立 monotonic deadline 实现到期，同时保留 wall-clock 公开时间戳和旧测试注入兼容。

## 2. ToolCall 边界

- [x] 2.1 使用已复现输入写 RED：未闭合 ToolCall 前标记不得吞掉后续有效调用。
- [x] 2.2 先按完整 HTML comment 边界扫描，再逐个解析 ToolCall JSON。

## 3. 稳定错误反馈

- [x] 3.1 写 RED：validation、JSON、provider 与 streaming 异常原文不得进入模型反馈。
- [x] 3.2 返回稳定类别和字段位置，详细异常进入有界、掩码 debug 日志。

## 4. 验证

- [x] 4.1 运行 HTTP approval、protocol、Step 和 provider 聚焦回归。
- [x] 4.2 在最终全量验证中确认所有公开投影兼容。
