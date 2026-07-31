## Why

Loop checkpoint/report、协议解析、工具反馈和协作审计路径仍有若干正确性接缝：schema 别名实现不一致；文本通道与原生通道的同一工具调用可能被重复分发；安全文本和反馈约定存在重复实现。这些问题会造成重复副作用、不稳定的 checkpoint JSON 或难以诊断的审计记录，因此需要在后续协作契约变更前先收紧。

## What Changes

- 使用 Pydantic 支持的 `schema_` 别名字段实现 `LoopCheckpoint` 与 `LoopReport`，保持磁盘上的 `"schema"` 键及旧数据加载能力。
- 在分发前按稳定调用 ID 合并文本协议和原生协议的工具调用；重复 ID 冲突时拒绝执行。
- 增加空正文和空白正文的 prose 完成回归测试，保持严格完成语义。
- 提取一个共享的内部 `_safe_text` 实现，并保留调用方原有的空值策略。
- 将工具 continuation 反馈改为 English-first，同时继续限制长度。
- 移除 `step` 对私有 `_apply_edit` 的再导出，测试从其定义模块导入。
- capability/receipt projection 失败时记录固定类型、有限长度的诊断，不输出原始异常或敏感载荷。
- 保持 M27 对旧 Duo/Triad collaboration source 的迁移语义，不扩大迁移推断。

## Capabilities

### New Capabilities

- `tool-call-identity`：定义跨协议通道的工具调用去重和冲突处理。

### Modified Capabilities

- `loop-execution`：补充 checkpoint/report 的 schema 别名兼容要求。
- `completion-integrity`：明确空 prose 正文不能完成任务。

## Impact

影响 `src/forgeagent/loop.py`、`protocol.py`、`step.py`、`tools.py`、`collaboration.py`、`external_actions.py` 及对应单元测试和 delta spec。不新增依赖，不改变公开发布、包上传、tag、push 或发布自动化。
