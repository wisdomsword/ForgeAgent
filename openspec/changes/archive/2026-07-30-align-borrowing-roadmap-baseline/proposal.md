## Why

当前工作区已经包含 M29-M32 以及已归档的 `external-action-receipts` change，但规划基线仍把
收据候选描述为待办，归档收据规格也保留 `Purpose: TBD`。这种漂移会让下一会话重复已完成
工作，或把候选清单误读成执行顺序。

## What Changes

- 在权威 `ACTION_PLAN.md` 和里程碑台账中登记已归档的外部动作收据能力及其验证证据。
- 根据收据 change 与 M29-M32 的真实证据，将五项借鉴候选标记为已完成；后续运行时治理工作
  保持明确延期。
- 把归档收据规格的占位 Purpose 改成已实现的契约边界，不改变运行时行为或公开 API。
- 更新最新里程碑续接说明，增加离线文档检查，验证候选映射和 PyPI 发布冻结仍有效。

## Capabilities

### New Capabilities

无。本 change 只记录并验证当前规划基线，不引入运行时能力。

### Modified Capabilities

- `agent-governance-gates`：要求每个标记为完成的借鉴候选关联归档 change、里程碑或验证报告，
  并为延期/条件触发候选记录触发条件或独立 change。

## Impact

- 文档与规划：`ACTION_PLAN.md`、借鉴清单、`milestones/milestone_033.md`、`milestones/latest` 和归档收据规格。
- 测试：一个离线文档契约测试；不访问网络、不调用模型、不上传包、不创建 tag、不 push。
- 运行时代码、依赖、持久化 schema 和公开 API：保持不变。
