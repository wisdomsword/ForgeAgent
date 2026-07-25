## Why

M22 真实模型人类验收暴露出协作角色完成协议不可靠：Planner、Generator、Evaluator 可能在
未调用其结构化 Submit 工具时声明完成，或在产物已经正确时因额外的 standalone
`task_status` 轮次耗尽。Generator 还会尝试用 restricted Exec 重复验证刚由 FileWrite 写入
的宿主文件，文件视图差异导致无意义重试。提示增强能降低偏离概率，但不能形成确定性门。

## What Changes

- 新增 Generator 专用零载荷 `SubmitCandidate`，成功提交是进入 Evaluator 的唯一入口。
- 三个角色的 Submit 工具保存成功即完成角色；Step 截断同一响应中位于成功 Submit 之后的
  工具调用，不再要求额外 standalone `task_status`。
- Tool registry 显式登记唯一 required completion tool；Step 提供一次缺失 Submit 的结构化
  恢复机会，但不感知协作角色、phase 或工具名称。
- 复用现有 phase、attempt 和 `last_evaluation` 表达 Candidate 生命周期，保持
  `forgeagent.collaboration.v1` schema 不变。
- Runner 继续负责冻结计划、统计边界、pass/reject、拒绝上限、恢复和稳定失败映射。
- 更新三个角色提示、回归测试和真实模型 Triad 验收。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`：增加结构化角色提交门、Candidate attempt 绑定和无歧义恢复语义。

## Impact

- 代码：`src/forgeagent/tools.py`、`src/forgeagent/step.py`、
  `src/forgeagent/collaboration.py`
- 测试：Step、协作工具、Runner、Planner、Loop collaboration 与真实模型人工验收
- 文档：`runtime-collaboration` delta spec、技术设计与实施计划
- API、依赖、公开报告和持久化 schema：不变
