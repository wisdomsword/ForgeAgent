# 结构化协作交接

## Why

现有 Duo/Triad 已耐久保存目标、冻结计划、评审结果、attempt、revision 和停止原因，但角色之间主要通过渲染后的 JSON task data 交接。目标范围、事实、假设、未决副作用、能力/审批和返回责任没有一个统一、可审计的契约；恢复时容易把“当前状态”误读成自由文本摘要。

## What Changes

- 新增有界、冻结且可重建的 `HandoffPacket`，由协作状态和宿主能力投影生成。
- 交接包包含目标/范围、已验证事实、显式假设、未决副作用、能力与审批、checkpoint、停止条件和返回责任人。
- Planner、Generator、Evaluator 的 role task data 使用同一结构化交接包；resume 从持久状态重建，不持久化模型自由摘要。
- 对交接包计算稳定 digest，并在协作审计中只记录 digest、角色、phase、attempt 和边界计数，不记录目标正文、文件内容、凭据或完整 receipt。
- 未决外部副作用只投影 manager-owned receipt label、phase 和 dispatch certainty；不自动重放、不自动解决。
- 单 Agent 默认路径、现有 Submit 门、Duo/Triad 串行编排和 `CollaborationReport` 既有字段保持兼容。

## Capabilities

### New Capabilities

- `structured-collaboration-handoff`: Duo/Triad 角色间的结构化交接协议。

### Modified Capabilities

- `runtime-collaboration`: role task data、resume 和审计增加有界 handoff 投影，不改变完成/拒绝/取消语义。

## Impact

- 运行时：`src/forgeagent/collaboration.py` 及协作测试、文档。
- 不新增 scheduler、Agent 网络、资源租约管理、数据库、endpoint、依赖或单 Agent 默认上下文。
- PyPI 发布、正式 tag、远程 push 和 `publish-v0-1-0` change 不在范围内，继续暂停。
