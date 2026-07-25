## 根因

Store 初始化先 `lstat` 再无条件 `mkdir`，缺少“另一实例刚创建目录”的合法竞态处理。Runner 的
提交验证只检查持久状态的 revision、phase 和 counters，没有检查当前角色的 `TaskOutcome` 是否真的
包含成功 Submit，因此 stale loser 可以认领 winner 的提交并继续写共享状态。

## 修复

1. `_directory` 捕获并发创建产生的 `FileExistsError`，随后继续执行既有 `lstat`、symlink、目录类型和
   root containment 校验；其他创建错误仍转换为 `CollaborationError`。
2. 新增私有 `_successful_submission(outcome, tool_name)`，要求对应 outcome 同时满足
   `success=True` 和 `completes_task=True`。
3. Planner、Generator、Evaluator 的 `submitted` 判定同时要求本次 outcome 的归属证明和原有持久
   invariant。若本次没有成功 Submit 且共享 revision 已前进，Runner 使用 `_finish_without_save`
   返回本地 `state_failure`；共享协作由 winner 继续推进。

## 边界

- 不阻止重复 provider/tool 前置工作；现有 CAS 仍决定唯一持久提交者。
- 不增加 owner token、锁、状态字段或迁移。
- 同一 Runner 实例的 `_run_lock` 行为不变。
