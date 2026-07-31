# M38 分发目标退役验证报告

## 结论

通过。M30 及之后规划中的包索引发布、正式 tag、远程 push 和发布自动化目标已移除；历史 RC 记录保留；原 `publish-v0-1-0` 已撤销并归档。

## 验证

- 文档专项：`uv run pytest tests/test_borrowing_roadmap.py tests/test_governance_docs.py -q` -> `11 passed`。
- 发布文档/规划专项：`uv run pytest tests/test_m28_release_docs.py tests/test_borrowing_roadmap.py tests/test_governance_docs.py -q` -> `16 passed`。
- 全量回归：`uv run pytest` -> `2480 passed, 10 skipped`。
- OpenSpec：`openspec validate --all --strict --no-interactive` -> `30 passed, 0 failed`。
- Ruff：`uv run ruff check .` -> `All checks passed!`。
- 格式：`uv run ruff format --check .` -> `126 files already formatted`。
- Diff：`git diff --check` -> 通过。
- 目录状态：active `openspec/changes/publish-v0-1-0` 不存在；`openspec/changes/archive/2026-07-31-retired-pypi-publication-goal/publish-v0-1-0` 和撤销说明存在。
- 外部动作：未上传包、未创建 tag、未 push、未访问网络。

## 两轮最终自评

1. 语义一致性：历史“未发布”事实没有被改写成“已公开发布”；当前文档不再表达暂停等待授权或恢复发布的未来任务。
2. 范围一致性：未修改运行时代码、依赖、API 或 Memory 数据；M30-M37 的能力证据保持原有边界，新增只涉及规划生命周期和文档契约。

## 残余风险

更早里程碑和历史验证报告仍会出现 PyPI/发布冻结字样，这是历史审计证据，不属于当前路线图。若未来重新考虑公开分发，必须建立全新的独立 change。
