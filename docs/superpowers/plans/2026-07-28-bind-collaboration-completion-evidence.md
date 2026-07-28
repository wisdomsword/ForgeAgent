---
change: bind-collaboration-completion-evidence
design-doc: docs/superpowers/specs/2026-07-28-bind-collaboration-completion-evidence-design.md
base-ref: 7534ba8b24b616c03560d0ac82ef136feca0f283
---

# M26 协作完成证据绑定实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Duo/Triad 的全通过完成判定绑定到当前 Candidate 的全部宿主冻结检查通过证据，阻止未运行、失败、过期或跨快照检查造成 false completion。

**Architecture:** `check_runner.py` 对实际临时检查副本生成宿主私有快照摘要；`build_evaluator_registry` 为一次 Evaluator Task 创建最小内存证据表，并由 `RunCheckTool` 写入、`SubmitEvaluationTool` 校验。证据不持久化，新 attempt 和恢复后自然为空；失败 verdict 与无检查路径保持兼容。

**Tech Stack:** Python 3.11、Pydantic v2、pytest、现有 ForgeAgent Tool/Collaboration/Audit 接口；不新增依赖。

## Global Constraints

- 只有所有冻结验收项通过且所有宿主冻结检查都对当前 Candidate 通过时，协作才能 completed。
- 模型只能选择 check ID，不得提交或覆盖命令、状态、环境、路径、超时或快照证据。
- 检查证据必须绑定当前 Generator attempt 和实际临时副本摘要；Candidate 变化或跨检查摘要不一致必须 fail closed。
- 失败 verdict 可以在未运行全部检查时提前提交；未注册检查时保持现有行为。
- 恢复和新 Generator attempt 不复用旧进程内证据；`CollaborationState` schema 不变。
- 审计不得记录 argv、绝对路径、文件内容、完整输出、secret 或快照摘要。
- 不调整 M27 协作路由，不修改 M23/M25 历史评测，不新增依赖、配置面或通用抽象层。

---

### Task 1: 对实际检查副本生成稳定快照摘要

**Files:**
- Modify: `src/forgeagent/check_runner.py:80`
- Test: `tests/test_check_runner.py:23`

**Interfaces:**
- Consumes: 现有 `_ignored(name: str) -> bool`、`run_check(...) -> CheckResult` 和 `shutil.copytree` 临时副本。
- Produces: `candidate_snapshot_digest(root: str | Path) -> str`；`CheckResult.snapshot_digest: str = ""`，该字段默认不进入 `model_dump()`；已成功复制副本后的结果携带摘要。

- [x] **Step 1: 写摘要行为的失败测试**

在 `tests/test_check_runner.py` 增加测试，证明相同文件树摘要稳定，文件内容/路径/空目录/权限模式变化会改变摘要，而 `.git`、`.forgeagent`、缓存目录和 `*.pyc` 变化不会改变摘要；另断言 `run_check` 的成功结果具有 64 位摘要且 `result.model_dump()` 不包含 `snapshot_digest`。

- [x] **Step 2: 运行 RED 并确认缺失接口导致失败**

Run: `uv run pytest tests/test_check_runner.py -q`

Expected: FAIL，原因是 `candidate_snapshot_digest` 或 `snapshot_digest` 尚不存在，而不是 fixture/语法错误。

- [x] **Step 3: 实现最小摘要算法并绑定临时副本**

在 `check_runner.py` 使用标准库 `hashlib`，安全验证目录后按相对 POSIX 路径排序，将目录/文件类型标记、权限模式、文件长度和内容写入 SHA-256；复用 `_ignored`，拒绝符号链接和特殊文件。`run_check` 在复制完成后、创建 `.check-tmp` 前计算摘要，并传入所有复制后返回的 `_result` 路径。`CheckResult.snapshot_digest` 使用 Pydantic `Field(default="", exclude=True, repr=False)`，避免模型反馈或既有序列化调用暴露宿主证据。

- [x] **Step 4: 运行 GREEN 与回归测试**

Run: `uv run pytest tests/test_check_runner.py -q`

Expected: PASS，所有 check runner 测试通过。

- [x] **Step 5: 提交 Task 1**

```bash
git add src/forgeagent/check_runner.py tests/test_check_runner.py
git commit -m "feat: fingerprint evaluator check snapshots"
```

### Task 2: 在 Evaluator registry 内绑定检查证据与全通过提交

**Files:**
- Modify: `src/forgeagent/collaboration.py:1216`
- Test: `tests/test_collaboration_tools.py:323`

