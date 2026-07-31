---
comet_change: reconcile-m29-m38-artifacts
role: technical-design
canonical_spec: openspec
---

# M29-M38 生命周期工件对账技术设计

## 1. 基线不一致

M44/M45 的源码和 ACTION_PLAN 已把 M29-M44 视为完成，但干净 Git 分支缺少 M29-M32、M35-M38 里程碑文件，M33/M34 的链接也指向不存在的历史 archive。主工作区存在这些文件，但同时包含旧 borrowing 基线、旧 MCP 主规格、用户 agent 配置和其他未提交内容。因此主工作区只能作为只读候选来源，不能作为整体同步源。

## 2. 恢复白名单

### 2.1 里程碑

恢复 `milestone_029.md`、`030`、`031`、`032`、`035`、`036`、`037`、`038`。每份追加统一 M45 对账注记；M30 额外引用 `2026-07-31-repair-mcp-progressive-disclosure-baseline`，说明当前执行契约已在 M45 重新证明。

### 2.2 OpenSpec archive

恢复以下历史目录：

- `2026-07-30-align-borrowing-roadmap-baseline`
- `2026-07-30-attention-state-projection`
- `2026-07-30-mcp-progressive-disclosure`
- `2026-07-30-prompt-memory-rewrite-governance`
- `2026-07-30-runtime-skill-exit-contract`
- `2026-07-30-structured-collaboration-handoff`
- `2026-07-31-align-http-trigger-next-steps`
- `2026-07-31-document-http-action-approval-trigger`
- `2026-07-31-retire-pypi-publication-goal`
- `2026-07-31-sync-borrowing-review-m34-baseline`

复制前检查 `.comet.yaml` 三个终态字段；复制后对整个仓库运行 OpenSpec strict。已有 `retired-pypi-publication-goal` 是被撤销 change 的历史目录，与完成 M38 文档更新的 `retire-pypi-publication-goal` 职责不同，两者都保留且均不进入 active changes。

### 2.3 Superpowers 与治理入口

恢复根工作区比 M45 多出的 5 份 design、5 份 plan、10 份 verify report，以及 `docs/agent-governance-gates.md` 和 `tests/test_governance_docs.py`。不恢复 `skills-lock.json`，因为既有历史证据明确将它归类为用户未跟踪文件，且运行时/治理测试不依赖它。

## 3. 规格恢复

当前 change 的 delta 是唯一新增主规格入口：

- ADDED：`agent-governance-gates`、`attention-state-protocol`、`runtime-skill-exit-contract`、`structured-collaboration-handoff`、`repository-lifecycle-integrity`；
- MODIFIED：`skills-runtime` 的 governed version 2 结构与按需 exit conditions。

历史 archive 原样恢复，不直接复制其 main spec。archive 当前 change 时，OpenSpec 将 delta 合并到 canonical specs。M45 `mcp-progressive-disclosure` 和 M44 `borrowing-review-baseline` 不参与本次 delta，避免降级。

## 4. Purpose 清理

新增测试枚举 `openspec/specs/*/spec.md`：

- 文件必须含 `## Purpose` 和非空下一段；
- Purpose 不得包含 `TBD - created by archiving`；
- canonical spec 不得包含 `## ADDED Requirements`、`## MODIFIED Requirements` 或 `## REMOVED Requirements`。

现有占位文件只改 Purpose 段，不改 requirement/scenario。新恢复规格在 archive 后若被 OpenSpec 模板写入 TBD，也必须在归档提交前修正并重新 strict validate。

## 5. 生命周期测试

`tests/test_repository_lifecycle.py` 使用标准库 `pathlib`、`re` 和 YAML 已有依赖的安全读取：

1. 固定白名单路径全部存在；
2. milestone 中的相对 Markdown 链接在仓库内可解析；
3. archive 终态字段正确；
4. `openspec list --json` 不由测试启动，测试只断言 active `publish-v0-1-0` 不存在；
5. current `milestones/latest` 目标存在，编号不小于恢复历史范围；
6. borrowing frontmatter 基线与 latest 一致或更新，不允许回退到 M34；
7. 全部 canonical Purpose 合法。

测试不执行 Git、网络、模型、发布工具或子进程，保持离线确定性。

## 6. 来源与冲突报告

`docs/reviews/2026-08-01-m45-m29-m38-artifact-reconciliation.md` 记录：

- 每类白名单、源根、源文件 SHA256 和目标状态；
- 采纳理由和当前 verifier；
- 明确拒绝的旧 borrowing 主规格、旧 MCP 主规格、`skills-lock.json` 与 agent 配置；
- 历史计数和当前 M45 计数的证据层级；
- 无 PyPI/tag/发布自动化、无 active 发布 change。

## 7. 回滚与完成标准

无数据迁移、无运行时行为变更。回滚本 change 的提交即可删除恢复工件并还原 Purpose。完成必须满足白名单测试、相关领域聚焦回归、全量 pytest、Ruff、format、build、diff check、OpenSpec strict，以及两轮最终一致性审查。
