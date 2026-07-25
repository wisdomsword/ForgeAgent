# 提案：修复 HTTP 协作任务终态被晚到 cancel 覆盖

## 问题描述

`TaskService._run_record` 的 cancel 守卫（`src/forgeagent/http_task_service.py`）只对
Loop 模式做了终态保护（`loop_report.status == "active"` 才允许 cancel 覆盖）。Duo/Triad
协作任务的 `loop_report` 恒为 `None`，导致守卫条件 `loop_report is None` 恒真：只要
`cancel_event` 已置位（服务 shutdown 会对所有未终结任务批量置位，或运行期间客户端调用
cancel），即使 `task.run()` 已正常返回终态 `CollaborationReport`（如 `completed`），
记录仍会被改写为 `cancelled`，丢弃已完成的协作报告。

这违反既有规格 `openspec/specs/http-task-service/spec.md` 的
"Cancellation has bounded terminal semantics"：取消与完成的竞态必须有确定性优先级。

## 根因分析

M22 引入协作模式时，`_run_record` 终局锁块的 cancel 守卫沿用了 M21 Loop 的条件
`loop_report is None or loop_report.status == "active"`，未为 `collaboration_report`
增加对等的终态豁免分支。触发时序：

1. 协作任务 `task.run()` 返回终态 `CollaborationReport`；
2. 在 worker 进入终局 `with self._lock:` 块之前（如恰逢 `close()` 资源清理耗时），
   服务 shutdown 或晚到的 cancel 调用置位 `cancel_event`；
3. 守卫命中，任务被记录为 `cancelled`，覆盖已完成的协作报告。

## 修复目标

- 协作任务的终态 `CollaborationReport`（非 `active`）不被晚到的 cancel 信号覆盖，
  与 Loop 模式语义对齐；
- 真正以 `cancelled` 终止的协作报告仍如实记录为 `cancelled`；
- 补充回归测试覆盖上述两条路径（修复前测试必须失败，RED→GREEN）。

## 附带整改（同批提交，非本缺陷根因）

- 文档状态同步：`CLAUDE.md` 移除过时的"规划阶段/尚无代码"描述；`ACTION_PLAN.md`
  M6-M10/M17 门禁列补完成日期、"首版不引入 mcp"加 M7 裁决后注；`README.md` 区分
  归档前 `2069` 与最终 `2073` 测试数字。
- `ruff format` 漂移修复：`tests/test_collaboration_runner.py`、`tests/test_loop_runner.py`。

## 范围与说明

改动已完成并以 3 个本地 commit 存在于 main（`b5b8884` 格式修复、`d9593e8`
bugfix+回归测试、`eb2dc8d` 文档同步），全量回归 `2075 passed, 11 skipped`。本 change
为补建流程记录，不新增 capability、public API 或 schema。附 `http-task-service` 的
delta spec：把"取消与完成竞态的确定性优先级"从原则细化为两个可执行场景（晚到 cancel
不覆盖协作终态报告；协作自身 cooperative cancelled 如实记录），使规格与修复后的实现
和回归测试一一对应。
