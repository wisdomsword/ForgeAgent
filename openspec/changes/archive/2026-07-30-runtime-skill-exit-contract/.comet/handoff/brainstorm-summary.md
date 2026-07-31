# Brainstorm Summary

- Change: runtime-skill-exit-contract
- Date: 2026-07-30

## 确认的技术方案

- 使用显式 `format_version: 2` 进入 governed Skill 解析路径；未声明版本的既有 Skill 按 version 1 兼容。
- version 2 的 front matter 使用固定键和固定五类 `exit_conditions`，每类包含有界 `condition` 与 `verifier`。
- 解析失败沿用现有发现器的 fail-closed 隔离和单条 bounded diagnostic；不影响其他有效 Skill。
- `SkillDefinition`、完整渲染、`exit_conditions` 分段读取及项目 effective digest 共同携带这五类声明。

## 关键取舍与风险

- 不对历史 Skill 做隐式强制迁移，避免现有用户目录在升级后集体消失。
- 只拒绝纯无界绝对断言，不拒绝包含可观察条件的正常自然语言。
- 不引入依赖，不做远程分发/签名/撤销，不改变执行权限或 PyPI 状态。

## 测试策略

- 先写失败测试，再实现解析和渲染。
- 覆盖 valid v2、legacy、unsupported version、缺失/错误/超限/绝对断言、掩码、trust digest、full/section read、reload 和 SkillTool。
- 完成后运行 focused tests、full pytest、ruff、OpenSpec strict validation、git diff check 和本地 uv build。

## Spec Patch

- 回写 `skills-runtime` 的固定结构和只读工具需求，增加 governed exit contract 与 legacy compatibility 场景。
