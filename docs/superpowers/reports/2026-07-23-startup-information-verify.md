---
change: startup-information
status: done_with_concerns
---

# Startup Information 验证报告

## 结论

Task 5 的文档、`/mcp` public-label 负向回归、G355 golden 对齐和验证记录已完成。受影响测试集、focused CLI/MCP 测试、完整 pytest、golden 20/20、Ruff、OpenSpec strict、发行包构建和 diff 检查均通过。真实 TTY smoke 由主会话执行，本任务未伪造结果。

## 变更范围

- `README.md`：说明真实 TTY 才显示 Logo/启动摘要；非 TTY 的 `printf 'quit\\n' | uv run forgeagent` 保持零启动字节；管道任务仍输出任务结果；Docker 仅是可选 MCP integration runtime；`/mcp` 诊断只显示固定字段。
- `docs/m7-tools-mcp-survey.md`：记录 per-server/per-generation 有界 stderr sink、generation 隔离和 raw child-error 不进入 public surfaces。
- `tests/test_cli.py`：新增 `test_mcp_diagnostic_uses_only_fixed_public_labels`，通过真实 manager capture 写入 Docker socket、异常类和 secret，确认 bare `/mcp` 只输出 `Status`、`Tools`、`Reason`、`Impact`、`Action` 及固定 Docker 原因。
- `tests/golden/cases.py`：G355 同时验证 bare `/mcp` 的固定诊断字段与 `/mcp status` 的工具清单，移除对旧 `available: available` 文本的断言。
- `tests/test_http_server.py`：两处 stale `build_mcp_manager(_console)` monkeypatch 对齐当前无参调用，测试语义不变。
- `docs/superpowers/reports/2026-07-23-startup-information-verify.md`：本报告。

## 自动化命令证据

| 命令 | 结果 |
| --- | --- |
| `uv run pytest tests/test_cli.py -q -k "mcp_diagnostic_uses_only_fixed_public_labels"` | `1 passed, 238 deselected`；首次 sandbox 读取 uv cache 被拒，升级权限后通过。 |
| `uv run pytest tests/test_cli.py -q -k "startup_summary or mcp_command"` | `14 passed, 225 deselected`。 |
| `uv run pytest tests/test_mcp_manager.py tests/test_cli.py tests/test_cli_startup_blackbox.py -q` | `455 passed, 1 skipped`。 |
| `uv run pytest tests/test_http_server.py -q -k "serve_real_client_uses_one_validated_registry_snapshot_for_tasks or serve_task_factory_passes_only_server_context_to_task"` | `2 passed, 64 deselected`。 |
| `uv run pytest -q` | `1486 passed, 11 skipped in 80.56s`。 |
| `uv run pytest tests/test_golden_runner.py -q`（G355 对齐后） | `78 passed in 29.55s`。 |
| `uv run python scripts/run_golden_core.py` | 失败：文件不存在（`can't open file .../scripts/run_golden_core.py`）。 |
| `uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-startup-information-golden` | 替代入口生成报告：`19/20 passed (95.0%)`；唯一失败 `G355 output lacks available status`。 |
| `uv run ruff check .` | `All checks passed!`。 |
| `uv run ruff format --check .` | `81 files already formatted`。 |
| `openspec validate startup-information --strict` | `Change 'startup-information' is valid`。 |
| `uv build --out-dir /tmp/forgeagent-startup-information-build` | 成功生成 `forgeagent-0.1.0.tar.gz` 和 `forgeagent-0.1.0-py3-none-any.whl`。 |
| `git diff --check` | 通过，无输出。 |
| `git status --short` | 本 change 允许路径：`README.md`、`docs/m7-tools-mcp-survey.md`、`tests/test_cli.py`、本报告；另有预存在的 `openspec/changes/startup-information/.comet/subagent-progress.md`，未修改且未纳入提交。 |

## 两轮自审

第一轮按三个 canonical spec 逐项对照 Task 1-4 证据：stderr sink 与 generation 发布隔离、required/optional 生命周期、注入 reader/non-TTY 零启动输出、TTY Logo 生命周期、实际 MCP enabled denominator、固定 `/mcp` 诊断字段均已有实现和 focused 回归；本 Task 5 只补最后的 public-label 负向断言与文档。

第二轮检查最终 diff：未发现 raw exception、child stderr、命令/参数/环境、secret 插值；未触碰 Rich markup、capture reader 生命周期、旧 generation 发布、disabled denominator、production code 或 pre-existing dirty path。先发现 G355 旧期望并以最小 fixture 级更新修复；完整 pytest 随后发现两个 HTTP 测试 monkeypatch 使用旧函数签名，按主会话授权做两处无参对齐。golden runner 与 full pytest 最终均全绿。

## 人工 TTY smoke

未在此子会话中伪造真实终端观察。主会话仍需使用真实 TTY 验证：可用/optional-failure 两种启动、动画暂停确认、Ctrl-C/quit 清理、`/mcp` 固定字段，以及 `printf 'quit\\n' | uv run forgeagent` 的 stdout/stderr 零字节。

## Dirty-path 审计

Global Constraints 要求本任务提交 `README.md`、`docs/m7-tools-mcp-survey.md`、`tests/test_cli.py`、`tests/golden/cases.py`、`tests/test_http_server.py`、本报告（brief 另列 OpenSpec tasks，但当前委派明确禁止修改 OpenSpec checkbox/progress）。`.comet/subagent-progress.md` 是预存在的未跟踪文件，未打开修改、未暂存、未提交。无 production、plan、milestone 或配置文件变更。
