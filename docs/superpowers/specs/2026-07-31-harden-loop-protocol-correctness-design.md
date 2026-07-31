---
comet_change: harden-loop-protocol-correctness
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-31-harden-loop-protocol-correctness
status: final
---

# Hardening Loop Protocol Correctness

## 技术方案

### 模型兼容

在 `loop.py` 中移除 `warnings.catch_warnings()` 包围的模型定义。`LoopCheckpoint` 和 `LoopReport` 使用 `schema_` 内部字段、`Field(..., alias="schema")`、`populate_by_name=True` 和 `serialize_by_alias=True`。现有 `model_dump()` 调用如需内部字段，明确使用 `by_alias=True` 作为持久化边界；读取旧 JSON 继续接受 `schema`。

### 双通道工具调用

`protocol.parse()` 先解析两个通道，再执行一个稳定合并函数。合并键为显式非空 ID；未提供 ID 的文本调用继续生成 UUID，不与其他调用猜测匹配。等价调用以首次出现顺序保留；同 ID 的工具名或参数模型 dump 不相同，则追加 `ParseErrorType.INVALID_FORMAT`，并把该 ID 从最终 `tool_calls` 中移除。这样 `Step._handle_reply()` 无需新增第二套去重逻辑。

### 共享文本安全

新增小型 `text_safety.py`，只负责 Unicode 控制字符检查、长度检查和可选 strip。三个调用方保留现有字段名、长度和 `allow_empty` 选择；共享函数不处理审计路径或 secret masking，避免混合职责。

### 反馈、所有权和日志

`tools.py` 中模型可见 continuation 常量改为 English-first 的等义短句。删除 `step.py` 的 `_apply_edit` 导入和 `__all__` 再导出，测试直接从 `tools` 导入。`collaboration.py` 的 capability/receipt fallback 使用模块 logger，记录固定事件名与异常类名；不记录异常消息、参数、路径或 secret。

## 数据流与错误处理

```text
AssistantMessage
  -> protocol.parse(text + native)
  -> validate + stable identity merge
       ├─ equivalent duplicate: keep first
       └─ conflicting id: bounded parse error, remove id
  -> Step dispatch only safe calls
```

冲突继续走现有 parse-error 反馈环；不会执行任何冲突调用，也不会自动重放。checkpoint/report 仍使用现有原子保存和严格 schema 校验。

## 测试与验收

先用 TDD 增加红测，再实现：旧 schema 键加载/序列化、双通道等价和冲突、空 prose 两轮行为、共享 helper 等价性、continuation 文案、`_apply_edit` 导入边界、projection 固定类型日志及敏感信息不泄漏。完成后运行 focused pytest、全量 pytest、ruff check、ruff format check、OpenSpec strict；环境边界失败必须原样记录。

## 风险与不做事项

不修改 M27 迁移规则，不引入新依赖，不处理 Loop handoff 结构化和 Collaboration stop-reason 映射，不触发 PyPI、tag、push 或发布自动化。

