# 借鉴清单 M34 基线同步验证报告

- 变更：`sync-borrowing-review-m34-baseline`
- 日期：2026-07-31
- 范围：仅评审规划文档与离线契约测试；不修改源码、运行时规格、Memory 数据或发布流程。

## 验证结果

- `uv run pytest tests/test_borrowing_roadmap.py tests/test_governance_docs.py -q`：`9 passed`。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：126 files already formatted。
- `git diff --check`：通过。
- `openspec validate --all --strict --no-interactive`：`30 passed, 0 failed`。

## 一致性检查

- 两份评审文档当前基线均为 M34，并保留 M32 作为继承的治理门禁。
- 运行时 Skill 自动拒绝标记为已由归档 change 交付；Memory 迁移和 Rewrite/依赖仍需真实需求。
- M33 历史证据、M34 milestone、`milestones/latest` 与 `publish-v0-1-0` 发布冻结均保持可追溯。

## 发布边界

未上传 PyPI、未创建正式 tag、未 push，未推进或归档 `publish-v0-1-0`。

Comet 的 Python build 自动探测不适用本项目；本 tweak 只涉及文档，验证使用上述离线测试和 OpenSpec 门禁，verify 状态以 `COMET_SKIP_BUILD=1` 跳过空探测推进。
