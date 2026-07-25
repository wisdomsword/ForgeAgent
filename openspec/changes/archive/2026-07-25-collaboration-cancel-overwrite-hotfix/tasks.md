# 任务清单

- [x] 1. 修复 `_run_record` cancel 守卫：为 `collaboration_report` 增加终态豁免，并新增两个回归测试（RED→GREEN 验证）— 对应 commit `d9593e8`
- [x] 2. 文档状态同步：CLAUDE.md 移除过时"规划阶段"描述、ACTION_PLAN.md 门禁列与 mcp 后注、README.md 测试数字更正 — 对应 commit `eb2dc8d`
- [x] 3. 修复 `tests/test_collaboration_runner.py`、`tests/test_loop_runner.py` 的 ruff format 漂移 — 对应 commit `b5b8884`

> 全量回归（pytest / ruff / OpenSpec strict）在 verify 阶段执行，不作为独立 build 任务。
> 三个任务的实现先于本 change 补建（审查修复即刻落地），本清单以对应 commit 为验收锚点：
> - Task 1 证据：`pytest tests/test_http_task_service.py` 30 passed；新测试在无修复时验证过 FAILED（RED）。
> - Task 2 证据：`git show --stat eb2dc8d` 覆盖 ACTION_PLAN.md/CLAUDE.md/README.md 三个文件。
> - Task 3 证据：`ruff format --check src/ tests/` 全部通过（99 files already formatted）。
