## Root Cause

M22 初始归档时 Generator 仍以普通 Task completion 作为候选边界；后续 change 已把
`SubmitCandidate` 升级为唯一 Candidate 门并修改通用 Step，但只向主 spec 追加新 requirement，
没有同步改写早期 requirement、里程碑范围和最终台账数字。因此同一权威文档内同时存在新旧语义。

## Fix

1. 完整替换 `Evaluator 独立验收并决定协作完成` requirement：候选提交以成功
   `SubmitCandidate` 为唯一前置条件，缺失提交以 `invalid_role_submission` 结束，Evaluator 不启动。
2. README/ACTION_PLAN 使用分层时间口径：旧数字保留为历史阶段证据，`2151 passed, 10 skipped`、
   OpenSpec `17/17` 和两次真实 Triad 作为当前最终基线。
3. M22 里程碑补记归档后结构化提交 change、通用 Step completion signal、per-ID `flock` 和真实验收，
   删除“未修改 Step”“clean completed 提交验收”等旧措辞。
4. 静态合同直接断言新语义与最终基线，避免文档再次漂移。

## Scope

只修正规格和台账，不修改运行时行为、接口、schema、依赖或权限。
