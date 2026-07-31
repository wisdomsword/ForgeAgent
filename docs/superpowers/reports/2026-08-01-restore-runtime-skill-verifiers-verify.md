# M34 运行时 Skill verifier 恢复验证报告

- 变更：`restore-runtime-skill-verifiers`
- 日期：2026-08-01
- M45 基线：`1f6acb27b636c830a0779e71d4965f8fff262b03`
- 发布边界：未执行 PyPI 上传、正式 tag 或发布自动化；`uv build` 仅生成本地验证产物。

## 结论

当前基线原本已包含 M34 的运行时实现、主规格和历史 archive，但缺少其专项回归测试。本 change 已恢复 10 组关键测试函数（其中参数化用例覆盖多个非法输入），并增加仓库生命周期门禁，保证后续不能在保留“完成”声明的同时静默删除这些 verifier。

恢复过程没有修改 `src/forgeagent/`。`tests/test_skills.py` 与只读来源 `/Users/admin/Code/llm-agent/ForgeAgent/tests/test_skills.py` 逐字节一致，双方 SHA256 均为 `a19db6e8be68bbcbe81693fc7ca1af120d5ee8b888c4c37d738aec6a621ad07d`。

## TDD 证据

- RED：`uv run pytest tests/test_repository_lifecycle.py::test_m34_runtime_skill_contract_keeps_executable_verifiers -q` → `1 failed`，明确列出 10 个缺失测试函数。
- GREEN：恢复后 `uv run pytest tests/test_repository_lifecycle.py tests/test_skills.py -q` → `37 passed`。
- 相关专项：lifecycle、skills、governance、borrowing、attention 与 collaboration → `318 passed`。

## 完整验证

| 命令 | 结果 |
| --- | --- |
| `uv run pytest -q` | `2723 passed, 10 skipped in 171.08s` |
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
