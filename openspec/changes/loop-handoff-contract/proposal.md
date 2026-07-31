## Why

Loop checkpoint 当前把模型提交的自由文本直接作为下一轮交接状态，导致模型可以间接改写宿主拥有的执行边界，也让旧字符串兼容、恢复提示和“不重放副作用”语义缺少统一契约。M40 需要把可提交进度收敛为有界、可验证的状态候选，并在旧 checkpoint 仍可读取的前提下明确恢复边界。

## What Changes

- 为 Loop handoff 引入宿主拥有的结构化状态，至少包含 `completed_items`、`open_questions` 和 `summary`。
- 将旧 JSON 中的字符串 `handoff` 只读迁移为结构化 `summary`；新写入使用稳定结构，保留公开 `schema` 键兼容性。
- 将 `Checkpoint` 工具限制为提交状态候选；目标、预算、权限、协作冻结状态、终态和恢复语义只能由宿主保留。
- 对提交缺失或可恢复校验失败提供有界恢复提示；恢复不执行无条件重放，尤其不重放副作用或未知收据动作。
- 增加旧 checkpoint、候选越权、迁移、恢复边界和 Loop 注入上下文的回归验收。

## Capabilities

### New Capabilities

- `loop-handoff-contract`: Loop handoff 的结构化状态、候选投影、兼容迁移和有界恢复契约。

### Modified Capabilities

- `loop-execution`: 修改 checkpoint handoff 的持久化、resume 注入和 Loop 专用 `Checkpoint` 提交边界；保留既有 Loop 终态、预算和公开报告语义。

## Impact

- 影响 `src/forgeagent/loop.py` 的 checkpoint 模型、Checkpoint 工具、resume 注入和失败恢复边界。
- 影响 `src/forgeagent/step.py` 的 required submission 恢复次数与不重放约束。
- 增加 Loop checkpoint、runner、Step 和 OpenSpec 严格校验测试；不新增依赖，不修改 CLI/HTTP 公共报告，不执行 PyPI、tag、push 或发布自动化。
