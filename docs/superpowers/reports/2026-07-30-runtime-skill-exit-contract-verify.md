# 运行时 Skill 退出契约验证报告

- 变更：`runtime-skill-exit-contract`
- 日期：2026-07-30
- PyPI：继续暂停；未上传、未创建 tag、未 push，也未推进活跃的 `publish-v0-1-0`。

## 范围证据

- 显式 `format_version: 2` 的 Skill 必须声明五类退出条件，每类都有有界 `condition` 和 `verifier`。
- 缺失、类型错误、超限、重复键、不支持版本和纯绝对断言会被 fail-closed 隔离，并输出有界诊断。
- 未声明版本的历史文档保持 version 1 兼容，原有完整渲染不变。
- governed 退出条件经过掩码、不可变封装、确定性渲染，可通过 `exit_conditions` 分段读取，并参与项目 effective trust digest。
- YAML alias 自引用和退出字段中的换行/C0 控制字符也会被 fail-closed 隔离，避免递归崩溃或 Markdown/front matter 注入。

## 验证命令与结果

| 命令 | 结果 |
| --- | --- |
| `uv run pytest tests/test_skills.py tests/test_tools.py tests/test_task.py -q` | 101 passed |
| `uv run pytest tests/test_skills.py tests/test_tools.py tests/test_task.py tests/test_borrowing_roadmap.py -q` | 109 passed |
| `uv run pytest -q` | 2477 passed, 10 skipped |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 126 files already formatted |
| `git diff --check` | 通过 |
| `openspec validate --all --strict --no-interactive` | 29 passed, 0 failed |
| `uv build` | 本地 sdist 与 wheel 构建成功 |

Comet 的自动 build 探测不识别 Python/`uv` 项目，因此没有推断出可执行命令。上面的显式 `uv build` 已提供真实构建证据；随后使用 `COMET_SKIP_BUILD=1` 仅跳过 Comet 的空探测并推进状态，没有跳过实际构建或测试。

## 两轮自评与修正

- 第一轮自评拒绝隐式迁移，避免升级后现有用户 Skill 集体消失。
- 第二轮自评补充了嵌套 YAML 重复键拒绝、手工构造定义的不可变映射、SkillTool governed 分段读取和敏感值掩码测试。
- 代码审查追加发现并修复 Critical alias-cycle 递归崩溃与 Important 控制字符注入；新增两项回归测试并重新通过专项门禁。
- 工作区中与 M29-M33 相关的既有脏改动均保留；本里程碑只改动 Skill 契约相关代码、测试、规格和规划记录。

## 发布边界

本报告只证明本地实现、测试和打包成功，不构成 PyPI 发布、正式 tag、远程 push 或 `publish-v0-1-0` 归档授权。
