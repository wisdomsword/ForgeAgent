# M34 运行时 Skill verifier 恢复验证报告

- 变更：`restore-runtime-skill-verifiers`
- 日期：2026-08-01
- M45 基线：`1f6acb27b636c830a0779e71d4965f8fff262b03`
- 发布边界：未执行 PyPI 上传、正式 tag 或发布自动化；`uv build` 仅生成本地验证产物。

## 结论

当前基线原本已包含 M34 的运行时实现、主规格和历史 archive，但缺少其专项回归测试。本 change 已恢复并补强 11 组关键测试函数（其中参数化用例覆盖多个非法输入），并增加仓库生命周期门禁，保证后续不能在保留“完成”声明的同时静默删除或空实现这些 verifier。

恢复过程没有修改 `src/forgeagent/`。初始恢复的 `tests/test_skills.py` 与只读来源工作区逐字节一致，双方 SHA256 均为 `a19db6e8be68bbcbe81693fc7ca1af120d5ee8b888c4c37d738aec6a621ad07d`；审查后又补充了 canonical 512/513 UTF-8 字节边界、`verifier` 超限和空值/类型/键集合用例。

## TDD 证据

- RED：`uv run pytest tests/test_repository_lifecycle.py::test_m34_runtime_skill_contract_keeps_executable_verifiers -q` → `1 failed`，明确列出 10 个缺失测试函数。
- GREEN：恢复并审查补强后 `uv run pytest tests/test_repository_lifecycle.py tests/test_skills.py -q` → `47 passed`。
- 相关专项：lifecycle、skills、governance、borrowing、attention 与 collaboration → `329 passed`；补充 SkillTool 专项后为 `92 passed`。

审查后，生命周期门禁改为绑定 M34 Skill 与 SkillTool 关键测试函数、装饰器和 governed/legacy fixtures 的 AST 语义 SHA256 摘要，函数被改成 `pass`、skip 或弱化断言都会触发失败；摘要不覆盖无关测试，避免锁死整个测试文件。

## 完整验证

| 命令 | 结果 |
| --- | --- |
| `uv run pytest -q` | `2734 passed, 10 skipped in 171.32s` |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `146 files already formatted` |
| `git diff --check` | 通过 |
| `git diff 1f6acb2..HEAD --check` | 通过 |
| `git diff 8513bef..HEAD --check` | 通过 |
| `uv build` | sdist/wheel 本地构建成功，未上传 |
| `openspec validate --all --strict --no-interactive` | `36 passed, 0 failed` |

## 边界复核

- 没有复制或修改 M34 源码；当前行为由恢复的测试重新证明。
- 没有采纳根工作区较旧的 HTTP、MCP、发布或主规格差异。
- 没有恢复 `publish-v0-1-0`，也没有执行 PyPI、tag 或发布自动化。
- 本 change 的 delta 只要求已对账运行时能力保留可执行 verifier，不改变 Skill 运行时契约。

## 独立审查修正

独立只读审查未发现 HTTP、MCP、发布源码夹带或 Critical 安全问题，并指出三项覆盖/证据缺口，现已全部修正：

- 将仅检查函数名的生命周期门禁升级为包含装饰器和 fixtures 的 AST 语义摘要，阻止 `pass`、skip 或断言弱化伪装成 verifier。
- 增加 512 UTF-8 字节接受、513 多字节拒绝、`verifier` 超限、空白/非字符串、缺少字段、额外字段和额外退出类测试。
- 从提交文档中移除宿主绝对路径，只保留中性来源说明和内容摘要。
