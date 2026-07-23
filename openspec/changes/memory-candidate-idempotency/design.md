## Context

模型在工具失败后的自纠错 round 中可能重复输出同一个 Memory 标记。当前 Task 在终态后按
round 顺序应用全部候选，因此完全相同的候选会重复写入、审计并展示。固定协议同时把真实
签名 `set_state(key, value)` 写成 `set_state(key=value)`，且没有明确 `utils` 是注入全局对象，
导致人工验收中的 ImportError 和 TypeError。

## Goals / Non-Goals

**Goals:**

- 单 Task 内同一 scope/key 的值未变化时，完全相同候选只应用一次。
- 同 key 但不同 scope、kind 或 content 的候选继续按出现顺序处理。
- 固定协议准确说明 `utils` API，并让纯记忆请求不再要求无意义的 Exec。

**Non-Goals:**

- 不跨 Task 去重，不改变相同 key 的后写覆盖语义。
- 不改变 MemoryManager、Runtime public API 或模型供应商行为。
- 不为模型生成代码增加自动修复或重试逻辑。

## Decisions

1. Task 按 `(scope, key)` 记录最近一次 `(kind, content)`；值未变化时跳过重发，值变化时
   继续调用 manager。相比全局 seen set，这保留 `ruff → black → ruff` 的明确回退语义。
2. 去重放在 Task 与 manager 的边界，而不是 CLI 展示层：这样写入和审计也保持幂等，所有
   Task 调用方获得一致结果。
3. 固定协议使用真实示例 `utils.set_state("key", value)`，明确 `utils` 已注入、不得 import；
   纯记忆请求可直接发候选并完成，无需 Exec。

## Risks / Trade-offs

- [模型故意重复完全相同候选以表达两次操作] → 同一 Task 中语义和内容完全相同，不提供
  新信息；按一次逻辑候选处理更符合幂等性。
- [提示词变化影响 golden] → 运行身份专项、Task/CLI 回归、完整 golden 和全量测试。
