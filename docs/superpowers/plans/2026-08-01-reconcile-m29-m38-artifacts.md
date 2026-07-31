---
change: reconcile-m29-m38-artifacts
design-doc: docs/superpowers/specs/2026-08-01-reconcile-m29-m38-artifacts-design.md
base-ref: 1b65c5635baa267012c3fb3f1a3e9551b5622867
---

# M29-M38 生命周期工件对账实施计划

## 任务 1：建立失败的生命周期契约

**文件：**
- 新增：`tests/test_repository_lifecycle.py`

1. 固定 8 个 milestone、10 个 archive、20 个 Superpowers 工件、治理文档/测试和 4 个缺失主规格白名单。
2. 检查 archive 三个终态字段、milestone 相对链接、当前 latest/baseline 不回退、active 发布 change 不存在。
3. 检查所有 canonical spec Purpose 非占位且无 delta-only 标题。
4. 运行专项测试，保存缺失路径和 TBD 导致的 RED 证据。
5. 勾选任务 1.1、1.2 并提交测试。

## 任务 2：恢复白名单历史工件

**文件：**
- 新增：`milestones/milestone_029.md` 至 `032.md`、`035.md` 至 `038.md`
- 新增：10 个 `openspec/changes/archive/` 历史目录
- 新增：20 个 `docs/superpowers/` 工件
- 新增：`docs/agent-governance-gates.md`
- 新增：`tests/test_governance_docs.py`
- 新增：`docs/reviews/2026-08-01-m45-m29-m38-artifact-reconciliation.md`

1. 对来源 archive 检查终态并计算 SHA256。
2. 只按 Design Doc 白名单复制目标不存在的文件。
3. 为 8 个 milestone 追加 M45 对账注记，M30 关联 M45 repair archive。
4. 在对账报告记录采纳文件、来源 SHA、拒绝冲突和分发边界。
5. 运行生命周期测试，确认文件链/状态类失败消失；提交恢复工件。

## 任务 3：恢复与清理 canonical specs

**文件：**
- 由当前 delta 新增：4 个历史能力主规格和 `repository-lifecycle-integrity`
- 由当前 delta修改：`openspec/specs/skills-runtime/spec.md`
- 修改：所有含归档器 TBD 的 `openspec/specs/*/spec.md`

1. 保持当前 change 的 delta spec strict valid，不直接复制历史 main spec 到目标。
2. 为现有 canonical spec 填写准确 Purpose，只修改 Purpose 段。
3. archive 后检查新生成主规格 Purpose，若模板产生 TBD 则立即修正。
4. 运行生命周期、governance、borrowing、skills、attention 和 collaboration 回归。

## 任务 4：完整验证与归档

1. 运行 `uv run pytest -q`。
2. 运行 `uv run ruff check .`、`uv run ruff format --check .` 和 `git diff --check`。
3. 运行 `uv build` 和 `openspec validate --all --strict`。
4. 对来源白名单、当前基线优先、无占位、无 active 发布 change 做两轮最终自审。
5. 完成验证报告并归档 change；不执行 PyPI、tag、push 或发布自动化。
