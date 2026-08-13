# harden-restricted-write-boundary 验证报告

日期：2026-08-12  
基线：`41d494f79d28c81bf871f75b77b84a83c0815063`

## 结论

| 维度 | 结果 | 证据 |
| --- | --- | --- |
| Completeness | PASS | hotfix tasks 4/4 完成；proposal/design/spec/tasks 与实现一致 |
| Correctness | PASS | restricted runtime prefix 普通写、`.pth` 创建、installed worker 文件写入三条回归全部通过 |
| Coherence | PASS | 修复仅收紧 restricted worker 写边界；runtime prefix 读导入保持可用 |

当前全量 pytest 仍保留 1 个已知非本 hotfix 回归：`tests/test_cli.py::test_run_once_streamed_prose_answer_is_not_rendered_twice`（S8）。

## 需求与实现映射

- `src/forgeagent/_sandbox_worker.py` 在 restricted worker 安装 audit hook 时启用 `writes_only_in_root=True`，保留 runtime prefix 读权限并限制写权限到 `allowed_root`。
- `tests/test_restricted_backend.py` 新增三条真实子进程回归：runtime `site-packages` 普通写、`.pth` 创建、installed worker 文件写入均被固定拒绝。
- `docs/threat-model.md` 修正 T2/T7：明确 `-I` 仍允许已安装环境导入，但 restricted 任务代码不能写 `sys.prefix` / `site-packages`。

## 验证命令

| 检查 | 结果 |
| --- | --- |
| RED：S1 三条新回归 | 2 failed, 1 passed（确认 `site-packages` 普通写与 `.pth` 创建原本可成功） |
| GREEN：S1 三条新回归 | 3 passed |
| `tests/test_restricted_backend.py` | 17 passed |
| `tests/test_check_runner.py` | 41 passed |
| 全量 `pytest -q` | 1 failed, 2987 passed, 11 skipped；唯一失败为既有 S8 |

## 备注

- 本 hotfix 不修改 trusted/container tier、配置面、依赖解析逻辑或任务级文件授权语义。
