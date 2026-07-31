# Prompt、Memory 与重写治理门禁设计

## Context

M31 已完成候选清单中的结构化 handoff。下一候选不是新的运行时能力，而是三条开发期质量纪律：长期 Prompt/Skill 的退出条件、长期 Memory 的四问、以及 Rewrite/依赖引入的量化门槛。当前实现已有 Skill 的失败分支/完成标准和 Memory 的安全写入边界，但缺少一个跨任务、可回归验证的治理入口。

## Goals / Non-Goals

**Goals:**

- 建立单一中文治理文档，作为 `spec.md`、`MILESTONE_GUIDE.md` 和后续 Comet 设计评审的引用入口。
- 把五类退出条件、Memory 四问（含可见性、恢复与删除/更正）和六项 Rewrite 门禁写成短字段、可检查的模板。
- 用纯本地文档契约测试锁定关键条款和 PyPI 发布暂停边界。

**Non-Goals:**

- 不改变 `SkillDefinition`、`MemoryCandidate`、Prompt 模板或持久化文件格式。
- 不迁移既有 `MEMORY.md`，不增加数据库、依赖、网络服务、自动记忆过期或 Rewrite 自动评分器。
- 不恢复 PyPI 发布，不创建 tag，不 push，不推进 `publish-v0-1-0`。

## Decisions

### 1. 采用 canonical 文档 + 引用，而不是运行时 schema

新增 `docs/agent-governance-gates.md` 作为流程事实源；`spec.md`、`MILESTONE_GUIDE.md` 和综合借鉴清单只引用其章节。这样可以让规范被人和评审工具读取，同时避免破坏现有 Skill/Memory 兼容格式。

备选方案是给 Skill frontmatter 和 Memory 行格式增加字段。该方案会引入旧文档迁移、持久化兼容和提示词上下文膨胀，与“流程纪律（零代码）”候选范围不符，否决。

### 2. 用静态文档契约测试作为最小 verifier

新增 `tests/test_governance_docs.py`，读取 canonical 文档和少量入口文档，逐项断言稳定标题、关键字段、反例和发布暂停词。测试不解析 Markdown AST、不访问网络、不读取凭据；失败消息包含缺失条款名称。

### 3. 退出条件采用统一五元模板

每个长期 Prompt/Skill 变更必须使用：`success`、`failure`、`blocked`、`needs-input`、`timeout-or-budget` 五行，并同时写 `condition` 和 `verifier`；模型升级还要记录模型版本、`minimum_regression_set` 和 `retire_stale_scaffolding`。现有 Skill 的 `Failure Branches`/`Completion Criteria` 继续作为运行时提示内容，不在本 change 中强制迁移。

### 4. Memory 四问扩展为可执行审查卡

治理模板要求回答核心四问 `who_can_write`、`truth_source`、`expires_or_revalidate`、`visibility_and_recovery`，并补充 `why_remember`、`delete_or_correct` 两个安全字段。`visibility_and_recovery` 同时回答“谁可见”和“崩溃后哪份恢复”。旧 Memory 内容不因本 change 自动补标。

### 5. Rewrite 门禁只规定证据，不自动给结论

六项固定指标为性能、可靠性、维护成本、兼容性、团队能力、迁移/回滚风险。每项必须有 baseline、threshold、evidence、migration、rollback trigger；缺任一项只能作为探索，不得进入实施。门禁不设全局数值阈值，因为不同模块的基线和风险不同。

## Risks / Trade-offs

- [流程文档与实现漂移] → 文档契约测试锁定入口条款；运行时 Skill/Memory 行为仍由各自专项测试负责。
- [模板过长导致形式主义] → 每个字段限制为一句话或一个可定位证据引用，不引入自动评分器。
- [旧文档不符合五元模板] → 只对新增或实质修改的长期 Prompt/Skill 生效，旧内容保持兼容并在后续变更中渐进补齐。
- [发布约束被误解] → canonical 文档和测试均检查 PyPI 暂停、不得 tag/push、不得推进 `publish-v0-1-0`。

## Migration Plan

1. 先添加失败的文档契约测试，确认测试能识别缺失条款。
2. 新增 canonical 治理文档，并在 `spec.md`、`MILESTONE_GUIDE.md`、综合借鉴清单和 threat model 中建立引用。
3. 运行定向测试、Markdown/diff 检查、全量 pytest、Ruff 和 OpenSpec strict。
4. 回滚只需移除本 change 新增文档、测试和引用；无运行时数据迁移。

## Open Questions

未来若要求运行时自动拒绝缺少退出条件的 Skill，必须另立 change，先定义旧 Skill 迁移、用户覆盖和 verifier 可信边界。
