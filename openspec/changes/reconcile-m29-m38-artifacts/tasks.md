## 1. 失败契约与来源清单

- [x] 1.1 增加离线生命周期契约测试，覆盖 M29-M38 里程碑、archive、Superpowers 工件、主规格和 `TBD` Purpose
- [x] 1.2 运行专项测试并确认当前基线因缺失文件和主规格占位失败
- [x] 1.3 记录白名单来源路径、SHA256、采纳/拒绝理由和新基线优先裁决

## 2. 历史证据恢复

- [x] 2.1 恢复 8 个缺失里程碑并追加 M45 历史证据/分发边界对账注记
- [x] 2.2 恢复 10 个已验证终态的历史 archive，不创建 active 发布 change
- [x] 2.3 恢复 20 个缺失 Superpowers design/plan/report、治理文档和离线治理测试

## 3. 主规格修复

- [x] 3.1 通过 delta 恢复 4 个缺失能力规格和 M34 `skills-runtime` 增量
- [x] 3.2 为全部 canonical spec 填写非占位 Purpose，不修改既有 requirements
- [x] 3.3 确认 M44 borrowing/HTTP、M45 MCP 和 `milestones/latest` 未被旧来源覆盖

## 4. 验证与归档准备

- [x] 4.1 运行 lifecycle、governance、borrowing、skills、attention 和 collaboration 聚焦回归
- [x] 4.2 运行全量 pytest、Ruff、format、build、diff check 和 OpenSpec strict
- [x] 4.3 完成两轮最终自审并记录归档证据，不执行 PyPI、tag、push 或发布自动化
