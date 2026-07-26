# 发布完整性收尾复审验证报告

## 结论

PASS。本次完成后复审发现并修复 4 个问题：sdist 测试依赖 tar 成员顺序；README 当前验证合同可能漏过额外畸形同名标题；当前合同仍与 M22 历史收尾测试耦合；ACTION_PLAN 未记录 restricted worker bootstrap 与发布完整性收尾。第二轮复审又发现标题正则未覆盖缺少 Markdown 空格的 `##当前验证`，已一并修复。

## OpenSpec 完整验证

| 维度 | 结果 |
| --- | --- |
| Completeness | 6/6 tasks 完成；1/1 modified requirement 已实现 |
| Correctness | 3/3 scenarios 有自动化测试或真实构建证据 |
| Coherence | proposal、design、delta spec、测试、README 与 ACTION_PLAN 一致 |

- sdist 场景：`tests/test_packaging.py` 从全部 tar 成员推导唯一根目录，精确校验允许的顶层集合与必需根文件，并禁止 agent/workflow/OpenSpec/user-local 路径。
- 当前验证场景：`tests/test_collaboration_docs.py` 单独检查唯一 `当前验证` 标题、结构化数字和 OpenSpec pass/total 自洽，不固定易变数字。
- 畸形重复标题场景：标题计数允许标题与正文之间零个或多个空白，因此 `## 当前验证` 和 `##当前验证` 都进入唯一性检查。
- M22 历史证据：ACTION_PLAN 里程碑行、milestone 与历史报告中的 `2155 passed / 10 skipped` 未修改。

未发现 CRITICAL、WARNING 或 SUGGESTION 项。

## 最终门禁

| 检查 | 结果 |
| --- | --- |
| 完整 pytest | `2252 passed, 10 skipped in 85.32s` |
| 包装 + 文档专项 | `12 passed` |
| 文档合同复跑 | `9 passed` |
| 离线 golden | `20/20 passed (100.0%)` |
| Ruff check | `All checks passed!` |
| Ruff format | `105 files already formatted` |
| wheel/sdist build | wheel 与 sdist 均成功生成 |
| sdist 内容检查 | 仅 `.gitignore`、`PKG-INFO`、`README.md`、`pyproject.toml`、`src`、`uv.lock`；48 个相对成员 |
| active OpenSpec strict | `19 passed, 0 failed`（18 个主规格 + 当前 change） |
| Git diff check | PASS |

第一次在文件沙箱中运行全量 pytest 时，11 个 M16 blackbox 因 loopback bind 被拒绝而失败，输出为 `PermissionError: [Errno 1] Operation not permitted`；这是受限执行环境问题。使用已授权的测试权限复跑同一命令后得到上述 `2252/10`。第一次真实 build 的后置内容检查误用了不存在的 `rtk python`，build 本身已成功；随后用 `uv run python` 单独重跑内容检查并通过。

## 两轮自审

1. **边界与历史证据审查**：确认 sdist 测试不依赖 tar 排序，顶层集合等值约束可拒绝所有未列入发布边界的仓库根路径；README/ACTION_PLAN 只更新当前事实，历史 M22 数字保持不变；无新依赖、公共 API、运行时或发布文件集合变更。
2. **反向与畸形输入审查**：确认当前验证测试已从 M22 测试拆出，合法章节唯一且数字可变；发现 `##当前验证` 未被初版标题正则计数后，将空白量词从 `+` 改为 `*`，与 delta spec 的“畸形同名标题”场景一致。

## 剩余限制

- 当前仓库没有许可文件；本 change 不替项目做法律授权选择，也不伪造许可内容。
- Docker 相关 10 项测试仍因本机 Docker daemon/image 条件跳过；本次不扩展平台矩阵。
