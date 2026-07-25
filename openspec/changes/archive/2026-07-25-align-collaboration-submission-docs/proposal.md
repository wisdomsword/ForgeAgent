## Why

M22 结构化提交门归档后，主协作规格、README、ACTION_PLAN 与里程碑仍保留部分旧协议和旧验证
基线：Generator 的普通 `completed` 被描述为候选提交，里程碑还声称未修改 Step，且最新真实模型
验收与 `2151 passed, 10 skipped` 未进入权威台账。这会误导后续实现、评审和续接。

## What Changes

- 将主 `runtime-collaboration` 规格统一为：Generator 只有成功调用 `SubmitCandidate` 才提交候选；
  普通 prose 或 `task_status.completed` 不能启动 Evaluator。
- 更新 README、ACTION_PLAN 与 M22 里程碑，保留历史阶段证据并增加最新结构化提交、跨进程 CAS、
  两次真实 Triad 和最终测试基线。
- 更新静态文档合同，防止旧完成协议、旧最终计数或错误的 Step 范围声明回归。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`：消除旧 Generator completion 描述与结构化 Candidate 门之间的矛盾。

## Impact

- 规格：`openspec/specs/runtime-collaboration/spec.md`
- 文档：`README.md`、`ACTION_PLAN.md`、`milestones/milestone_022.md`
- 测试：`tests/test_collaboration_docs.py`
- 运行时代码、公开 API、依赖与持久化 schema：不变
