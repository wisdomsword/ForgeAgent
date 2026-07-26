## Context

Hatchling 当前按默认规则生成 sdist，仓库根目录中的开发资料和用户文件因此可能被自动收集。README 顶部混合了历史里程碑证据与易变的当前测试数量，M22 文档测试又把某次历史数量绑定为 README 的永久合同。

## Goals / Non-Goals

**Goals:**

- 使用 Hatchling 原生配置表达可审计的 sdist 最小 allowlist。
- 以真实构建产物的负向测试锁定发布边界。
- 将 README 当前验证结果放入独立、格式稳定的章节。
- 让 M22 历史证据只在历史产物中保持不可变。

**Non-Goals:**

- 不新增构建脚本、依赖、发布命令或动态测试数量同步工具。
- 不修改 wheel 内容、版本号、运行时或历史验证报告。

## Decisions

1. 使用 `[tool.hatch.build.targets.sdist] include` 最小 allowlist，包含 `src/forgeagent`、`pyproject.toml`、`README.md` 和 `uv.lock`。Hatchling 会额外强制加入作为 VCS 排除规则来源的 `.gitignore` 和生成的 `PKG-INFO`；接受这两个后端元文件，不为删除它们引入自定义 build hook。仓库当前没有许可文件，因此不伪造或新增许可文件。
2. 负向测试读取真实 tar member，统一去掉 sdist 顶层目录后检查相对路径；禁止代理/IDE/工作流目录、OpenSpec、用户锁文件和已知本地 HTML 文件。
3. README 使用 `## 当前验证` 标题及单行机器可读格式：`pytest: <passed> passed, <skipped> skipped；OpenSpec strict: <passed>/<total>`。测试只校验章节唯一、字段存在和数字格式，不固定数值。
4. 当前 pytest 数量采用实现完成后的新鲜完整测试证据。历史 M22 的 `2155` 只保留在 ACTION_PLAN、验证报告和 milestone，不再要求 README 重复历史基线。

## Risks / Trade-offs

- [新增根文件未自动进入 sdist] -> 这是 allowlist 的预期安全属性；发布必要文件应通过显式评审加入。
- [README 数量仍会随测试变化而过时] -> 文档合同不再锁死数量，每次发布收尾用新鲜完整测试更新。
- [uv.lock 增大 sdist] -> 它是当前唯一必要锁文件，可复现构建环境；不包含用户本地状态。
