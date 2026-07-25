## ADDED Requirements

### Requirement: MCP hung-call 超时具有可执行回归
MCP manager MUST 对已建立 session 上永不返回的工具调用应用共享调用 deadline，并在 deadline 到达后返回固定、脱敏的 timeout 失败。验证该行为的自动化测试 MUST 使用确定性本地 stdio fixture、在短时间内完成且不得永久 skip。超时不得使 `close()` 无界阻塞，也不得把迟到结果发布到已失效 generation。

#### Scenario: 永不返回的 MCP 工具调用超时
- **WHEN** 一个本地 MCP stdio fixture 接受工具调用但在配置的 call timeout 内永不完成
- **THEN** `call_tool` 在 deadline 后返回固定 timeout 结果，测试在有界时间内通过且不依赖公网或用户 MCP 配置

#### Scenario: hung-call 后关闭 manager
- **WHEN** manager 在一次工具调用超时后关闭
- **THEN** `close()` 在既有 shutdown deadline 内返回，迟到 holder 或调用结果不能恢复旧 generation
