---
change: startup-information
status: done_with_concerns
---

# Startup Information 验证报告

## 结论

Task 5 的文档、`/mcp` public-label 负向回归、G355 golden 对齐、最终 MCP 修复、两轮 whole-change review 和验证记录已完成。此前报告中的 golden `19/20` 是 G355 期望修复前的历史结果，不能作为最终通过证据；最终使用全新输出目录实际运行 runner，得到 `20/20 passed (100.0%)`。真实 TTY smoke 已由主会话完成，剩余未覆盖项只限报告中明确列出的可选人工分支。

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
| `UV_CACHE_DIR=/tmp/forgeagent-startup-information-uv-cache uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-startup-information-golden-final2`（最终修复后） | `0`；`report.md` 显示 `Summary: 20/20 passed (100.0%)`，G355 为 `PASS`。 |
| `UV_CACHE_DIR=/tmp/forgeagent-startup-information-uv-cache uv run python scripts/run_golden_core.py` | `2`；失败事实保留：`can't open file .../scripts/run_golden_core.py: [Errno 2] No such file or directory`。该脚本不存在，未将其当作通过。 |
| `UV_CACHE_DIR=/tmp/forgeagent-startup-information-uv-cache uv run python -m tests.golden.runner --help` | `0`；可用 runner 入口为 `python -m tests.golden.runner`，接受 `--real-model` 与 `--output-dir`。 |
| `uv run pytest tests/test_cli.py -q -k "mcp_diagnostic_uses_only_fixed_public_labels"` | `0`；`1 passed, 238 deselected`。首次 sandbox 读取 uv cache 被拒，升级权限后通过。 |
| `uv run pytest tests/test_cli.py -q -k "startup_summary or mcp_command"` | `0`；`14 passed, 225 deselected`。 |
| `uv run pytest tests/test_mcp_manager.py tests/test_cli.py tests/test_cli_startup_blackbox.py -q` | `0`；`455 passed, 1 skipped`。 |
| `uv run pytest tests/test_http_server.py -q -k "serve_real_client_uses_one_validated_registry_snapshot_for_tasks or serve_task_factory_passes_only_server_context_to_task"` | `0`；`2 passed, 64 deselected`。 |
| `UV_CACHE_DIR=/tmp/forgeagent-startup-information-uv-cache uv run pytest -q` | `0`（允许 loopback/build 子进程的环境）；`1489 passed, 11 skipped in 71.72s`。受限 sandbox 的首次运行另有 12 个环境型失败（11 个 loopback allocation、1 个子进程 `uv build`），不属于本 change 断言；在允许网络/loopback 的环境重跑通过。 |
| `uv run pytest tests/test_golden_runner.py -q`（G355 对齐后） | `0`；`78 passed in 29.55s`。 |
| `UV_CACHE_DIR=/tmp/forgeagent-startup-information-uv-cache uv run pytest -q`（最终修复后） | `0`；`1489 passed, 11 skipped in 71.72s`。 |
| `uv run pytest -q tests/test_mcp_manager.py`（最终修复独立复审） | `0`；`187 passed, 1 skipped`。 |
| `uv run ruff check src/forgeagent/mcp_manager.py tests/test_mcp_manager.py` / `uv run ruff format --check src/forgeagent/mcp_manager.py tests/test_mcp_manager.py` | `0`；均通过。 |
| `uv run ruff check .` | `0`；`All checks passed!`。 |
| `uv run ruff format --check .` | `0`；`81 files already formatted`。 |
| `openspec validate startup-information --strict` | `0`；`Change 'startup-information' is valid`。 |
| `uv build --out-dir /tmp/forgeagent-startup-information-build` | `0`；生成 `forgeagent-0.1.0.tar.gz` 与 `forgeagent-0.1.0-py3-none-any.whl`。 |
| `UV_CACHE_DIR=/tmp/forgeagent-startup-information-uv-cache uv build --out-dir /tmp/forgeagent-startup-information-build-final` | 首次受限 sandbox 因 DNS 无法解析 `hatchling`（exit `2`）；获得网络权限后重跑 `0`，生成 `forgeagent-0.1.0.tar.gz` 与 `forgeagent-0.1.0-py3-none-any.whl`。 |
| `git diff --check` | `0`；无输出。 |
| `openspec status --change startup-information --json` | `isComplete: true`；proposal/design/specs/tasks 均为 `done`。CLI 没有独立 `openspec verify` 子命令，已用 `openspec validate startup-information --strict` 完成严格校验。 |

