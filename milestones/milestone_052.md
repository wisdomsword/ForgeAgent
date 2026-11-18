# 里程碑 M52: 标准 Skills SDK 兼容路径

- 状态: 已完成并归档
- 起止: 2026-10-28 ~ 2026-11-07
- 对应 ACTION_PLAN 行: M52（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_051](milestone_051.md)

## 目标与范围

为 ForgeAgent 的 skill 发现与加载（`src/forgeagent/skills.py`）增加标准 Skills SDK 兼容路径：接受 `name + description + 自由正文` 的标准技能（skill-creator、find-skills 实证），经 `SkillRegistry` 正常加载，同时保持 native 严格格式与全部安全属性（名称格式、symlink 包含、secret 掩码、目录信任确认、raw/effective digest 全量绑定）不变。改动集中一个模块；不新增依赖、不改 skill 文本协议/工具行为/协作路由、不改变发布边界、不 push。

## 方案设计

- **识别规则**：front matter `format_version==1` 且不含 `trigger` 但含 `description` → 兼容路径；含 `trigger` → native 原路径；同时含 `trigger` + `description` → 拒绝（`invalid format`）。
- **映射**：trigger 由 description 派生（`" ".join(split())` 压成单行、≤240 字符、超长在最近空格截断，无空格则硬截断）；正文 → Steps（`_bounded_body` 截断到 32768 UTF-8 字节，`errors="ignore"` + `rstrip` 保持完整字符边界）；Failure Branches/Completion Criteria 合成固定文本。
- **有界与安全**：磁盘 256KB 上限（`_MAX_COMPAT_SKILL_BYTES`）；native >32KB 仍拒绝（`raw_bytes` 重加强制）；名称格式、symlink 包含（发现层）、secret 掩码、目录信任确认、raw digest 绑定**完整磁盘内容**（32KB 截断点之后的变更仍触发信任重新确认）全部保留。
- 无新依赖；改动集中 `skills.py`，`_parse_document` 增加 `raw_bytes`/`diagnostic` 参数（内部仅 `_discover` 一处调用）。

## 子任务清单

- [x] 实现兼容路径（`_parse_document` 识别 + `_parse_standard_document` + `_derive_trigger` + `_bounded_body`）
- [x] 新增 11 项 compat 持久化回归测试（`tests/test_skills.py`，含 digest 确定性）
- [x] Comet change `standard-skills-sdk-compat`：brief + 目标 Spec + Shape 确认 → Build → Verify（6/6）→ Archive
- [x] ACTION_PLAN.md M52 登记并更新为完成

## 交付物清单

- [x] `src/forgeagent/skills.py` — 新增兼容路径：`is_standard` 识别、`_parse_standard_document`、`_derive_trigger`、`_bounded_body`、`_MAX_COMPAT_SKILL_BYTES`、`_MAX_TRIGGER_CHARS`、合成节常量。
- [x] `tests/test_skills.py` — 11 项 compat 测试：加载、正文截断、trigger 派生、非法拒绝（5 参数化）、hybrid 拒绝、raw digest 绑全量、digest 确定性（二次加载不重提示）。
- [x] `docs/comet/changes/standard-skills-sdk-compat/brief.md` + `specs/standard-skills-sdk-compat/spec.md` — Comet 需求与完整目标 Spec（6 个 `Scenario:` 分别标注 `验收：A1`…`A6`）。
- [x] `ACTION_PLAN.md` — M52 基线行与里程碑表条目。

## 三次评审

### 技术方案评审

- [x] 对照 brief/spec 逐条复核：识别规则、映射规则、有界与安全、6 场景与 A1-A6 对齐。
- [x] 未新增依赖、未改 Skill 文本协议/工具行为/协作路由、未改 `SkillDefinition` 公共形状与 catalog 边界；改动集中一个模块。

### 代码评审

- [x] 全面自评发现并修正 2 处 Shape 问题（目录结构误列非新建文件、缺「验证预期」披露 2 个既有失败），并补充 1 项 A6 确定性测试。
- [x] 独立 Verifier 核查候选 `a92165b`：兼容路径实现与 brief/spec 逐条一致，`pytest tests/test_skills.py` 52 passed，ruff check/format 清，skills.py 无 mypy 错误。

### 验收评审

- [x] Comet change 归档：verdict pass，验收 **6/6 通过**（A1-A6），candidate `a92165b`，archive commit `aa663197`。
- [x] 全量套件 `3071 passed, 10 skipped, 2 failed` —— 2 个既有失败为 m23/m25（history-rewrite 哈希失效，非 M52 引入），已在 brief「验证预期」披露、不计入 M52 验收。

## 遗留问题

- [x] M52 当时的全量套件存在 2 个既有失败（`tests/test_m23_mode_evaluation.py`、`tests/test_m25_mode_evaluation.py`）：引用里程碑历史重写前已失效的提交哈希（c20c0948/8e82fdd4/9e1e5c58），`git ls-tree` 退出 128，已在干净 HEAD 实证复现、与 M52 无关 — 后续维护（2026-11-18）：`fix-github-release-readiness` 已改用固定摘要与可移植证据校验，M23/M25 定向测试通过；原 M52 验收数字保留为历史记录。最新全量检查见[维护验证报告](../docs/superpowers/reports/2026-11-18-fix-github-release-readiness-verify.md)。

## 续接指引

M52 已完成并归档，下一阶段从 `ACTION_PLAN.md` 与本文件开始。继续保持：native 严格格式与安全属性不放宽；标准 Skills SDK 技能仅经兼容路径加载，正文始终内存有界（≤32KB）、磁盘 ≤256KB；raw digest 绑定完整磁盘内容。发布（新 GitHub remote + push）仍待用户明确授权：不 push、不用 `git push --all --tags`。
