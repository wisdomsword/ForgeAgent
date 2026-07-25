# 修复方案：协作终态 cancel 守卫对齐 Loop 语义

## 方案

在 `TaskService._run_record` 终局锁块的 cancel 守卫中，为 `collaboration_report`
增加与 `loop_report` 对等的终态豁免条件：

```python
if (
    record.cancel_event.is_set()
    and (loop_report is None or loop_report.status == "active")
    and (collaboration_report is None or collaboration_report.status == "active")
):
```

三类结果的语义统一为：

| 结果类型 | cancel_event 置位时的行为 |
|---------|--------------------------|
| ordinary `TaskOutcome` | 保持原语义：记录为 `cancelled`（cooperative cancel 已有测试锚定） |
| `LoopReport` 终态 | 不覆盖（原有守卫，行为不变） |
| `CollaborationReport` 终态 | **不覆盖（本修复新增）**；`status == "active"` 时仍可标记 cancelled |

不改动 `cancel()`、`shutdown()`、`_set_cancelled_locked` 或协作 runner 本身；
`CollaborationRunner` 对 cancel 的 cooperative 响应（返回 `cancelled` 终态报告）不受影响，
该路径由新增的第二个回归测试锚定。

## 测试

`tests/test_http_task_service.py` 新增两个测试，镜像既有 Loop 测试对：

1. `test_cancel_during_collaboration_close_preserves_completed_report` —— runner 在
   `close()` 中阻塞时收到 cancel，最终视图仍为 `completed`（修复前该测试失败，已验证 RED）。
2. `test_cancelled_collaboration_report_remains_cancelled` —— runner 自身以
   `cancelled` 终态返回时，记录如实为 `cancelled`。

## 附带整改

文档同步（CLAUDE.md/ACTION_PLAN.md/README.md）与 ruff format 修复不涉及方案取舍，
按审查发现直接修正，见 proposal「附带整改」。
