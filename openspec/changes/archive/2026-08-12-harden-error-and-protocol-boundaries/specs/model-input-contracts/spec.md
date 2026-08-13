## ADDED Requirements

### Requirement: 模型反馈不得包含下游异常原文
ForgeAgent MUST 将协议校验、响应解析和 provider transport 失败投影为稳定错误类别；字段校验 MAY 包含首个字段位置。完整异常、endpoint 返回正文、模型输入片段、secret 和宿主绝对路径 MUST NOT 进入下一轮模型反馈。诊断详情 MAY 写入 debug 日志，但 MUST 先掩码并限制长度。

#### Scenario: 字段校验失败
- **WHEN** ToolCall 参数不符合注册 schema
- **THEN** 下一轮只收到稳定的 `invalid_arguments` 类别和字段位置，不包含 Pydantic 输入值或完整 ValidationError

#### Scenario: provider 流式失败
- **WHEN** provider 在 streaming 中抛出包含 credential 或 endpoint 原文的异常
- **THEN** 模型只收到稳定 transport kind，本地 debug 日志保留有界且已掩码的诊断
