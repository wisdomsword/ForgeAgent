# 里程碑 M15: 运行时身份文件层

- 状态: 已完成（真实 wheel/sdist 构建受当前沙箱 DNS/构建缓存限制，作为明确遗留）
- 起止: 2026-07-17 ~ 2026-07-21
- 对应 ACTION_PLAN 行: M15（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_013](milestone_013.md)
- 已验证实现 HEAD: `901b9a8d7573e18d9408264ad25f193506a0eb30`

## 目标与范围

交付分层运行时身份文件层：包内提示词模板与组合器、用户/项目身份加载、项目信任确认与持久化、CLI `--no-identity` 与 `/reload`、固定协议和 Kiro 防污染回归、G381-G400 候选扩展、威胁模型与 README 更新。身份文件只在显式 CLI 接线读取；Task 直接构造保持零文件 I/O。

## 方案设计

- 使用 `ApprovedIdentity` 快照和包内 `importlib.resources` 模板组合系统提示词，固定 harness/protocol 段不受身份内容覆盖。
- 用户级 SOUL/USER 与项目级 AGENTS/MEMORY 分层加载；项目身份以 canonical root、symlink containment、大小/secret 掩码和有界诊断约束。
- 项目批准使用 v1 trust record：project/digest 字段为 canonical lowercase SHA-256，`approved_at` 为 UTC RFC3339-Z；畸形或悬空记录不可授权或覆盖。确认后的任务使用冻结内存快照，后续磁盘变化在下一次解析时重确认。
- CLI 交互确认、headless 默认拒绝、`--no-identity` 和 `/reload` 均保持固定 MCP/protocol 语义；TOCTOU 残余风险在 threat model 中明确记录。

## 子任务清单

- [x] Task 1-4：提示词资源、身份加载、信任记录、Task 接线
- [x] Task 5-6：CLI 身份接入、`--no-identity`、`/reload`
- [x] Task 7：wheel/sdist 资源回归测试（真实构建待具备 hatchling/DNS 的环境执行）
- [x] Task 8-10：矩阵/TOCTOU、固定协议、G381-G400 与独立 mock replay
- [x] Task 11：README、威胁模型和文档一致性断言
- [x] Task 12：专项、非 packaging 全量、golden、静态检查和最终两道实现评审
- [ ] 真实 wheel/sdist 隔离安装 — 当前沙箱无法解析 PyPI `hatchling`；保留未验证状态，需在有构建后端缓存/网络的环境执行

## 交付物清单

- [x] `src/forgeagent/identity.py` — 身份快照、资源加载、symlink/大小/掩码边界、信任记录语义校验
- [x] `src/forgeagent/task.py` / `src/forgeagent/cli.py` — 显式身份组合、CLI 确认、`--no-identity`、`/reload`
- [x] `tests/test_identity.py` / `tests/test_task.py` / `tests/test_cli.py` — TDD、矩阵、TOCTOU、信任 schema 与 CLI 回归
- [x] `tests/test_packaging.py` — wheel/sdist 真实安装探针（隔离 `-I`/环境/cwd，并校验安装模块来源）
- [x] `tests/test_golden_runner.py` / `tests/test_golden_candidates_identity.py` / `docs/golden-tasks-seed.md` — G01-G400、20/380、160/100/80/40/20 与 M15 8/5/4/2/1 门禁
- [x] `README.md` / `docs/threat-model.md` — 身份边界、T12、TOCTOU 和候选/可信核心口径

## 三次评审

### 技术方案评审

- [x] Task 12 spec consistency rereviewer：`901b9a8` 与 runtime-identity/golden-validation-core specs、design、plan 一致，未发现 Critical/Important
- [x] strict OpenSpec validation：`openspec validate compose-runtime-identity --strict` → `Change 'compose-runtime-identity' is valid`
- 技术方案与代码评审已通过；第三道验收证据评审槽位见“验收评审”唯一 pending 项

### 代码评审

- [x] whole-branch reviewer 首轮发现并修复：悬空 symlink、trust record 语义校验、Rich literal label、golden category ratio gate
- [x] whole-branch rereviewer：`9470988..901b9a8` → Approved；无 Critical/Important/阻塞 Minor
- 代码评审已通过；第三道验收证据评审槽位见“验收评审”唯一 pending 项

### 验收评审

- [x] 非 packaging 全量：`981 passed, 13 skipped`；skip 为 Docker、本地 socket、外网能力和既有慢测试，均有明确原因
- [x] identity/CLI/golden 定向回归：fix 后 identity `75 passed`、CLI `152 passed`、golden `78 passed`；最终聚焦汇总 `309 passed`
- [x] 离线 golden：`.venv/bin/python -m tests.golden.runner` 退出 0；无模型凭证时未运行 real 模式
- [x] 静态/规范：全仓 Ruff check、变更涉及的 10 个 Python 文件 format check、`git diff --check`、strict OpenSpec 均通过；全仓 format 诊断另有 7 个未修改历史文件 baseline 差异
- [ ] 真实 wheel/sdist：未验证 — `uv build` 无法解析 PyPI `hatchling`（DNS/缓存受限）
- [x] 第三道证据评审：APPROVED by `/root/task_12_evidence_reviewer`

## 遗留问题

- [ ] wheel/sdist 隔离安装未在当前沙箱完成 — 影响：无法在本环境证明构建产物资源加载 — 计划：在具备 hatchling 缓存或网络的环境运行 `tests/test_packaging.py`
- [ ] CLI `/help reload` 仍有既有文案只描述 models/config — 影响：帮助文本不完整 — 计划：后续独立文案清理，不扩大本 change
- [ ] CodeGraph 索引属于主 checkout — 影响：无法将索引结果当作当前 worktree 精确调用图 — 计划：已按警告使用当前 worktree 直接源码、diff 和测试复核，未运行 `codegraph init`
- [ ] 5 项真实模型 golden 未运行 — 影响：不构成离线门禁失败 — 计划：仅在显式模型/凭证 opt-in 时运行

## 续接指引

当前实现固定在 `901b9a8d7573e18d9408264ad25f193506a0eb30`。第三道验收证据评审已通过；真实 wheel/sdist 构建仍需在具备 hatchling 缓存或网络的环境执行。后续提交仅允许 evidence-only 文件，随后运行 Comet build guard 并进入 Comet verify/archive 流程。
