## Context

前一 change 已用 Hatchling sdist allowlist 收窄发布输入，并用真实构建测试检查发布内容。复审确认边界本身成立，但测试从 tar 的首个成员推导归档根目录，隐含依赖成员排序；README 合同只计算完整正则匹配，额外畸形的 `## 当前验证` 标题不会导致失败，而且该检查仍位于 M22 历史收尾测试中。

## Goals / Non-Goals

**Goals:**

- 让发布内容测试与 tar 成员顺序无关。
- 让 README 当前验证章节真正唯一，并与历史 M22 证据解耦。
- 让 README 和 ACTION_PLAN 准确记录 2026-07-26 的最新验证与归档状态。

**Non-Goals:**

- 不调整 Hatchling 构建后端或发布文件集合。
- 不重写 M22 里程碑、历史报告或历史测试数字。
- 不修改 ForgeAgent 运行时。

## Decisions

1. 从全部 tar 成员的首段路径构造集合，并要求恰有一个归档根；不再信任首个成员的顺序。
2. 在现有发布测试中显式断言 `pyproject.toml`、`README.md`、`uv.lock`、`.gitignore` 和 `PKG-INFO`，继续用顶层集合等值断言禁止其他仓库内容。
3. 单独建立 README 当前验证合同测试：先要求 `## 当前验证` 标题只出现一次，再校验结构化计数；M22 测试只负责历史收尾证据。
4. README 记录本次发布完整性收尾和验证报告；ACTION_PLAN 增加最新状态段，不改 M22 行中的 `2155 passed / 10 skipped` 历史证据。

## Risks / Trade-offs

- 拆分测试会使 pytest 通过数增加 1；README 只在完整验证后写入实测新值。
- `.gitignore` 与 `PKG-INFO` 是 Hatchling 构建所需/生成的元文件，仍作为明确例外保留在归档根集合中。
