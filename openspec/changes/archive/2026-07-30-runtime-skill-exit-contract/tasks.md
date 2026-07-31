## 1. 运行时契约模型

- [x] 1.1 为 `SkillDefinition` 增加显式 `format_version` 和不可变的五类 `exit_conditions` 数据，同时保持 legacy 文档的渲染与读取逐字节兼容。
- [x] 1.2 增加确定性的 version 2 front matter 解析、固定键校验、有界 condition/verifier 校验和 fail-closed 诊断；不引入新依赖。
- [x] 1.3 在 governed Skill 的完整读取中渲染退出条件，并通过只读 Skill 工具暴露 `exit_conditions` 段；保持 legacy 段读取行为不变。

## 2. 信任边界与回归测试

- [x] 2.1 按测试先行增加 fixture 和测试，覆盖有效 version 2、legacy 兼容、不支持版本、缺失/错误/超限字段、无界绝对断言拒绝和敏感值掩码。
- [x] 2.2 增加测试证明项目 Skill 仅修改退出 condition/verifier 时 effective digest 发生变化，同时 raw/effective 双摘要确认语义保持不变。
- [x] 2.3 增加完整读取、分段读取、有界诊断、`/reload` 快照替换和既有 SkillTool 行为测试。

## 3. 文档与验证

- [x] 3.1 在实现验证后更新 canonical `skills-runtime` Purpose 和 requirements，说明版本化退出契约与 legacy 兼容策略。
- [x] 3.2 编写 Superpowers 实施计划与带精确命令/结果的验证报告，并更新借鉴清单，将运行时强制校验标记为已交付。
- [x] 3.3 运行聚焦测试、全量 pytest、ruff check/format、`git diff --check`、`openspec validate --all --strict --no-interactive` 和本地 `uv build`；不得执行 PyPI 上传、tag 或 push。