**Interfaces:**
- Consumes: Task 1 的 `candidate_snapshot_digest` 与 `CheckResult.snapshot_digest`。
- Produces: 当前 registry 私有的 `_CheckEvidence` 记录；`RunCheckTool(checks, evidence, generator_attempt)`；`SubmitEvaluationTool(store, state, checks, evidence)`；不改变模型参数 schema。

- [ ] **Step 1: 写完成门与兼容性的失败测试**

在 `tests/test_collaboration_tools.py` 增加或拆分测试覆盖：注册检查但未运行时全通过提交失败且 revision/evaluator attempt 不变；failed/timeout/cancelled/copy/start error 不能被自报 pass 覆盖；两个检查摘要不同被拒绝；检查通过后 Candidate 变化被拒绝；全部检查同一当前摘要通过后允许保存；至少一个验收项失败时无需检查即可保存；无检查 registry 保持现有工具集和提交行为。测试直接检查 `RunCheckArgs`/`SubmitEvaluationArgs` 的 extra 字段仍被 Pydantic 拒绝。

- [ ] **Step 2: 运行 RED 并确认现有 false completion**

Run: `uv run pytest tests/test_collaboration_tools.py -q`

Expected: FAIL，至少“未运行检查仍保存全通过 verdict”场景暴露现有行为。

- [ ] **Step 3: 实现最小私有证据表和全通过门**

在 `collaboration.py` 增加一个冻结私有记录，只保存 `status`、`snapshot_digest` 和 `generator_attempt`。`build_evaluator_registry` 仅在 checks 非空时创建普通 dict 并共享给两个工具。`RunCheckTool` 用宿主结果覆盖当前 ID；`SubmitEvaluationTool` 先完成现有 plan ID 校验，若存在失败项直接保存，若全部通过则验证缺失 ID、非 passed ID、attempt、摘要非空/一致和提交时 `candidate_snapshot_digest(ctx.allowed_root)`。失败反馈只含有界 check ID 或固定原因，不保存 state。

- [ ] **Step 4: 运行 GREEN 与相关模型测试**

Run: `uv run pytest tests/test_collaboration_tools.py tests/test_collaboration_models.py -q`

Expected: PASS，且既有无检查、脱敏和冻结 ID 测试保持通过。

- [ ] **Step 5: 提交 Task 2**

```bash
git add src/forgeagent/collaboration.py tests/test_collaboration_tools.py
git commit -m "feat: require current check evidence for collaboration pass"
```

### Task 3: 增加安全审计并验证恢复/新 attempt 不复用证据

**Files:**
- Modify: `src/forgeagent/collaboration.py:1263`
- Test: `tests/test_collaboration_tools.py:420`
- Test: `tests/test_collaboration_runner.py:200`

**Interfaces:**
- Consumes: Task 2 的私有证据记录和现有 `ToolContext.audit_sink`/`operation_id`。
- Produces: `collaboration.check` 审计事件；Runner 层对恢复和 rejection 后新 registry 的行为测试。

- [ ] **Step 1: 写审计和生命周期的失败测试**

增加测试断言 `collaboration.check` 只包含 check ID、Generator attempt、稳定状态和耗时，不含 argv、root、stdout/stderr 或摘要；增加 Runner 测试证明 evaluator phase 空 verdict 恢复时旧证据不可用，以及第一次 rejection 后新 Generator attempt 必须重新运行检查才可通过。使用既有 `_RoleBuilder`/`_reopened_duo_runner` 和真实 registry 工具调用，不在测试里直接篡改证据表。

- [ ] **Step 2: 运行 RED 并确认审计/生命周期断言失败**

Run: `uv run pytest tests/test_collaboration_tools.py tests/test_collaboration_runner.py -q`

Expected: FAIL，因为尚无 `collaboration.check` 事件或旧测试脚本未按新门禁重跑检查。

- [ ] **Step 3: 实现安全审计并调整最小 Runner 测试脚本**

`RunCheckTool` 在合法已注册检查结束后通过 `emit_audit` 发出稳定事件，沿用 ToolContext 的 task/operation ID，attempt 使用冻结 Generator attempt；parameters 不加入任何执行内容。生产 Runner 不新增持久字段；只通过每次 `build_evaluator_registry` 创建新证据表满足恢复和新 attempt 语义。更新受影响测试客户端脚本，使预期通过场景显式调用冻结检查。

- [ ] **Step 4: 运行 GREEN 与协作集成回归**

