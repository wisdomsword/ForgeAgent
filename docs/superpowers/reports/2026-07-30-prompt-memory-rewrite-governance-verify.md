---
comet_change: prompt-memory-rewrite-governance
role: verification-report
canonical_spec: openspec
---

# M32 验证报告

## Summary

| 维度 | 状态 |
| --- | --- |
| 完整性 | OpenSpec 任务 10/10，实施计划步骤全部勾选 |
| 正确性 | 4/4 项要求均由 canonical 文档、入口引用和确定性测试覆盖 |
| 一致性 | 评审修复后，设计、计划、规格与实现一致 |

## 验证证据

- `uv run pytest tests/test_governance_docs.py -q`：`5 passed`。
- `uv run pytest`：`2461 passed, 10 skipped`。
- `uv run ruff check .`：`All checks passed!`。
- `uv run ruff format --check .`：`125 files already formatted`。
- `git diff --check`：无输出，退出码 0。
- `uv build`：生成 `dist/forgeagent-0.1.0.tar.gz` 和 `dist/forgeagent-0.1.0-py3-none-any.whl`。
- `openspec validate --all --strict --no-interactive`：`28 passed, 0 failed`。

## 范围与评审修复

- 第一轮评审发现 Memory 缺少写入权限、候选验收与文档-only 范围矛盾、行级契约断言过弱、命名漂移和里程碑措辞过强。
- 第二轮评审又发现缺少模型升级回归/过时脚手架清理字段，以及发布中立检查不足。
- 所有问题均已修复到 canonical 文档、delta spec、设计文档、评审清单、里程碑指南和测试中；之后重新运行专项测试、OpenSpec strict 和全量 pytest。
- 设计 handoff hash 早于评审修订；验证时直接读取当前产物，没有虚报旧 hash 仍匹配。

## 明确边界

- 未修改 `SkillDefinition`、`MemoryCandidate`、Prompt 运行时，也未迁移 `MEMORY.md`。
- 运行时 stop-reason 映射和 Skill 自动拒绝留待独立后续 change。
- 未访问网络或凭据，未上传包、创建正式 tag、远程 push 或执行 PyPI 发布。
- `openspec/changes/publish-v0-1-0` 仍为 active 且未触碰。

## 最终自评

1. 模糊性：新 Prompt/Skill 退出字段统一为 `needs-input` 和 `timeout-or-budget`；旧注意力协议中的 `needs_input` 不属于本治理字段。
2. 错误/过度范围：否决运行时 schema 和历史 Memory 迁移；候选验收已改为文档契约范围，并明确运行时映射另立 change。
3. 遗漏/不一致：补充 `who_can_write`、模型版本/最小回归集、过时脚手架清理、行级测试、阶段检查和 ACTION_PLAN M32 台账。

指定 M32 文件中没有剩余 CRITICAL 或 IMPORTANT 问题。工作区仍有与 M32 无关的 M31/用户既有改动，均已保留。