此前的 `uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-startup-information-golden` 得到 `19/20`，唯一失败是 `G355 output lacks available status`。它是修复前工件，已由上述新目录 `20/20` 结果取代，不作为最终验证结论。

## 两轮自审

第一轮按三个 canonical spec 对照 Task 1-4 证据：stderr sink 与 generation 发布隔离、required/optional 生命周期、注入 reader/non-TTY 零启动输出、TTY Logo 生命周期、实际 MCP enabled denominator、固定 `/mcp` 诊断字段均已有实现和 focused 回归；本 Task 5 只补最后的 public-label 负向断言与文档。

第二轮检查最终 diff：未发现 raw exception、child stderr、命令/参数/环境、secret 插值；未触碰 Rich markup、旧 generation 发布、disabled denominator 或 pre-existing dirty path。发现 `_BoundedStderrCapture.close()` 对继承写端无界等待，以及运行时 holder/call failure 缺少固定诊断投影；新增回归并修复为有界 join、跨平台 blocking pipe reader 和 `startup_failed` public diagnostic。复审还发现 README 把颜色降级与非 TTY prompt 抑制混为一谈，现已明确动画/静态标识与 `forge> ` 的独立条件；同时以新输出目录的实际 golden `20/20` 结果替换旧的最终通过主张。

最终独立代码评审（覆盖整个 change）确认：generation ownership、public diagnostic masking、enabled-only denominator、非 TTY 零输出和 Rich markup 隔离均无阻塞问题；修复后的 stderr reader 在 Windows 使用 blocking pipe-compatible `os.read()`，close 只做有界 join，重复 writer 回归明确 reader 可延迟退出。

## 人工 TTY smoke

主会话使用真实 PTY 完成了 optional-failure 启动与 `quit` 清理：

- `TERM=dumb` 的 TTY 不显示 Logo 或动画，随后显示 `Ready | MCP 0/2`、固定字段的 filesystem/Docker 降级摘要和 `forge> `；输入 `quit` 后退出状态为 `0`。
- `TERM=xterm-256color` 且设置 `NO_COLOR=1` 时显示一次静态 ASCII 标识；同样的终端未设置 `NO_COLOR` 时观察到 ANSI 七色动态 Logo 帧。两种模式均显示摘要和提示符，输入 `quit` 后退出状态为 `0`。
- 使用 `tests/mcp_fixture_server.py` 的 normal 模式与隔离 HOME 启动时，摘要显示 `MCP 1/1`；bare `/mcp` 显示 `fixture`、`Status: available`、`Tools: 2`，随后 `quit` 退出状态为 `0`。
- 在临时项目放置 `.forgeagent/AGENTS.md` 后，动态 Logo 在 `trust project identity` 确认出现前停止刷新；回答 `n` 后动画从 `Loading identity` 恢复到 `Connecting MCP services`，未与输入提示重叠。
- 在完成启动后的 `forge> ` 提示符发送 Ctrl-C，进程退出状态为 `0`，终端光标与 bracketed-paste 状态均由 prompt-toolkit/Rich 清理序列恢复，无后台刷新残留。
- optional-failure smoke 使用配置中的 filesystem 与 github servers，因此 Docker 未运行只产生脱敏的固定摘要，不阻塞 REPL。管道零启动字节由自动化 black-box/golden 覆盖。

## Dirty-path 审计

Task 5 实际修改并提交了 `README.md`、`docs/m7-tools-mcp-survey.md`、本验证报告、`docs/superpowers/plans/2026-07-23-startup-information.md`、`openspec/changes/startup-information/tasks.md`、`tests/test_cli.py`、`tests/golden/cases.py` 和 `tests/test_http_server.py`；Task 1-4 的生产代码与测试属于同一 change 的既定范围。当前 worktree 的 `git status --short` 只有：

```text
?? openspec/changes/startup-information/.comet/subagent-progress.md
```

该 Comet 协调文件预先存在，未修改、未暂存、未提交。根 worktree 另有既存未提交路径（`.agent/`、`.agents/`、`.claude/commands/`、`.claude/rules/`、`.claude/skills/`、`.codex/`、`.superpowers/brainstorm/`、`skills-lock.json`、`work/`、`何为Harness.html`、`ACTION_PLAN.md`、`scripts/m16-filewrite-allowlist-blackbox.sh`），均不在本 change worktree，也未被纳入提交。
