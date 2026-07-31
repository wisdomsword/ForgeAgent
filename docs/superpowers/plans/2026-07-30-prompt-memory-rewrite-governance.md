---
change: prompt-memory-rewrite-governance
design-doc: docs/superpowers/specs/2026-07-30-prompt-memory-rewrite-governance-design.md
base-ref: 6a304bc6273a3acfd06aae81dd265ce3eeef6347
archived-with: 2026-07-30-prompt-memory-rewrite-governance
---

# Prompt、Memory 与重写治理门禁实施计划

> **For agentic workers:** 按 `executing-plans` 逐任务执行；每个测试型任务遵循 TDD 红-绿-重构循环。

**Goal:** 建立不改变运行时行为的项目级治理规范和文档契约测试，锁定 Prompt/Skill 退出条件、Memory 四问、Rewrite/依赖六指标及 PyPI 发布冻结。

**Architecture:** 新增 `docs/agent-governance-gates.md` 作为唯一流程入口，其他规范文档只做短引用。新增 `tests/test_governance_docs.py` 读取固定项目文件并断言关键条款；不解析 Markdown AST、不新增依赖、不迁移 `MEMORY.md`。

**Tech Stack:** Markdown、Python `pathlib`、pytest、现有 OpenSpec/Comet 工具链。

## Global Constraints

- 只对新增或实质修改的长期 Prompt/Skill 生效，旧 Skill/Memory 格式保持兼容。
- 不修改 `SkillDefinition`、`MemoryCandidate`、Prompt 模板或运行时持久化行为。
- 不新增依赖、数据库、网络服务、自动过期或自动 Rewrite 评分器。
- PyPI 发布继续暂停：不上传、不创建正式 tag、不 push、不推进 `openspec/changes/publish-v0-1-0`。
- 保留工作区已有用户改动，不运行破坏性 git 命令。

archived-with: 2026-07-30-prompt-memory-rewrite-governance
---

### Task 1: 建立文档契约测试（RED）

**Files:**
- Create: `tests/test_governance_docs.py`

**Interfaces:**
- Consumes: project-root Markdown files via `Path(__file__).parents[1]`.
- Produces: deterministic pytest failures naming missing governance clauses.

- [x] **Step 1: Write the failing test**

  Add tests that load `docs/agent-governance-gates.md` and assert the five exit keys, five Memory review keys, six rewrite metrics plus evidence columns, and release-freeze terms. Also assert the canonical document is referenced by `spec.md`, `MILESTONE_GUIDE.md`, the comprehensive review, and `docs/threat-model.md`.

- [x] **Step 2: Run test to verify it fails**

  Run: `uv run pytest tests/test_governance_docs.py -q`
  Expected: FAIL because `docs/agent-governance-gates.md` and its references do not yet exist.

- [x] **Step 3: Add precise assertion helpers only**

  Keep helpers local to the test file; each assertion includes the missing field/filename in its failure message. Do not add production helpers or dependencies.

### Task 2: Add the canonical governance document (GREEN)

**Files:**
- Create: `docs/agent-governance-gates.md`
- Test: `tests/test_governance_docs.py`

**Interfaces:**
- Consumes: OpenSpec `agent-governance-gates` requirements and the two review documents.
- Produces: a human-readable process template with bounded exit, Memory, Rewrite, verifier, and release-pause clauses.

- [x] **Step 1: Write the five exit-condition template**

  Include `success`, `failure`, `blocked`, `needs_input`, and `timeout_or_budget`; require both `condition` and `verifier`, plus an explicit rule against unbounded absolute acceptance claims.

- [x] **Step 2: Write the Memory four-question review template**

  Include `why_remember`, `truth_source`, `expires_or_revalidate`, `visibility_and_recovery`, and `delete_or_correct`; state that session-only memory may use the session boundary but still needs source and correction behavior.

- [x] **Step 3: Write the six-metric Rewrite/Dependency gate**

  Include performance, reliability, maintenance cost, compatibility, team capability, and migration/rollback risk. For every row require baseline, threshold, evidence, migration, and rollback trigger.

- [x] **Step 4: Add scope, counterexamples, and release freeze**

  State that this is a development gate, not runtime schema; preserve old data; and explicitly prohibit PyPI upload, tag, push, and advancing `publish-v0-1-0`.

- [x] **Step 5: Run the focused test**

  Run: `uv run pytest tests/test_governance_docs.py -q`
  Expected: PASS.

### Task 3: Wire canonical references into project governance

**Files:**
- Modify: `spec.md`
- Modify: `MILESTONE_GUIDE.md`
- Modify: `docs/reviews/2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md`
- Modify: `docs/threat-model.md`
- Test: `tests/test_governance_docs.py`

**Interfaces:**
- Consumes: canonical governance document headings and release-freeze terms.
- Produces: traceable references from constitutional, milestone, review, and threat-model entry points.

- [x] **Step 1: Add the `spec.md` entry**

  Add a concise development-gate rule linking to `docs/agent-governance-gates.md`; do not alter product runtime requirements.

- [x] **Step 2: Add milestone stage checks**

  Add links at the problem-card/design/implementation/verification points in `MILESTONE_GUIDE.md`, without changing the fixed milestone template order.

- [x] **Step 3: Add review and threat-model references**

  Point candidate 5 at the canonical document and record residual risks for governance drift, missing exit verifiers, Memory source/visibility ambiguity, and unmeasured rewrites.

- [x] **Step 4: Run focused test and diff check**

  Run: `uv run pytest tests/test_governance_docs.py -q` and `git diff --check`.
  Expected: PASS with no whitespace errors.

### Task 4: Verify and close the change

**Files:**
- Modify: `openspec/changes/prompt-memory-rewrite-governance/tasks.md`
- Create: `milestones/milestone_032.md`
- Modify: `milestones/latest`
- Create: `docs/superpowers/reports/2026-07-30-prompt-memory-rewrite-governance-verify.md`

**Interfaces:**
- Consumes: all prior artifacts and verification outputs.
- Produces: completed task ledger, M32 milestone record, and evidence report.

- [x] **Step 1: Run the full verification set**

  Run: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `git diff --check`, and `openspec validate --all --strict --no-interactive`.
  Expected: all commands exit 0; report exact counts.

- [x] **Step 2: Perform final two-round self-review**

  Check for ambiguity, false claims, over-conservatism, contradictions, missed references, runtime drift, Memory migration, and release actions. Fix any finding and rerun affected checks.

- [x] **Step 3: Record evidence and archive through Comet**

  Check every task, write the verification report and M32 milestone, run `comet-guard ... build --apply`, then verify. Keep the branch and do not publish; archive only after the user’s explicit final archive confirmation if the bridge receives one.

