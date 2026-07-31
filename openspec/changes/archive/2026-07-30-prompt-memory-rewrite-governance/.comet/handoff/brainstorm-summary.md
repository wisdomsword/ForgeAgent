# Brainstorm Summary

- Change: prompt-memory-rewrite-governance
- Date: 2026-07-30

## 确认的技术方案

采用兼容性优先的治理门禁：新增单一 canonical 文档 `docs/agent-governance-gates.md`，并由 `spec.md`、`MILESTONE_GUIDE.md`、综合借鉴清单和 threat model 引用；新增纯本地 `tests/test_governance_docs.py` 锁定关键标题、字段、反例和 PyPI 发布暂停条款。

长期 Prompt/Skill 变更使用 success、failure、blocked、needs_input、timeout_or_budget 五元退出模板；长期 Memory 评审使用 why_remember、truth_source、expires_or_revalidate、visibility_and_recovery、delete_or_correct；Rewrite/依赖评审使用性能、可靠性、维护成本、兼容性、团队能力、迁移/回滚风险六项指标，并要求 baseline、threshold、evidence、migration、rollback trigger。

## 关键取舍与风险

- 不改 SkillDefinition、MemoryCandidate、Prompt 模板和 `MEMORY.md` 格式，避免旧数据迁移和运行时兼容风险。
- 不新增依赖、数据库、网络服务、自动过期或 Rewrite 自动评分器。
- 只对新增加或实质修改的长期 Prompt/Skill 生效，旧内容保持兼容。
- PyPI 发布持续暂停；不上传、不 tag、不 push、不推进 `publish-v0-1-0`。

## 测试策略

先写静态文档契约测试并确认缺少 canonical 文档时失败，再写文档使其通过；随后执行专项 pytest、全量 pytest、Ruff、diff check 和 OpenSpec strict。

## Spec Patch

无。
