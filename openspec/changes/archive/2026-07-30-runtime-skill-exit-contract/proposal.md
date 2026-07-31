## Why

现有运行时 Skill 只校验五段文档结构，无法判断长期指令是否声明成功、失败、阻塞、需输入和超时/预算五类可观察退出条件。治理门禁已经要求这些字段，但运行时尚未执行同一契约，导致不完整的新增 Skill 仍可能进入模型可见目录。

本变更把退出条件纳入一个显式、可兼容的 Skill 文档版本：旧版 Skill 继续按既有规则读取；声明新版格式的 Skill 若缺少完整退出契约则 fail-closed 隔离，并提供有界诊断。

## What Changes

- 为 `SKILL.md` 增加显式 `format_version: 2` 运行时格式，要求五类退出条件分别声明可观察 `condition` 与负责 `verifier`。
- 在 Skill 解析结果中保留结构化退出条件，并在完整读取、项目可信摘要和内容摘要中稳定呈现，避免信任摘要遗漏治理字段。
- 新版 Skill 缺少字段、字段类型错误、空值、超限或使用无界绝对断言时跳过加载；旧版文档保持兼容。
- 为用户级、项目级、只读 Skill 工具和 `/reload` 路径补充契约测试与有界诊断测试。
- 明确本 change 不迁移既有 Skill 文件、不引入远程 Skills 供应链、不改变 PyPI 发布状态。

## Capabilities

### New Capabilities

- `runtime-skill-exit-contract`: 运行时 Skill 退出契约的版本化解析、验证、fail-closed 加载和结构化读取。

### Modified Capabilities

- `skills-runtime`: 修改 Skill 文档结构、发现、完整读取和可信摘要要求，使新版 Skill 的退出契约成为运行时可验证部分。

## Impact

- 代码：`src/forgeagent/skills.py` 及 Skill 相关工具装配和测试。
- 文档/spec：新增运行时退出契约 delta spec，并更新 `skills-runtime` 需求场景。
- 兼容性：默认保留现有无版本 Skill 的读取行为；只有明确声明 `format_version: 2` 的文档进入新校验路径。
- 依赖与发布：不新增依赖，不上传包、不创建 tag、不 push，也不推进 `publish-v0-1-0`。
