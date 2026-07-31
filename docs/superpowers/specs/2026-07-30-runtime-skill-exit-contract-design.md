---
comet_change: runtime-skill-exit-contract
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-30-runtime-skill-exit-contract
status: final
---

# Runtime Skill Exit Contract Design

## Context

ForgeAgent 当前通过 `SkillRegistry` 发现并解析本地 `SKILL.md`，以固定 front matter 和三段正文保证渐进披露与项目内容信任。M32 已建立开发期治理门禁，要求新增长期 Skill/Prompt 声明成功、失败、阻塞、需输入、超时/预算五类退出条件，但运行时还没有可识别、可拒绝和可按需读取的对应结构。

本设计只处理运行时文档契约，不迁移历史文件、不扩展远程供应链、不新增依赖，也不改变执行权限或发布行为。

## Goals / Non-Goals

### Goals

1. 让新格式 Skill 以显式版本进入严格退出契约校验。
2. 让失败文档 fail-closed 且诊断有界，继续加载其他有效文档。
3. 让退出条件进入不可变定义、完整读取、分段读取和 project effective digest。
4. 让 legacy Skill 保持可读，同时明确其不满足 version 2 治理契约。

### Non-Goals

- 不自动改写既有 `SKILL.md`。
- 不在 Skill 执行时替代 Loop/Task 的终态与注意力状态判定。
- 不引入远程 Skill 下载、签名、撤销或平台化供应链。
- 不恢复 PyPI 发布，不创建 tag，不 push。

## Architecture

`_parse_document` 先解析固定 front matter：无 `format_version` 时构造 legacy version 1；值为 `2` 时解析固定 `exit_conditions` 映射并校验五类字段。其他版本直接拒绝。校验通过后，退出条件存入 `SkillDefinition` 的只读结构。

`_render_full_skill` 对 legacy 输入保持现有输出；对 governed 输入按固定顺序追加 `## Exit Conditions`。`SkillRegistry.read` 增加 `exit_conditions` 分段，legacy 返回 `None`。项目 Skill 的 effective digest 继续使用完整渲染，因此退出条件任何变化都会触发现有信任重新确认；raw digest 仍绑定原始文件字节。

## Contract Validation

- 固定版本：只允许 1（legacy）和 2（governed）。
- 固定键：version 2 front matter 只允许 `name`、`trigger`、`format_version`、`exit_conditions`。
- 固定退出类：`success`、`failure`、`blocked`、`needs_input`、`timeout_or_budget`，不可增删。
- 固定字段：每类只允许 `condition` 和 `verifier`，二者都必须为非空字符串。
- 单值上限：每个字符串最多 512 UTF-8 字节，整体仍受既有 32 KiB 文件上限约束。
- 绝对断言：当 condition 去除空白后只由无界绝对断言组成（如 `100% complete`、`always succeeds`、`全部完成`）时拒绝；带可观察对象/边界的条件允许。
- 安全：所有字段进入 registry 前走既有 `mask_secrets`。

## Error Handling

所有 version 2 契约错误统一转换为 `ValueError("invalid exit contract")`，复用 `_discover` 的有界诊断格式 `skill ignored: invalid exit contract (<name>)`。单个坏 Skill 不影响其他目录；项目 Skill 在解析阶段即被排除，不会进入信任摘要或覆盖用户 Skill。

## Testing Strategy

先以失败测试锁定：完整 v2、legacy、unsupported version、缺字段/重复字段/类型错误、长度边界、绝对断言、敏感值掩码、完整和分段读取、project effective digest 变化。再做最小实现，最后运行 Skill、Task、CLI/HTTP 相关回归和全库质量门禁。

## Alternatives Rejected

1. **所有 Skill 隐式强制五类字段**：会让历史用户 Skill 在升级后失效，超出本 change 的迁移范围。
2. **仅在开发期文档校验**：无法阻止运行时未治理 Skill 进入模型上下文，不能解决已识别缺口。
3. **新增独立 JSON 文件或新依赖**：增加同步、信任和部署复杂度；现有 YAML front matter 足以表达固定结构。
