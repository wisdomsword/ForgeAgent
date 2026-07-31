## Context

`src/forgeagent/skills.py` 当前把 front matter 限定为 `name` 与 `trigger`，正文限定为三段，并将解析后的五段内容放入不可变 `SkillDefinition`。项目级 Skill 的信任摘要和 effective-input digest 都由该定义渲染而来。M32 已把长期 Prompt/Skill 的五类退出声明纳入开发期治理，但运行时仍无法区分 governed Skill 与旧格式 Skill。

本 change 需要在不迁移历史文件、不引入新依赖、不改变项目级信任边界的前提下，把新契约接入发现、读取和摘要流程。

## Goals / Non-Goals

**Goals:**

- 引入显式 `format_version: 2`，对新格式执行 fail-closed 的五类退出条件校验。
- 保持无版本历史 Skill 的读取兼容，并让调用方可识别 legacy 与 governed 定义。
- 让完整渲染、按段读取、项目 effective digest 和敏感值掩码覆盖退出条件。
- 用单元测试覆盖成功、缺失字段、类型/边界、无界断言、旧格式和信任摘要变化。

**Non-Goals:**

- 不自动改写或迁移现有 `SKILL.md`。
- 不建立远程 Skill 分发、签名、撤销或供应链平台。
- 不改变 Skill 执行权限、sandbox、Task 完成判定或 PyPI 发布状态。

## Decisions

1. **显式版本而非隐式强制。** `format_version` 缺失视为 version 1，`2` 才启用退出契约；这样不会在本 change 中让用户目录里的既有 Skill 集体消失。其他版本 fail-closed。
2. **结构化 front matter。** version 2 的 front matter 只允许 `name`、`trigger`、`format_version`、`exit_conditions` 五个固定键；`exit_conditions` 是五个固定映射，每项只允许 `condition` 和 `verifier`。正文三段保持原样，避免重复解析协议。
3. **有界文本规则。** `condition` 和 `verifier` 必须是非空字符串，单项不超过 512 UTF-8 字节；只含无界绝对断言的 condition（例如 `100% complete`、`always succeeds`、`全部完成`）拒绝。规则保持确定性、无网络和无额外模型调用。
4. **定义与渲染。** `SkillDefinition` 增加 `format_version` 和只读 `exit_conditions` 映射。`_render_full_skill` 在 version 2 文档中追加 `## Exit Conditions`，按固定顺序输出五类及其字段；legacy 文档输出保持字节级兼容。`read(..., "exit_conditions")` 对 legacy 返回 `None`，对 governed 返回结构化文本。
5. **信任摘要绑定。** project Skill 的 effective-input digest 继续对完整渲染结果取摘要，因此任何退出条件变化都会触发已有确认；raw digest 仍绑定原始字节，保持双摘要语义。
6. **错误面。** 所有版本 2 校验失败都转为 `ValueError("invalid exit contract")`，沿用现有 `_discover` 的单条 bounded diagnostic 和“跳过坏文档、继续发现”语义。

## Risks / Trade-offs

- [兼容性] 旧格式不会自动获得治理保证 → 通过 `format_version` 明示 legacy 状态，并在开发期 change/文档中要求新建或实质修改的 Skill 使用 version 2。
- [规则误报] 某些合法自然语言可能包含绝对词 → 只拒绝纯绝对断言，不限制含可观察条件的正常句子，并用回归测试锁定边界。
- [摘要长度] 退出条件加入完整渲染可能增加 trust summary 输入 → effective digest 不受摘要展示截断影响；既有 32 KiB 文档上限继续生效。

## Migration Plan

无需数据迁移。新建或实质修改的 Skill 使用 `format_version: 2` 和五类退出条件；未迁移的历史文档继续按 version 1 读取。若 version 2 文档被拒绝，诊断会指出 Skill 名称和 `invalid exit contract`，用户修正文件后通过 `/reload` 获取新快照。

## Open Questions

无。运行时执行退出条件本身仍由现有模型/Task 流程负责，本 change 只负责声明完整性和可信读取。
