---
change: define-duo-acceptance-contract
date: 2026-07-31
status: verified
release_actions: paused
---

# Verification Report

## Scope

本 change 将 Duo 默认计划从循环论证式伪验收改为产物、验证和文本三类确定性可观察模板，同时保持单项 `goal` ID、旧 snapshot 和 Evaluator 提交兼容。未执行 PyPI、tag、push 或发布自动化。

## Evidence

- RED：新增 golden tests 在旧实现上 `4 failed`；旧 snapshot 兼容测试在首次实现后继续失败，证明兼容缺口真实存在。
- Focused：`116 passed`，覆盖 Duo golden、store、runner 和 tools。
- Collaboration/HTTP：`390 passed`。
- Full pytest：`2526 passed, 10 skipped`。
- Ruff check：通过；Ruff format check：`122 files already formatted`。
- OpenSpec strict：`31 passed, 0 failed`。
- `uv build`：成功生成 wheel 与 sdist，但未上传。

## Two-Pass Review

第一轮确认采用单项兼容方案，不引入动态拆项或 LLM 拆解器。第二轮发现并修复两个问题：旧 snapshot 会因新模板重算而被拒绝；`casefold()` 会让非字符串 goal 以 raw `AttributeError` 越过 CollaborationError 边界。修复后增加旧模板白名单和 invalid-goal 回归，均已验证。

## Residual Risk

关键词分类是有意的有限启发式；复杂、多条件验收应使用 Triad Planner。回退文本模板仍提供可观察证据，不会退回“原始目标已满足”。
