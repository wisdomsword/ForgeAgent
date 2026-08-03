## Context

当前 provider client 在每次 `complete()` 或 `stream()` 调用中创建 SDK client；入口层对 `Task` 与 `ModelClient` 的关闭责任也不完全一致。模型参数的 Pydantic 模型允许零值、负值和非有限值继续传播到请求构造层。仓库声明支持 Python 3.11 及以上，但生命周期 verifier 使用带解释器实现差异的 `ast.dump()` 固定摘要，导致同一源码在 3.11、3.12 和 3.14 得到不同结果。

本变更必须保持现有 provider 请求形状、CLI 输出、HTTP 行为、注入 transport 的测试替身和八个运行时依赖不变；不新增依赖，不做 Rust 或大模块重写。

## Goals / Non-Goals

**Goals:**

- 为 client、SDK transport、Task 和创建它们的入口建立可执行且可测试的所有权边界。
- 在一个 provider client 实例内复用 SDK client，普通请求与流式请求共享同一连接池，并提供幂等关闭。
- 确保 CLI、evaluate、smoke、HTTP 和已有协作路径在成功、失败、提前返回和异常时释放其拥有的资源。
- 在模型边界拒绝零、负数、非有限超时和非法能力上限。
- 使用跨 Python 3.11+ 稳定的 verifier 摘要输入，保留对受保护测试源码变化的检测能力。

**Non-Goals:**

- 不由 `Task` 关闭外部注入的 client，不改变调用方可复用 client 的语义。
- 不改变供应商 API 参数翻译、重试策略、错误公开文本或 HTTP schema。
- 不增加温度范围、上下文与输出上限的厂商特定关系，除非已有契约明确要求。
- 不添加运行时依赖，不拆分 Memory、MCP、Collaboration 或 CLI 大文件，不进行 Rust/FFI 试验。

## Decisions

### 1. Client ownership is explicit and local

`ModelClient` 提供幂等 `close()` 的统一生命周期面；基础实现默认为无操作，注入 transport 仍由外部拥有。Anthropic/OpenAI client 实例拥有各自创建的 SDK client，并在普通与流式 transport 中复用它。创建 client 的 CLI/HTTP/evaluation 入口负责在 `finally` 中关闭自己创建的 client；`Task.close()` 继续只关闭 backend 及 Task 自有资源。

替代方案：让 `Task.close()` 总是关闭 client。放弃该方案，因为 HTTP、REPL、协作和测试中存在共享或外部注入 client，隐式关闭会破坏复用和调用方所有权。

### 2. Provider SDK clients are lazy, shared, and idempotently closed

provider client 首次真正发送请求时才创建一个 SDK client；complete 与 stream 共用该实例。SDK 创建失败保持现有错误分类。`close()` 在已创建时调用 SDK 的关闭方法，重复调用不重建、不重复关闭；关闭后的再次请求按现有 client 错误语义失败。

替代方案：每次请求创建后立即关闭。放弃该方案，因为它无法复用连接池，且流式迭代的生命周期不能由请求函数安全包围。

### 3. Validate numeric contracts at the Pydantic boundary

`GenerationParams.timeout_seconds`、可选 `max_output_tokens`、`ModelCapability` 和 `ModelEntry` 的窗口/输出上限使用正数约束；浮点超时拒绝 NaN 和无穷。请求构造使用显式 `is not None` 判断，避免把合法边界判断与默认回退混在 `or` 表达式中。

替代方案：只在 provider 请求前检查。放弃该方案，因为 registry、context policy 和非 provider 调用会继续接受同一非法对象，错误发现太晚且语义不一致。

### 4. Verifier digest hashes canonical source slices

生命周期 verifier 仍通过 AST 定位顶层目标函数和赋值，但摘要 payload 改为这些节点在原文件中的规范化源码片段：统一换行并以 UTF-8 编码。这样保留源码变化检测，同时不把 Python AST 新增的空字段或 dump 格式绑定到解释器版本。

替代方案：继续使用 `ast.dump()` 并针对每个 Python 版本更新常量。放弃该方案，因为它会把兼容矩阵变成版本分支，且不能证明源码没有变化。

## Risks / Trade-offs

- [风险] provider SDK 的关闭方法在异常路径中再次抛错 → [缓解] close 采用幂等状态保护，并沿用固定的关闭错误投影；请求结果不被二次异常覆盖。
- [风险] 流式响应仍在迭代时提前关闭 SDK client → [缓解] client 只由拥有它的外层生命周期关闭；provider client 的 `stream()` 在迭代完成或调用方关闭时保持现有边界。
- [风险] 更早拒绝非法数值可能暴露此前被隐式接受的调用 → [缓解] 仅拒绝明确无效值，增加单测并保持所有正值和默认值行为不变。
- [风险] 源码片段摘要对格式调整敏感 → [缓解] 这是治理 verifier 的有意取舍：格式或正文变化都要求重新确认摘要，且摘要跨 Python 稳定。
- [风险] 入口清理改动触及多个控制流 → [缓解] 先补生命周期回归测试，再按入口小步实施；任一行为或输出回归即回滚该入口。

## Migration Plan

1. 先增加 client 复用/关闭、入口清理、参数拒绝和跨 Python digest 的失败测试。
2. 实现 provider client 生命周期与 `ModelClient.close()`，再接入 `run_once`、smoke、evaluate、HTTP 的拥有者清理。
3. 更新模型边界校验和请求构造的显式回退逻辑。
4. 替换 verifier digest，运行 Python 3.11、3.12、3.14 的 focused lifecycle 测试。
5. 运行全量 pytest、Ruff、format、构建和 OpenSpec strict；任一公开行为变化则只回滚本 change 的改动。

## Open Questions

- SDK close 失败是否只进入固定日志，还是需要加入现有公开错误投影？本 change 采用不改变公开错误投影的方案。
- 是否需要在后续 change 为 `ModelClient` 增加上下文管理器语法？当前不增加，以免扩大 public API。
