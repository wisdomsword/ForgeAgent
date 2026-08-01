## Context

M44 之后的干净分支已包含 M34 的 `SkillDefinition`、version 2 解析和退出契约实现，M45 又恢复了 M34 的主规格与历史 archive；但 `tests/test_skills.py` 仍停留在 M34 之前。根工作区保存了当时验证过的测试候选，同时混有较旧 HTTP/MCP 文件，因此只能按测试块选择性恢复。

## Goals / Non-Goals

**Goals:**

- 让当前 HEAD 直接验证 M34 已声明的安全、兼容和信任边界。
- 证明恢复内容只补测试，不改变已验证的运行时行为。
- 把 verifier 完整性纳入仓库生命周期对账门禁。

**Non-Goals:**

- 不复制或修改 M34 运行时源码。
- 不改变 Skill 格式、公开 API、依赖或迁移策略。
- 不同步根工作区中较旧的 HTTP、MCP、发布或文档候选。

## Decisions

1. 逐块恢复 M34 测试，而不是整体复制 `tests/test_skills.py`。这样来源可追溯，同时保留 M44/M45 当前文件内容。
2. 测试覆盖有效 version 2 文档、缺失/超限/绝对断言/重复键/alias cycle/控制字符拒绝、unsupported version、legacy 兼容、映射不可变、secret masking 和 effective trust digest。
3. 不修改运行时源码；任何失败先证明是当前实现回归还是候选测试假设过期，再做最小处理。
4. 在 `repository-lifecycle-integrity` 增加 verifier 完整性要求，避免以后只恢复“完成声明”而漏掉关键回归测试。

## Risks / Trade-offs

- [来源测试可能依赖旧基线细节] → 逐项运行并以当前 canonical spec 为裁决，不复制不匹配的断言。
- [增加测试时间] → 仅恢复 M34 的关键契约用例，不引入参数组合扩张或新依赖。
- [误覆盖后续修改] → 使用局部 patch，并用根工作区与当前文件的差异清单证明范围。
