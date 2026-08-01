## Why

M34 的运行时 Skill 退出契约源码、主规格和归档证据已经进入当前基线，但其专项回归测试没有进入干净 Git 历史。继续保留这种状态会让“已完成并归档”的声明缺少可执行 verifier，也可能让后续解析、掩码或信任摘要回归在全量测试中静默通过。

## What Changes

- 从只读来源工作区逐项恢复 M34 已验证的 Skill version 2 退出契约测试。
- 覆盖有效契约、fail-closed 校验、legacy 兼容、不可变映射、敏感值掩码和项目 effective trust digest。
- 记录来源与采纳边界；不复制旧源码，不覆盖 M44/M45 的 HTTP、MCP 或当前主规格。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `repository-lifecycle-integrity`：已完成运行时能力进入当前基线时，必须同时保留能直接验证其关键安全和兼容边界的可执行回归测试。

`runtime-skill-exit-contract` 和 `skills-runtime` 的运行时需求保持不变，本 change 只恢复其缺失的可执行 verifier。

## Impact

- 测试：`tests/test_skills.py`
- 证据：M45 对账报告与本 change 验证报告
- 依赖、公开 API、运行时行为和数据格式均不变
