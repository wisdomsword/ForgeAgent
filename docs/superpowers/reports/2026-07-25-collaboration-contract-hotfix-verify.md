# Collaboration Contract Hotfix 验证报告

- Change: `collaboration-contract-hotfix`
- 基线: `489999a3629767a6c961db72065d6b8313d5dc0c`
- 验证模式: full
- 结论: PASS；无 CRITICAL、WARNING 或未接受偏差，可以归档

## Scorecard

| 维度 | 结果 |
|---|---|
| Completeness | 4/4 tasks；2/2 modified requirements 已实现 |
| Correctness | WHAT-only 双字段、single/Duo/Triad route、角色 start/outcome、异常安全收口均有回归覆盖 |
| Coherence | 实现与 proposal/design/delta specs 一致；未新增依赖、公开 schema 或持久化 schema |
| Code review | 两轮自审与一次 `codex review --uncommitted`；审查发现的 single Loop route、Loop correlation 和本地转录泄漏风险均已修复 |
| Security | 审计不记录 goal、计划/反馈正文、prompt、工具参数、credential、绝对路径或异常文本 |

## 验证证据

```text
UV_CACHE_DIR=/tmp/forgeagent-m22-review-uv-cache rtk uv run pytest -q
2073 passed, 11 skipped in 78.05s

UV_CACHE_DIR=/tmp/forgeagent-m22-review-uv-cache rtk uv run ruff check .
All checks passed!

UV_CACHE_DIR=/tmp/forgeagent-m22-review-uv-cache rtk uv run python -m tests.golden.runner \
  --output-dir /tmp/forgeagent-m22-postarchive-golden
20/20 passed (100.0%)

UV_CACHE_DIR=/tmp/forgeagent-m22-review-uv-cache rtk uv build \
  --out-dir /tmp/forgeagent-m22-postarchive-dist
source distribution and wheel built successfully

openspec validate --all --strict
18 passed, 0 failed

rtk git diff --check
exit 0
```

上述 OpenSpec 计数包含验证时的 active change；归档并合并 delta spec 后，主规格复验为
`17 passed, 0 failed`。

## 需求映射

- Planner WHAT-only：`SubmitPlanTool` 对 `behavior` 与 `acceptance` 复用同一 HOW-only 拒绝边界；回归覆盖具体库/工具/实现步骤。
- 路由审计：CLI/REPL/HTTP 在模式解析后记录安全 route；Loop create/resume 对 single、Duo、Triad 均记录 mode、reason、requested mode、override flag 与 loop_id。
- 角色审计：Planner/Generator/Evaluator 每次尝试记录 start/outcome、model、tier、phase、attempt、duration、rounds 与 normalized usage。
- 异常收口：构建、执行、中断和资源关闭异常只记录稳定状态与零 usage，不包含异常原文。
- 关联性：协作事件携带 collaboration_id，并在 Loop 中显式携带 loop_id；HTTP 路径继续携带 task_id。

## 最终评估

所有检查通过。该 hotfix 已闭合 M22 归档后发现的契约缺口，具备归档条件。
