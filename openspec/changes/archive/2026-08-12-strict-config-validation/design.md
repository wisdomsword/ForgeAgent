## Context

配置是启动期信任边界。此前 `yaml.safe_load(...) or {}` 的结果直接参与 `.get()` 与 merge，未知根键被丢弃；Pydantic 默认允许额外字段，MCP 普通 `bool` 也接受 `"false"`、`0` 与 `1`。错误分支把完整 `ValidationError` 拼入公共 `RegistryError`，使 API 和错误文本与 Pydantic 实现细节耦合。

## Goals / Non-Goals

**Goals：**

- 在任何 merge 前逐份验证 YAML 根结构。
- 拒绝相关模型的未知字段。
- 只严格化 MCP 的启停布尔字段。
- 以来源标识和固定文案向外报告配置错误。
- 拒绝 temperature 的 NaN 与正负无穷。

**Non-Goals：**

- 不改变模型 group 的合并/替换语义（S9 独立处理）。
- 不扩大 temperature 的取值范围策略。
- 不将所有 MCP 字段改为 strict 类型。
- 不增加新配置面或依赖。

## Decisions

1. models.yaml 只允许 `default_model`、`models`；共享 config.yaml 只允许既有的 `groups`、`context`、`restricted`、`search_engine`；mcp.yaml 只允许 `mcpServers`。解析结果必须是 mapping，`mcpServers` 也必须是 mapping。
2. 每份内建或用户 YAML 先独立解析、验证 MCP entries 或根键，再执行 overlay；因此无效 user overlay 不会被 builtin 结构掩盖，错误来源准确。
3. Pydantic 模型采用 `ConfigDict(extra="forbid")`。MCP 继续允许 `autoApprove` 作为显式 alias。
4. `enabled`、`required` 使用 `StrictBool`；其余字段维持已有 Pydantic 兼容行为，避免无关破坏。
5. 对外仅返回 `<source>: invalid configuration`，详细 `YAMLError` / `ValidationError` 作为异常链保留给本地调试，不进入 CLI 展示。
6. GenerationParams.temperature 使用已有 Pydantic `FiniteFloat`；这只排除非有限数，保留当前任何有限范围的行为。

## Risks / Trade-offs

- 过去依赖拼写错误被忽略的配置会在启动时失败；这是预期的安全修正。
- 稳定错误不含字段路径，诊断性降低；完整细节仍在异常链中，而稳定公共边界不泄露实现格式或潜在敏感值。
