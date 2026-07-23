---
change: startup-information
status: done_with_concerns
---

# Startup Information 验证报告

## 结论

Task 5 的文档、`/mcp` public-label 负向回归、G355 golden 对齐和验证记录已完成。此前报告中的 golden `19/20` 是 G355 期望修复前的历史结果，不能作为最终通过证据；本次复审后使用全新输出目录实际运行 runner，得到 `20/20 passed (100.0%)`。真实 TTY smoke 未在本子会话伪造，仍保留为人工验证限制。

## 文档契约

- `README.md` 将真实交互式 REPL 定义为默认 reader 且 stdin、stdout 都是 TTY。
- 动态彩色 Logo 仅在支持颜色且不处于 `CI`/`TERM=dumb` 等降级环境时显示；`NO_COLOR`、`console.no_color` 或无颜色系统停用动画和 ANSI 颜色，但在真实交互式 REPL 中仍显示一次静态单色标识。
- `CI`、`TERM=dumb` 与非 TTY 路径均不显示标识或动画；`run` 和 `serve` 不进入 REPL 启动界面。
- `forge> ` 的条件与动画/标识独立：默认 reader 加 stdin/stdout 双 TTY 即显示提示符，`CI`、`TERM=dumb`、`NO_COLOR` 本身不会抑制它；非 TTY 或显式注入 reader 使用空提示符。
- `printf 'quit\\n' | uv run forgeagent` 的 stdout、stderr 保持零启动字节，管道输入的实际任务结果仍可输出。
- Docker 只是已配置 MCP integration runtime 的可选依赖；bare `/mcp` 只显示固定的 `Status`、`Tools`、`Reason`、`Impact`、`Action` 字段，不回显 child stderr、命令、参数、环境、异常类型或 secret。

## 自动化命令证据

| 命令 | 退出状态与实际结果 |
| --- | --- |
| `UV_CACHE_DIR=/tmp/forgeagent-startup-information-uv-cache uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-startup-information-golden-final` | `0`；新目录 `report.md` 显示 `Summary: 20/20 passed (100.0%)`。G01、G03、G05、G06、G08、G11、G13、G14、G15、G17、G27、G43、G58、G59、G324、G329、G330、G332、G333、G355 均为 `PASS`；G355 详情为 `MCP slash output showed optional degradation and available tools`。 |
| `UV_CACHE_DIR=/tmp/forgeagent-startup-information-uv-cache uv run python scripts/run_golden_core.py` | `2`；失败事实保留：`can't open file .../scripts/run_golden_core.py: [Errno 2] No such file or directory`。该脚本不存在，未将其当作通过。 |
| `UV_CACHE_DIR=/tmp/forgeagent-startup-information-uv-cache uv run python -m tests.golden.runner --help` | `0`；可用 runner 入口为 `python -m tests.golden.runner`，接受 `--real-model` 与 `--output-dir`。 |
| `uv run pytest tests/test_cli.py -q -k "mcp_diagnostic_uses_only_fixed_public_labels"` | `0`；`1 passed, 238 deselected`。首次 sandbox 读取 uv cache 被拒，升级权限后通过。 |
| `uv run pytest tests/test_cli.py -q -k "startup_summary or mcp_command"` | `0`；`14 passed, 225 deselected`。 |
| `uv run pytest tests/test_mcp_manager.py tests/test_cli.py tests/test_cli_startup_blackbox.py -q` | `0`；`455 passed, 1 skipped`。 |
| `uv run pytest tests/test_http_server.py -q -k "serve_real_client_uses_one_validated_registry_snapshot_for_tasks or serve_task_factory_passes_only_server_context_to_task"` | `0`；`2 passed, 64 deselected`。 |
| `uv run pytest -q` | `0`；`1486 passed, 11 skipped in 80.56s`。 |
| `uv run pytest tests/test_golden_runner.py -q`（G355 对齐后） | `0`；`78 passed in 29.55s`。 |
| `uv run ruff check .` | `0`；`All checks passed!`。 |
| `uv run ruff format --check .` | `0`；`81 files already formatted`。 |
| `openspec validate startup-information --strict` | `0`；`Change 'startup-information' is valid`。 |
| `uv build --out-dir /tmp/forgeagent-startup-information-build` | `0`；生成 `forgeagent-0.1.0.tar.gz` 与 `forgeagent-0.1.0-py3-none-any.whl`。 |
| `git diff --check` | `0`；无输出。 |

此前的 `uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-startup-information-golden` 得到 `19/20`，唯一失败是 `G355 output lacks available status`。它是修复前工件，已由上述新目录 `20/20` 结果取代，不作为最终验证结论。

## 两轮自审

第一轮按三个 canonical spec 对照 Task 1-4 证据：stderr sink 与 generation 发布隔离、required/optional 生命周期、注入 reader/non-TTY 零启动输出、TTY Logo 生命周期、实际 MCP enabled denominator、固定 `/mcp` 诊断字段均已有实现和 focused 回归；本 Task 5 只补最后的 public-label 负向断言与文档。

第二轮检查最终 diff：未发现 raw exception、child stderr、命令/参数/环境、secret 插值；未触碰 Rich markup、capture reader 生命周期、旧 generation 发布、disabled denominator、production code 或 pre-existing dirty path。复审发现 README 把颜色降级与非 TTY prompt 抑制混为一谈，现已明确动画/静态标识与 `forge> ` 的独立条件；同时以新输出目录的实际 golden `20/20` 结果替换旧的最终通过主张。

## 人工 TTY smoke

未在此子会话中伪造真实终端观察。主会话仍需使用真实 TTY 验证：可用/optional-failure 两种启动、动态动画与静态单色降级标识、摘要、提示符、动画暂停确认、Ctrl-C/quit 清理、`/mcp` 固定字段，以及 `printf 'quit\\n' | uv run forgeagent` 的 stdout/stderr 零字节。

## Dirty-path 审计

本次复审只修改 `README.md` 与本报告。工作树中预存在的 `openspec/changes/startup-information/.comet/subagent-progress.md` 未修改、未暂存、未提交。未触碰生产代码、测试、plan、OpenSpec progress、配置或 milestone 文件。
