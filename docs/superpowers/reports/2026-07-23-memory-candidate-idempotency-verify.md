---
change: memory-candidate-idempotency
status: passed
---

# Memory Candidate Idempotency Hotfix 验证报告

## 人工验收根因

- 模型在工具自纠错的多个 round 中重复发出同一 Memory 标记，Task 原先逐次调用
  MemoryManager，导致两条相同 `memory disabled` 结果和审计事件。
- 固定协议把真实 API `utils.set_state(key, value)` 错写成
  `utils.set_state(key=value)`，且未说明 `utils` 已注入，直接解释人工日志中的 ImportError
  和 TypeError。

## 实现与契约

- Task 按 `(scope, key)` 保存最近一次 `(kind, content)`；值未变化的模型重发只处理一次。
- 同 key 的值发生变化后再改回原值仍按顺序处理，保留后写覆盖语义。
- 固定协议使用真实位置参数签名，明确 `utils` 无需 import，纯记忆请求无需 Exec。
- `runtime-memory` 和 `runtime-identity` delta spec 均已 strict 校验。

## 完整验证 Scorecard

| 维度 | 结果 |
| --- | --- |
| 完整性 | 3/3 tasks；2/2 modified requirements 已实现 |
| 正确性 | 10/10 delta scenarios 有实现或既有回归证据 |
| 一致性 | proposal、hotfix design、两份 delta、代码与测试一致 |

- 关联设计：`docs/superpowers/specs/2026-07-23-memory-runtime-design.md`。
- 关联设计：`docs/superpowers/specs/2026-07-17-compose-runtime-identity-design.md`。
- M18 的候选出现顺序仍用于所有发生变化的值；仅 scope/key 当前值未变化的重发折叠为
  同一逻辑候选，因此没有设计漂移。

## TDD 与验证证据

- RED：重复候选产生 2 个 disabled 结果；固定协议缺少正确签名。
- GREEN：核心新增用例 `3 passed`；相关 Task/Identity/Memory/Protocol/CLI `331 passed`。
- 边界 RED：初版全局 seen set 错误跳过 `ruff → black → ruff` 的最后回退。
- 边界 GREEN：最近值算法返回 `accepted → replaced → replaced`，最终为 ruff。
- 最终全量：`1381 passed, 11 skipped in 75.97s`。
- fast-forward 合并至 main 后复跑：`1381 passed, 11 skipped in 74.11s`。
- 独立 golden：`84 passed in 30.93s`。
- `ruff check .`、`openspec validate memory-candidate-idempotency --strict`、
  `git diff --check` 通过。
- `uv build` 成功生成 sdist 与 wheel。

## 两轮自评审

1. 第一轮发现 task-global seen set 会破坏 A → B → A 的明确回退语义；已改为按
   scope/key 最近值判断并增加失败测试。
2. 第二轮确认候选原文仍不进入结果或审计，HTTP schema 未改变，MemoryManager 与 Runtime
   public API 未改变，没有新增依赖、配置面或额外 LLM round。

最终结论：无 CRITICAL、WARNING 或 SUGGESTION，满足归档条件。