Run: `uv run pytest tests/test_collaboration_tools.py tests/test_collaboration_runner.py tests/test_collaboration_integrations.py -q`

Expected: PASS，恢复、取消、打回和 completion tool 语义无回归。

- [ ] **Step 5: 提交 Task 3**

```bash
git add src/forgeagent/collaboration.py tests/test_collaboration_tools.py tests/test_collaboration_runner.py
git commit -m "test: verify collaboration evidence lifecycle"
```

### Task 4: 契约、真实验证与里程碑收尾

**Files:**
- Create: `scripts/m26_completion_evidence_evaluation.py`
- Create: `tests/test_m26_completion_evidence_evaluation.py`
- Modify: `openspec/changes/bind-collaboration-completion-evidence/tasks.md`
- Modify: `ACTION_PLAN.md`
- Create: `docs/evaluation/m26/protocol.json`
- Create: `docs/evaluation/m26/runs/<run-id>/environment.json`
- Create: `docs/evaluation/m26/runs/<run-id>/summary.json`
- Create: `docs/evaluation/m26/runs/<run-id>/report.md`
- Create: `milestones/milestone_026.md`
- Modify: `milestones/latest`

**Interfaces:**
- Consumes: 完成的运行时、delta spec、M23/M25 已冻结的评测证据格式与 `MILESTONE_GUIDE.md`。
- Produces: 独立 M26 真实验证证据、完整验证记录与续接指引；不改写 M23/M25。

- [ ] **Step 1: 更新 M26 直接相关契约和任务状态**

仅更新 `ACTION_PLAN.md` 的当前里程碑状态/后续边界，并逐项勾选已经由提交和测试证明完成的 OpenSpec tasks。若实现中发现小型边界遗漏，同步修正 delta spec/design；不得扩展到路由校准或通用文档清理。

- [ ] **Step 2: 运行完整静态和测试验证**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv build --offline
openspec validate bind-collaboration-completion-evidence --strict
```

Expected: 全部命令退出码 0；记录测试数量和构建产物，不用旧输出代替当前验证。

- [ ] **Step 3: 运行独立 M26 小规模真实 Duo/Triad 验证**

先为 `scripts/m26_completion_evidence_evaluation.py` 写失败测试，固定其只运行 M26 最小样本、向 Duo/Triad Runner 注入宿主 `evaluator_checks`、采用独立输出根目录并拒绝写入 M23/M25。实现后复用 M23/M25 已冻结的模型与证据字段运行：至少一个会在未通过检查时被门禁拒绝的场景、一个全部检查与验收真实通过的场景，并覆盖 Duo 与 Triad。结果只写入 `docs/evaluation/m26/`，保存 protocol、environment、summary、raw 和 report；若外部模型/凭证不可用，记录阻塞原因并用受控端到端测试替代，不能伪造真实结果。

- [ ] **Step 4: 生成 M26 里程碑记录并完成双重最终审查**

按 `MILESTONE_GUIDE.md` 创建 `milestones/milestone_026.md` 并更新 `milestones/latest`。第一轮逐条映射 proposal/spec/tasks/测试/真实证据，第二轮专查错误、前后不一致、遗漏、false completion 旁路和无关文件污染；发现问题立即修复并重跑覆盖验证。

- [ ] **Step 5: 提交 Task 4**

```bash
git add ACTION_PLAN.md scripts/m26_completion_evidence_evaluation.py tests/test_m26_completion_evidence_evaluation.py docs/evaluation/m26 milestones/milestone_026.md milestones/latest openspec/changes/bind-collaboration-completion-evidence
git commit -m "docs: complete M26 evidence binding milestone"
```

## Plan Self-Review

- **Spec coverage:** Task 1 覆盖实际检查输入摘要；Task 2 覆盖全通过门、提前拒绝和无检查兼容；Task 3 覆盖审计、恢复和新 attempt；Task 4 覆盖全量/真实验证与里程碑收尾。delta spec 每个新增场景均有对应任务。
- **Placeholder scan:** 无 TBD/TODO、“类似任务”或未指定测试命令；真实评测命令必须先从现有脚本 `--help` 获取，避免计划硬编码不存在的参数。
- **Type consistency:** `candidate_snapshot_digest`、`CheckResult.snapshot_digest`、`_CheckEvidence`、`RunCheckTool` 和 `SubmitEvaluationTool` 的接口在任务间一致；不改变模型参数 schema 或持久状态 schema。
