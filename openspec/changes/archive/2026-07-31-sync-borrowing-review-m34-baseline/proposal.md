## Why

M34 已将运行时 Skill 退出契约交付，但两份评审规划文档仍把 M32 写成当前基线，并保留“运行时拒绝尚待立项”的过期表述。继续引用这些文档会让下一轮规划重复已完成工作或误判当前缺口。

## What Changes

- 将两份评审文档的当前基线同步为 M34。
- 将 Prompt/Skill 借鉴项更新为“开发期治理 + M34 运行时校验”，明确 legacy 兼容和未迁移边界。
- 删除/改写运行时 Skill 自动拒绝仍待触发的过期表述，保留 Memory 迁移与 Rewrite/依赖的真实需求门槛。
- 增加离线文档契约测试，锁定 M34、发布冻结和后续候选边界。
- 不修改源码、主规格、依赖、发布 change 或 PyPI 状态。

## Capabilities

### New Capabilities

- `borrowing-review-baseline`: 评审规划文档的里程碑基线和借鉴状态一致性。

### Modified Capabilities

无。此次只同步规划文档和离线契约，不改变运行时能力规格。

## Impact

- 文件：两份 `docs/reviews/` 文档和 `tests/test_borrowing_roadmap.py`。
- 验证：专项 pytest、Ruff、diff check、OpenSpec strict。
- 发布：继续暂停 PyPI，不上传、不创建 tag、不 push，不推进 `publish-v0-1-0`。
