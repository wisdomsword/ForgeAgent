# M28 Task 4 实施报告

## 状态

DONE_WITH_CONCERNS

M28 RC 证据、公开基线、验证报告和 milestone 已生成。Task 1-3 的 task-level review 已完成；
最终整分支 review、两轮一致性复审和 OpenSpec archive 留给 controller gate。完整 pytest 的初始
失败已由 tests-only 可移植性合同修正关闭；Docker/Linux 证据未执行，未写成 pass。

## 新鲜证据

- focused RC：`42 passed in 51.34s`
- Ruff check：`All checks passed!`
- Ruff format：`119 files already formatted`
- full pytest：`2 failed, 2401 passed, 10 skipped in 169.62s`
- MCP timing 修正后 focused：`2 passed in 0.23s`；MCP suite：`216 passed in 9.28s`
- 修正后 full pytest：`2403 passed, 10 skipped in 167.99s`
- Golden：exit 0，`20/20 passed (100.0%)`
- OpenSpec strict：`22 passed, 0 failed`
- build：唯一 `forgeagent-0.1.0-py3-none-any.whl` 与 sdist 成功
- RC harness：exit 0；Python 3.11.15，wheel SHA-256
  `d497df6a507adc7654c80b9042e4f96c838277bbabdeb031e1ca9c7f72bd4bdf`，六项全 passed
- docs/continuous/collaboration 合同复跑：`21 passed in 0.09s`
- final strict 复跑：`22 passed, 0 failed`

## Full pytest 根因调查

失败测试：

- `test_capture_close_returns_before_duplicated_writer_reaches_eof`
- `test_close_wall_clock_is_bounded_by_shutdown_and_join_budgets`

隔离复跑两次均为 2 failed。前者约 0.25004 秒，后者约 0.14771-0.18022 秒；本机
`sleep(0.01)` 实测 0.0238-0.0901 秒。M28 merge-base 到 HEAD 对 MCP source/test diff 为空。
结论：旧绝对墙钟 slack 在当前宿主调度下稳定不成立；没有在 Task 4 越界修改 MCP，也没有把失败
冒充为环境 pass。

提交 `83ba892` 仅修改 `tests/test_mcp_manager.py`，用确定性 probe 保留相同的 timeout/budget 行为
合同；生产 MCP 代码不变。修正后 focused 2、MCP 216 和全量 2403 均通过，首次失败历史仍保留。

## Docker 阻塞

Docker client 29.2.1 存在，daemon preflight 返回：

```text
Cannot connect to the Docker daemon at unix:///Users/admin/.docker/run/docker.sock.
```

按 brief 未启动 Docker Desktop。因此十项 container integration 和 Linux-container RC smoke
未执行；M28 required GitLab job 保持 configured/pending。

## 交付文件

- `docs/superpowers/reports/2026-07-29-m28-v0-1-release-candidate-verify.md`
- `milestones/milestone_028.md`
- `milestones/latest`
- `ACTION_PLAN.md`
- `README.md`
- `docs/platform-support.md`
- `docs/releases/0.1.0-rc.md`
- `openspec/changes/m28-v0-1-release-candidate/tasks.md`

OpenSpec 5.1 已勾选，因为全部本机可执行命令均已运行并如实记录结果。5.2 和 5.3 保持未勾选，
分别等待 controller 最终审查/两轮复审和实际 change archive。

提交：`37365bd`（`chore: close M28 release candidate milestone`），精确包含上述八个允许的
证据/台账文件；本报告与 Comet progress 未纳入提交。

## 文档合同调试

首跑为 `2 failed, 19 passed`，根因是 README 移除了既有静态合同要求的结构化 baseline 行；补回
实际完成计数并紧邻标记 `2 failed` 后，第二轮还暴露平台矩阵相同结构合同。最小修复后 fresh
结果为 `21 passed`，没有弱化测试或隐藏 full-suite failure。

## 风险信号

- 跨模块：YES；本任务只更新证据文档和 lifecycle checklist，未改产品代码。
- 安全/API/并发：NO 新增；既有 harness 风险由 Task 1-3 review 覆盖。
- 外部环境：YES；Docker daemon 不可用，Linux job 无当前执行证据。
- 完整门禁：CLOSED；tests-only 可移植性合同修正后 full pytest `2403 passed, 10 skipped`。
- 大 diff：YES；验证报告和 milestone 需要完整场景映射，但没有新增抽象或依赖。

## Task Review Fix

Reviewer 指出的 lifecycle gate 问题已按限定范围修正：M28 改回进行中（RC 工程冻结，非正式发布），
`milestones/latest` 恢复指向 `milestone_027.md`，ACTION_PLAN 不再宣称 M28 完成；正式发布的 full
pytest 条件收紧为全绿，或失败经已批准 change 明确裁决并关闭后重跑验证。milestone/verify report
补入 Task 1-4 关键提交 provenance，Task 4 plan Steps 1-4 按实际已执行状态勾选；OpenSpec 5.2/5.3
保持 pending。本节仅记录 review fix，继续保持本报告不纳入提交。

## MCP 修正后证据刷新

提交 `521bb49`（`docs: refresh M28 verification baseline`）保留首次 full-suite 失败与复现历史，新增
`83ba892` tests-only 修正 provenance 和新鲜 `2403 passed, 10 skipped` 基线。milestone 的完整
pytest 项已关闭；M28 仍为进行中，current Linux required job、最终 review/archive 和另行授权的
tag/上传仍开放。文档/continuous/collaboration 合同 `21 passed in 0.09s`，OpenSpec strict
`22 passed, 0 failed`，`git diff --check` 通过。

## Task Review Round 2

修正后复审发现一项 Important provenance 问题：公开 SHA 对应的 wheel 构建早于 `521bb49`，但
wheel METADATA 会嵌入 README，因而该 artifact 仍携带旧 M27 基线，不能作为当前候选。修复策略是
从当前 README 重建唯一 wheel/sdist、检查嵌入 metadata、用 Python 3.11 重跑六项 harness 并刷新
公开 SHA。复审同时指出 Task 4 plan Step 3 要求 `milestones/latest` 指向 M28，在最终 lifecycle
收口前不得提前勾选；现已恢复为 pending。
