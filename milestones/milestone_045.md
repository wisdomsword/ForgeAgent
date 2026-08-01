# 里程碑 M45: 基线一致性与生命周期证据对账

- 状态: 已完成并归档
- 起止: 2026-08-01 ~ 2026-08-01
- 对应 ACTION_PLAN 行: M45（见该文件 §四里程碑表）
- 前置里程碑: [milestone_044](milestone_044.md)
- OpenSpec changes:
  - [repair-mcp-progressive-disclosure-baseline](../openspec/changes/archive/2026-07-31-repair-mcp-progressive-disclosure-baseline/)
  - [reconcile-m29-m38-artifacts](../openspec/changes/archive/2026-07-31-reconcile-m29-m38-artifacts/)
  - [restore-runtime-skill-verifiers](../openspec/changes/archive/2026-08-01-restore-runtime-skill-verifiers/)
  - [sync-m45-planning-baseline](../openspec/changes/archive/2026-08-01-sync-m45-planning-baseline/)
- 分发边界: 不执行 PyPI、正式 tag 或发布自动化；普通开发分支 push 已获明确授权，仅作版本控制交接

## 目标与范围

M45 解决 M44 干净分支与历史开发工作区之间的三类可证明基线断层：M30 已注册 `MCPDescribe`，但真实
`MCPManager` 缺少查询方法且 prompt 仍可能泄漏完整 schema；M29-M38 的部分里程碑、Comet archive、
设计/计划/报告和 canonical specs 未进入当前 Git 基线；M34 的运行时实现和规格存在，但关键回归测试缺失。

本里程碑将根工作区视为只读候选来源，只采纳可验证白名单，不整体复制脏工作区。M39-M44 的正式提交经
Git 祖先链证明已集成，不重复 cherry-pick。M45 不恢复 `publish-v0-1-0`、PyPI/tag/发布自动化，不改变
M44 HTTP 能力的历史归属；只将借鉴清单当前基线同步到 M45，不引入新依赖、Gateway、Memory 数据迁移或
Rewrite 试验。

## 方案设计

- `MCPManager.describe_tool()` 只读取 available discovery snapshot 并返回深拷贝；system prompt 只保留有界
  目录摘要，schema 由 `MCPDescribe` 按需读取。
- M29-M38 历史工件使用固定白名单、来源 SHA/tree manifest 和 M45 对账注记恢复；历史计数仅证明当时快照，
  当前 HEAD 由 M45 门禁重新证明。
- canonical spec 通过当前 delta 语义恢复，不用旧 M30/M34 文件覆盖 M44/M45 较新规范；所有 Purpose 去除
  归档模板占位。
- M34 verifier 先用 lifecycle RED 暴露缺失，再恢复只读来源测试；独立审查后增加 UTF-8 字节、类型/键
  边界，并以 AST 语义摘要绑定关键 Skill/SkillTool 测试、装饰器和 fixtures。
- 借鉴评审基线以 `milestones/latest` 为权威来源；frontmatter、正文和目标里程碑完成状态由测试精确绑定，
  M44/M43 仍分别保留为 HTTP 审批和 Rewrite 基线的历史交付证据。
- 设计与来源裁决见
  [`M45 对账报告`](../docs/reviews/2026-08-01-m45-m29-m38-artifact-reconciliation.md)。

## 子任务清单

- [x] 完成 MCP 渐进披露真实 manager 契约修复、TDD、full verify 与归档。
- [x] 恢复 M29-M38 授权白名单工件、canonical specs 与治理入口，完成来源/拒绝项记录。
- [x] 审计 M39-M44 Git 祖先链，确认正式提交已集成且无需历史 cherry-pick。
- [x] 补回 M34 运行时 Skill verifier，并修复独立审查发现的可伪满足和覆盖缺口。
- [x] 同步借鉴评审文档、canonical 规划基线和 `milestones/latest`，并加固精确一致性门禁。
- [x] 完成四项顺序 Comet change、最终两轮自评和 M45 全区间验证。

## 交付物清单

- [x] `src/forgeagent/mcp_manager.py`、`tests/test_mcp_manager.py` — manager-owned discovery 查询、深拷贝、
  有界目录与重复读取验证。
