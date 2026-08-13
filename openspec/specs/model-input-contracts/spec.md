# model-input-contracts Specification

## Purpose
Define fail-fast positive and finite numeric bounds, plus explicit fallback semantics, for generation parameters, model capabilities, and registry entries before provider requests execute.
## Requirements
### Requirement: Generation parameters reject invalid numeric values

`GenerationParams` MUST reject `max_output_tokens` when it is zero or negative. It MUST reject `timeout_seconds` when it is zero, negative, NaN, or infinite. Existing defaults and all positive finite values MUST remain accepted.

#### Scenario: Invalid generation limit
- **WHEN** a caller constructs `GenerationParams(max_output_tokens=0)` or with a negative value
- **THEN** model validation fails before provider request construction

#### Scenario: Invalid timeout
- **WHEN** a caller constructs `GenerationParams(timeout_seconds=0)`, a negative value, NaN, or infinity
- **THEN** model validation fails before Task execution

#### Scenario: Positive default remains compatible
- **WHEN** a caller constructs `GenerationParams()` or supplies a positive finite timeout and output limit
- **THEN** construction succeeds and existing provider defaults/translation remain unchanged

### Requirement: Registry capability limits are positive

`ModelCapability` and `ModelEntry` MUST reject zero or negative `context_window` and `max_output_tokens` values. Registry loading MUST fail with its existing structured registry error path when an entry violates these bounds.

#### Scenario: Invalid model registry entry
- **WHEN** a model entry declares a zero or negative context window or output ceiling
- **THEN** registry validation rejects the entry before it becomes selectable

#### Scenario: Valid large model entry
- **WHEN** a model entry declares positive integer capability limits within the existing configuration format
- **THEN** registry loading and capability projection remain unchanged

### Requirement: Request fallback distinguishes absence from invalidity

Provider request builders MUST use explicit `None` checks for optional output limits rather than truthiness fallback, so validation and defaulting cannot silently convert zero or other invalid values into a provider default.

#### Scenario: Explicit positive override
- **WHEN** `max_output_tokens` is a positive value
- **THEN** the provider request uses that exact value

#### Scenario: Omitted override
- **WHEN** `max_output_tokens` is `None`
- **THEN** the provider request uses the model capability ceiling as before

### Requirement: 用户模型组覆盖支持显式替换
当用户配置覆盖已有 provider group 时，显式提供的 `models` MUST 替换该组的完整模型列表，而不是与内建列表合并。省略 `models` MUST 保留内建列表；显式空列表 MUST 清空该组。

#### Scenario: 模型被重新分组
- **WHEN** 用户在旧组显式移除一个模型并在新组列出该模型
- **THEN** 最终 registry MUST 只将该模型路由到新组
- **AND THEN** 不得因隐式保留旧组成员而产生重复路由错误

#### Scenario: 只覆盖组的标量字段
- **WHEN** 用户覆盖已有组但省略 `models`
- **THEN** 最终 registry MUST 保留该组的内建模型列表

#### Scenario: 显式清空组
- **WHEN** 用户为已有组配置 `models: []`
- **THEN** 最终 registry MUST 接受空列表并移除该组的全部模型成员

### Requirement: 模型反馈不得包含下游异常原文
ForgeAgent MUST 将协议校验、响应解析和 provider transport 失败投影为稳定错误类别；字段校验 MAY 包含首个字段位置。完整异常、endpoint 返回正文、模型输入片段、secret 和宿主绝对路径 MUST NOT 进入下一轮模型反馈。诊断详情 MAY 写入 debug 日志，但 MUST 先掩码并限制长度。

#### Scenario: 字段校验失败
- **WHEN** ToolCall 参数不符合注册 schema
- **THEN** 下一轮只收到稳定的 `invalid_arguments` 类别和字段位置，不包含 Pydantic 输入值或完整 ValidationError

#### Scenario: provider 流式失败
- **WHEN** provider 在 streaming 中抛出包含 credential 或 endpoint 原文的异常
- **THEN** 模型只收到稳定 transport kind，本地 debug 日志保留有界且已掩码的诊断

