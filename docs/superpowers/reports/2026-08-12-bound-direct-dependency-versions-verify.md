# bound-direct-dependency-versions 验证报告

日期：2026-08-12
基线：`41d494f79d28c81bf871f75b77b84a83c0815063`

## 结论

| 维度 | 结果 | 证据 |
| --- | --- | --- |
| 完整性 | PASS | 4/4 tasks 完成；全部直接依赖均有上界 |
| 正确性 | PASS | `uv lock` 成功；锁文件仅更新直接依赖 specifier |
| 一致性 | PASS | `pyproject.toml`、`uv.lock` 与依赖契约测试保持一致 |

当前全量 pytest 仍保留 1 个与本 tweak 无关的既有失败：`tests/test_cli.py::test_run_once_streamed_prose_answer_is_not_rendered_twice`（S8）。

## 需求与实现映射

- `pyproject.toml` 为所有直接运行时依赖及 `pytest`、`ruff` 增加主版本兼容上界。
- `uv.lock` 只同步对应 specifier，没有包版本升级或降级。
- `tests/test_collaboration_docs.py` 的直接依赖精确集合断言同步更新。

## 验证命令

| 检查 | 结果 |
| --- | --- |
| `uv lock` | PASS |
| 依赖契约聚焦测试 | PASS |
| 全量 `pytest -q` | 1 failed, 2987 passed, 11 skipped；唯一失败为既有 S8 |

## 备注

- 本 tweak 不修改运行时源码、公共 API 或功能行为。
- 上界按现有 `openai>=2.24,<3` 风格收敛；未来跨主版本升级需要单独验证。
