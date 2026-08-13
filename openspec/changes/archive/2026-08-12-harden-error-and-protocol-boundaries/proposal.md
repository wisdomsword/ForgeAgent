## Why

HTTP action approval TTL 以可调整的 wall clock 执行，时间跳变可错误延长或提前撤销权限。文本 ToolCall 解析正则也会让一个不完整 marker 跨越注释边界吞掉后续有效调用。解析与 provider 异常原文还会进入模型反馈，依赖后续掩码持续正确。

## What Changes

- action approval 用 monotonic deadline 判定 TTL，wall clock 只生成公开时间戳。
- ToolCall 先按完整 HTML comment 边界分段，再逐个 JSON 解析。
- 解析和 provider 失败只向模型返回稳定类别与字段位置；详细异常仅进入有界、先掩码的 debug 日志。

## Capabilities

### Modified Capabilities

- `tool-approval`：短期 HTTP MCP 权限按单调时间到期。
- `completion-integrity`：一条畸形文本 ToolCall 不得吞掉后续有效 ToolCall。
- `model-input-contracts`：下游异常不得以原文进入模型反馈。

## Impact

- `src/forgeagent/http_action_approvals.py`、`src/forgeagent/protocol.py`、provider transport/client 和对应测试。
- 不新增依赖，不改变审批公开 ISO 字段格式或 native tool-call 协议。