- [x] `milestones/milestone_{029,030,031,032,035,036,037,038}.md` — 已验证历史记录及 M45 对账注记。
- [x] `openspec/changes/archive/2026-07-30-*`、`2026-07-31-*` 授权白名单 — 历史 Comet 生命周期证据。
- [x] `openspec/specs/` — M29/M31/M32/M34 主规格恢复、Purpose 修复和 verifier 完整性要求。
- [x] `tests/test_repository_lifecycle.py`、`tests/test_governance_docs.py`、`tests/test_skills.py` — 生命周期、
  治理和 M34 可执行契约门禁。
- [x] `docs/reviews/2026-08-01-m45-m29-m38-artifact-reconciliation.md` — 来源摘要、采纳/拒绝与残余边界。
- [x] 两份 Agent 开发指南借鉴评审、`borrowing-review-baseline` 和对应生命周期测试 — M45 当前基线同步。
- [x] `docs/superpowers/reports/2026-08-01-*-verify.md` — 四个顺序 change 的验证证据。

## 三次评审

### 技术方案评审

- [x] 第一轮区分“运行时实现缺失”“生命周期证据缺失”和“测试 verifier 缺失”，避免整体复制脏工作区。
- [x] 第二轮确认 M39-M44 正式提交已在 M45 祖先链；只补 M34 测试，不重复实现或覆盖较新 HTTP/MCP 代码。
- [x] 所有恢复项都有当前契约、来源摘要或可执行测试；拒绝项不被伪装为延期任务。

### 代码评审

- [x] `reconcile-m29-m38-artifacts` 独立只读审查发现并修复 exact archive state、tree manifest 定义、
  开发分支 push 措辞、恢复白名单范围和 diff whitespace 问题。
- [x] `restore-runtime-skill-verifiers` 独立只读审查发现并修复函数名门禁可伪满足、UTF-8/类型/键边界
  覆盖不足和验证报告宿主绝对路径问题。
- [x] `sync-m45-planning-baseline` 独立只读审查发现并修复三项/四项计数、M32-M43 过期范围、综合文档
  证据链接缺失和字符串门禁可伪满足问题。
- [x] 最终第二轮自评发现并移除对账报告中的宿主绝对路径；来源摘要仅保留相对标识和内容摘要。
- [x] 未发现 Critical 安全问题；M45 第三个 change 的 base→HEAD 无 `src/forgeagent/` 修改，未夹带旧
  HTTP、MCP、发布源码或配置。

### 验收评审

- [x] 相关专项 `329 passed`；M34 lifecycle/skills/SkillTool 专项 `92 passed`；规划基线专项 `22 passed`。
- [x] 最终全量 `2734 passed, 10 skipped`；Ruff、146 文件 format、`uv build` 和 M44→M45 全区间
  `git diff --check` 通过。
- [x] 第四个 change 归档前 OpenSpec strict `36/36`，归档后 `35/35`；四个 change 均为 `phase: archive`、`verify_result: pass`、
  `archived: true`。
- [x] 未执行 PyPI、正式 tag 或发布自动化；本地构建产物未上传。

## 遗留问题

M45 范围内无未完成任务。Memory readiness 仍为 `no_data`，M43 仍裁决 `keep_python`，HTTP listener 仍
loopback-only；这些是已验证边界，不是待自动推进的缺口。只有出现真实 Memory 数据、六项 Rewrite 指标越阈
或跨主机 HTTP 控制需求时，才分别新建 change。发布目标继续保持移除。

## 续接指引

M45 已完成四项顺序 change、最终全量验证和生命周期闭环。下一会话先读取本文件和 `ACTION_PLAN.md`；
当前没有活跃 OpenSpec change，也没有自动承诺的 M46。若用户提出新任务，先以当前 M45 基线核对真实缺口，
不要从根工作区未提交候选反向覆盖当前分支。HTTP 保持 loopback，未知外部动作禁止自动重放，PyPI、正式
tag 和发布自动化仍不在路线图；普通开发分支 push 只按明确授权执行。
