# 目标

为 ForgeAgent 的 skill 发现与加载增加标准 Skills SDK 兼容路径：接受 `name + description + 自由正文` 的标准技能（如 anthropics/skills 的 skill-creator、vercel-labs/skills 的 find-skills），经 `SkillRegistry` 正常加载，同时保持 native 严格格式与全部安全属性（名称格式、symlink 包含、secret 掩码、目录信任确认、raw/effective digest 全量绑定）不变。

# 范围

## 目录结构

### 新建

- `docs/comet/changes/standard-skills-sdk-compat/specs/standard-skills-sdk-compat/spec.md` — 本 change 的完整目标 Spec，描述标准 Skills SDK 兼容加载行为（含 `Scenario:` 标记的验收场景）。

### 修改

- `src/forgeagent/skills.py` — 新增标准 Skills SDK 兼容路径：`_parse_document` 识别无 `trigger` 但有 `description` 的标准技能并转 `_parse_standard_document`；派生 trigger（描述压成单行 ≤240 字符）、正文→Steps、合成 Failure Branches/Completion Criteria、正文截断 32KB 内存有界（磁盘 256KB 上限）；native 严格格式路径与 32KB 磁盘上限保持不变。
- `tests/test_skills.py` — 新增 10 项 compat 持久化回归测试与 `_standard_skill_document` 辅助函数。
- `ACTION_PLAN.md` — 登记 M52 基线行与里程碑表条目。

### 删除

无

### 明确不建

- 独立的新技能格式模块 — 兼容路径实现在既有 `skills.py` 内，改动集中一个模块。
- 新的第三方依赖 — 无需新依赖；标准技能正文沿用既有 secret 掩码与有界机制处理。
- 解析标准技能声明的显式 exit conditions — 标准 Skills SDK 技能不声明失败分支/完成标准，由兼容路径合成通用文本。
- 修改 skill 文本协议、Skill 工具行为或协作路由 — 兼容路径仅在发现/解析层，不改下游行为。

# 非目标

- 不改动 native 严格格式（`name + trigger` + `## Steps`/`## Failure Branches`/`## Completion Criteria`）及其校验。
- 不改变 `SkillDefinition` 公共形状、catalog 边界（64 条目/16KB）、目录信任确认或 secret 掩码语义。
- 不改变 skill 文本协议、Skill 工具行为或协作路由。
- 不新增依赖、不改变发布边界、不 push、不发布。

# 验收示例

- A1：标准 Skills SDK 技能（`name + description + 自由正文`）经 `SkillRegistry` 加载；trigger 由 description 派生（单行、≤240 字符、无换行），正文成为 Steps，Failure Branches/Completion Criteria 为合成文本。
- A2：native 严格格式技能仍按原路径加载；native 非法情形（未知 key、多行 trigger、trigger+description 混合）仍拒绝。
- A3：native 技能磁盘大小 >32KB 仍拒绝；兼容技能正文截断到 ≤32KB（内存有界）。
- A4：兼容技能磁盘 >256KB、空正文、缺 description、空白 description、名称不匹配均拒绝。
- A5：兼容技能 raw digest 绑定完整磁盘内容：32KB 截断点之后的变更（不改变截断后正文）仍触发信任重新确认。
- A6：兼容技能经完整 `SkillRegistry.load` 管线加载（catalog、信任确认、read 各节、digest 确定性），与 user 侧 native 技能共存。

# 验证预期

- M52 的验收以 `tests/test_skills.py` 的 compat 测试（51 项中新增 10 项）与 `uv run pytest tests/test_skills.py -q` 全绿为准，不要求全量套件清零。
- 全量套件存在 **2 个既有失败**（`tests/test_m23_mode_evaluation.py`、`tests/test_m25_mode_evaluation.py`），源于里程碑历史重写后引用的提交哈希（c20c0948 / 8e82fdd4 / 9e1e5c58）已不存在（`git ls-tree <hash>` 退出 128）。已实证：在干净的 HEAD（stash 后）上仍同样失败，**与 M52 无关**。Verifier 不应把这两个失败计入 M52 验收。
