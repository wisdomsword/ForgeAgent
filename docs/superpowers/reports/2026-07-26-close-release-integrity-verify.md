# 发布完整性收尾验证报告

## 结论

PASS。T1-T4 已完成：sdist 使用显式最小 allowlist，真实发布物不再包含开发目录、OpenSpec 工作资料或用户文件；README 具有唯一且可解析的当前验证章节；文档合同不再把易变的 pytest/OpenSpec 数量定义为永久产品值；历史 M22 证据保持原样。

## OpenSpec 完整验证

| 维度 | 结果 |
| --- | --- |
| Completeness | 5/5 tasks 完成；1/1 requirement 已实现 |
| Correctness | 2/2 scenarios 有真实 build 或文档合同测试映射 |
| Coherence | proposal、design、delta spec、实现和 README 一致 |

- sdist 场景映射：`pyproject.toml` 的 Hatchling include、`tests/test_packaging.py` 的真实 tar member 负向断言和隔离 wheel 安装探针。
- 当前证据场景映射：README `## 当前验证` 与 `tests/test_collaboration_docs.py` 的唯一章节/数字格式合同；ACTION_PLAN、M22 milestone 和历史报告中的 `2155` 未修改。
- delta requirement 归入现有 `golden-validation-core`，因为该能力已拥有自动化文档一致性和公开文档与验证行为一致合同；归档追加 requirement，不新增主规格目录。

未发现 CRITICAL、WARNING 或 SUGGESTION 项。

## TDD 证据

- RED：默认 sdist 根集合包含 `.agent`、`.agents`、`.claude`、`.codex`、`.superpowers`、`openspec`、docs/tests/scripts、`skills-lock.json` 与 `何为Harness.html`，包装合同失败。
- RED：README 尚无 `## 当前验证` 章节，文档格式合同失败。
- GREEN：加入 Hatchling sdist include 后包装专项 `3 passed`，文档专项 `8 passed`。
- Hatchling 会强制加入作为 VCS 排除规则来源的 `.gitignore`，并生成 `PKG-INFO`；两者作为构建后端元文件纳入精确允许根集合，未引入自定义 build hook。

## 最终门禁

| 检查 | 结果 |
| --- | --- |
| 完整 pytest | `2251 passed, 10 skipped in 85.74s` |
| 包装专项 | `3 passed` |
| 文档合同专项 | `8 passed` |
| 离线 golden | `20/20 passed (100.0%)` |
| Ruff check | `All checks passed!` |
| Ruff format | `105 files already formatted` |
| wheel/sdist build | wheel 与 sdist 均成功生成 |
| active OpenSpec strict | `19 passed, 0 failed`（18 个主规格 + 当前 change） |
| Git diff check | PASS |

最终 sdist 仅包含：`src/forgeagent/**`、`pyproject.toml`、`README.md`、`uv.lock`、Hatchling 强制加入的 `.gitignore` 与生成的 `PKG-INFO`。归档合并到既有 `golden-validation-core` 后，主规格目录数量保持 18。

## 两轮自审

1. 范围与历史证据审查：确认 README 只表达当前结果；ACTION_PLAN、M22 milestone 和历史报告继续保留当时的 `2155`，未篡改历史证据；未新增依赖、脚本、公共 API 或运行时改动。
2. 反向一致性审查：确认测试不是只查少数禁止项，而是同时锁定精确根集合；确认 README 合同校验章节唯一、四个数字字段和 pass/total 一致，但不固定值；确认 delta 不新增第 19 个主规格。

审查过程中曾为验证 OpenSpec 官方 `--skip-specs` 路径误执行一次提前归档；该命令未同步主规格，随后立即把目录恢复到 active change。恢复后 `comet status`、`openspec status`、git 状态与所有最终门禁均重新验证，未留下代码、主规格或状态损失。最终采用正常 Comet spec 同步路径。

## 审查与剩余风险

`review_mode: off`，按 tweak 预设未派发自动代码审查；full verify 与两轮自审覆盖了正确性、内容边界、文档一致性和历史证据。

剩余限制：显式 allowlist 会让未来新增的发布必需根文件默认缺席，这是安全边界的预期行为；届时应通过测试与评审显式加入。仓库当前没有许可文件，本 change 不伪造许可内容。
