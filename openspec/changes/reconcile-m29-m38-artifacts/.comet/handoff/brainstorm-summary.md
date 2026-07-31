# Brainstorm Summary

- Change: reconcile-m29-m38-artifacts
- Date: 2026-08-01

## 确认的技术方案

采用白名单恢复并建立离线生命周期门禁。只恢复 8 个缺失 milestone、10 个终态 archive、20 个缺失 Superpowers 工件、M32 canonical 治理文档/测试；缺失主规格通过当前 change 的 delta 合并。已存在的 M44 borrowing/HTTP、M45 MCP 和 `milestones/latest` 保持不变。

## 关键取舍与风险

拒绝全量复制主工作区，因为会吸收用户文件和过期基线；拒绝只写说明，因为不能修复链接与 OpenSpec 断链。历史 archive 只有同时满足 `phase: archive`、`verify_result: pass`、`archived: true` 才可恢复。历史测试计数保留但标记为当时快照，不能替代 M45 verifier。

两轮自审确认：旧 M30 archive 可作为 provenance 恢复，但不能覆盖 M45 修复规格；旧 borrowing spec 不采纳；开发分支 push 与 PyPI/tag/发布自动化分开表达。

## 测试策略

先增加失败的离线清单测试，精确报告缺失路径、无效 archive 状态、`Purpose: TBD` 和 delta-only canonical 标题。恢复后运行 governance、borrowing、skills、attention、collaboration 聚焦回归，再运行全量 pytest、Ruff、format、build、diff check 和 OpenSpec strict。

## Spec Patch

无。open 阶段已包含仓库生命周期完整性、4 个缺失能力 ADDED delta 和 `skills-runtime` MODIFIED delta。
