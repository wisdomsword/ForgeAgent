# 里程碑 M34: 运行时 Skill 退出契约

- 状态: 已完成
- 起止: 2026-07-30 ~ 2026-07-30
- 对应 ACTION_PLAN 行: M34
- 前置里程碑: [milestone_033](milestone_033.md)
- OpenSpec change: [runtime-skill-exit-contract](../openspec/changes/archive/2026-07-30-runtime-skill-exit-contract/)

## 目标与范围

M34 将 M32 的 Prompt/Skill 五类退出条件治理门禁接入运行时 Skill 解析链，同时保持历史 Skill 兼容：

- `format_version: 2` 文档必须声明 `success`、`failure`、`blocked`、`needs_input`、`timeout_or_budget` 五类退出条件；
- 每类退出条件必须有不超过 512 UTF-8 字节的 `condition` 与 `verifier`，纯无界绝对断言拒绝；
- 缺失、错误、超限、重复键或不支持版本的文档 fail-closed 隔离，并输出有界诊断；
- 未声明版本的历史文档按 version 1 读取，完整渲染保持兼容；
- governed 退出条件经过掩码、不可变封装、确定性渲染，可按 `exit_conditions` 分段读取，并参与项目 effective trust digest。

不包含既有 Skill 自动迁移、远程分发/签名/撤销、执行权限或 sandbox 变更、Memory 元数据迁移、Rewrite/依赖变更和任何 PyPI 发布动作。

## 方案与实现

- 在 `src/forgeagent/skills.py` 增加 `SkillExitCondition`、版本化 front matter 校验、嵌套 YAML 重复键检测和 governed 渲染；`SkillDefinition` 的退出映射始终不可变。
- 在 `src/forgeagent/protocol.py` 与 `src/forgeagent/tools.py` 增加 `exit_conditions` 只读段路由；legacy Skill 请求该段返回不可用，不改变旧段语义。
- 项目 trust 继续使用完整渲染的 effective digest，因此修改任一退出字段会触发既有重新确认。
- canonical `skills-runtime` Purpose/requirements、治理门禁和借鉴清单已同步更新。

## 任务清单

- [x] 版本化 SkillDefinition 与五类退出契约解析。
- [x] fail-closed 校验：缺失/错误/超限/重复键/绝对断言/不支持版本。
- [x] 审查加固：YAML alias 自引用和退出字段控制字符均 fail-closed，避免 registry 崩溃或结构注入。
- [x] governed 完整读取、`exit_conditions` 分段读取、掩码和不可变映射。
- [x] project effective digest 退出字段变更重新确认。
- [x] 规格、治理文档、借鉴清单和验证报告同步。

## 两轮自评

### 方案自评

- 第一轮：拒绝对历史 Skill 隐式强制迁移，避免没有回滚和用户覆盖路径的破坏性升级；选择显式 version 2。
- 第二轮：补充嵌套 YAML duplicate-key fail-closed、legacy/version 公开区分、项目摘要绑定和无界条件边界，避免“有字段但不可验证”的假治理。

### 实现自评

- 检查了 `SkillRegistry.load -> _discover -> _parse_document -> SkillTool.read` 全链路，确认坏 Skill 不进入 catalog、trust digest 或模型反馈。
- 检查了 secrets masking、MappingProxyType、固定顺序、legacy byte-compatible rendering 和工具继续反馈提示。
- 检查了工作区既有 M29-M33 脏改动，未回滚或覆盖无关文件；未触碰 `publish-v0-1-0`。

## 验收证据

- 专项：`uv run pytest tests/test_skills.py tests/test_tools.py tests/test_task.py -q` -> `101 passed`；审查加固后含规划回归 -> `109 passed`。
- 全量：`uv run pytest -q` -> `2477 passed, 10 skipped`。
- 质量：`uv run ruff check .`、`uv run ruff format --check .`、`git diff --check` 全部通过。
- 规格：`openspec validate --all --strict --no-interactive` -> `29 passed, 0 failed`。
- 构建：`uv build` 本地 sdist/wheel 成功；Comet 自动 build 探测不识别 uv 项目，已用显式构建证据并以 `COMET_SKIP_BUILD=1` 只跳过空探测。
- Comet：build/verify 守卫通过，change 已归档为 `openspec/changes/archive/2026-07-30-runtime-skill-exit-contract/`。

## 遗留问题

- 既有 Memory 元数据迁移：仍需真实需求、来源/回滚/verifier 后独立立项。
- Rewrite/依赖变更：当前没有量化需求，继续按六项指标门禁等待触发。
- 外部分发：不在当前路线图；原 `publish-v0-1-0` 已撤销归档。

## 续接指引

M34 已完成并归档。下一会话读取本文件和 `ACTION_PLAN.md`；当前无新的已授权运行时 change。若出现 Memory 迁移或 Rewrite/依赖真实需求，先建立问题卡并按 Comet full 流程立项；不要把本里程碑的 legacy 兼容策略误读为自动迁移授权。
