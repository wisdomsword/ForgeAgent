# port-startup-logo-persistence 验证报告

日期：2026-08-04  
基线：`cc6472566cf13d5449b151f3047dcb8455db0d55`（main M47）  
分支：`codex/m48-port-startup-logo-persistence`

## 结论

| 维度 | 结果 | 证据 |
| --- | --- | --- |
| Completeness | PASS | `tasks.md` 4/4 完成；1 个 modified requirement 已实现 |
| Correctness | PASS | 3/3 delta spec scenarios 有实现与测试或真终端证据 |
| Coherence | PASS | 实现遵循 change design 与 M19 技术设计，无规格漂移 |

无 CRITICAL、WARNING 或 SUGGESTION 项。change 可进入分支处理与归档确认。

## 需求与场景映射

### 交互式启动展示产品标识

- `src/forgeagent/_cli_repl.py:157` 为 `StartupDisplay.stop()` 增加默认关闭的 `persist` 参数；只有存在活动 Live 时才会停止并按请求输出静态 Logo，实例标记保证至多输出一次。
- `src/forgeagent/_cli_repl.py:367` 仅在 MCP 初始化完成后的成功停止点传入 `persist=True`。确认暂停、异常清理和 `finally` 路径继续使用默认行为。
- `tests/test_cli.py:391` 验证成功启动后静态 Logo 恰好一次，且位于 `Ready | model mock` 摘要之前。
- `tests/test_cli.py:200` 验证确认暂停不会向终端记录静态 Logo，恢复后所有 Live 均停止。
- `tests/test_cli.py:416` 验证确认期间 `KeyboardInterrupt` 保留原控制流且所有 Live 均停止；既有启动异常测试验证失败路径清理。

### 真终端最终屏幕

使用实际 Rich `Live` 的临时程序 `/tmp/forgeagent-m48-logo-pty.py` 在 100x30 的 tmux PTY 中执行，随后通过 `tmux capture-pane` 读取最终屏幕。捕获结果只包含一份完整 ForgeAgent ASCII Logo，下一行是 `Ready | model mock`；不存在 `Loading identity`、`Connecting MCP services` 或残留刷新行。临时程序和 tmux 会话已在验证后删除。

## 设计一致性

- change design 的最小方案得到保持：`Live(transient=True)` 不变，`stop(*, persist=False)` 默认不改变旧调用方，只有成功点选择持久化。
- `docs/superpowers/specs/2026-07-23-startup-information-design.md:29` 已规定成功后打印稳定 Logo；本次移植恢复该设计在 M47 代码中的实现。
- 没有新增 change 专属 Superpowers Design Doc；这是 `workflow: tweak` 的已验证行为移植，OpenSpec `design.md` 是本 change 的实现设计。delta spec 与两份设计均无矛盾。
- README 只更新最终可见状态说明，并将 M19 历史验证报告明确限定为原始启动信息范围。

## 验证命令

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 全量测试 | `UV_CACHE_DIR=/tmp/forgeagent-m48-logo-uv-cache uv run pytest -q` | PASS：2782 passed, 11 skipped，155.22s |
| main 合并后全量测试 | `UV_CACHE_DIR=/tmp/forgeagent-m48-main-uv-cache uv run pytest -q` | PASS：2782 passed, 11 skipped，176.71s |
| 静态检查 | `UV_CACHE_DIR=/tmp/forgeagent-m48-logo-uv-cache uv run ruff check .` | PASS：All checks passed |
| 格式检查 | `UV_CACHE_DIR=/tmp/forgeagent-m48-logo-uv-cache uv run ruff format --check .` | PASS：147 files already formatted |
| OpenSpec | `openspec validate port-startup-logo-persistence --strict` | PASS |
| Diff whitespace | `git diff --check cc6472566cf13d5449b151f3047dcb8455db0d55...HEAD` | PASS |
| PTY 终态 | `tmux capture-pane -p -t forgeagent-m48-logo-verify -S -30` | PASS：单一稳定 Logo，摘要顺序正确，无刷新残留 |

全量 pytest 在 sandbox 外运行，因为既有 loopback socket 测试需要绑定本机端口；未访问外部网络。

## 审查与安全

- 提交区间产品行为只修改 `README.md`、`src/forgeagent/_cli_repl.py` 和 `tests/test_cli.py`；其余文件为本 change 的 OpenSpec/Comet 产物。
- 独立代码审查提出的 README 历史证据范围和 Logo/摘要顺序断言均已修正；最终差异未发现正确性、安全或边界问题。
- `review_mode: off` 因 tweak preset 跳过 verify 阶段自动审查；build 阶段已对同一最终产品 diff 完成独立审查。
- 没有新增依赖、配置、公共 API、文件系统写入、网络访问、密钥、外部命令或 unsafe 操作。
