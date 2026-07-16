# hardening-core-correctness 验证报告

- 日期：2026-07-17
- OpenSpec change：`hardening-core-correctness`
- 计划基线：`44456c57e2ef76990f44846eadb83bc8d5e25166`
- 已验证实现：`6f347d3e0006de36dae9789f9cf2e4c126aff675`
- 合并前功能分支 HEAD：`fb49b79`
- 验证模式：`full`
- 结论：PASS

## 总览

| 维度 | 结果 | 证据 |
| --- | --- | --- |
| Completeness | PASS | OpenSpec tasks `45/45`；5 个 capability 的 requirement `30/30`、scenario `136/136` 均有实现与测试映射 |
| Correctness | PASS | 网络边界、工具确认与最小披露、两阶段完成、MCP 生命周期和黄金 runner 的专项与全量测试通过 |
| Coherence | PASS | proposal、OpenSpec design/delta specs、Superpowers Design Doc/plan、公开文档与当前实现未发现矛盾 |

## Capability 覆盖

| Capability | Requirements | Scenarios | 结果 |
| --- | ---: | ---: | --- |
| `completion-integrity` | 4/4 | 7/7 | PASS |
| `network-boundary-safety` | 5/5 | 16/16 | PASS |
| `tool-approval` | 7/7 | 36/36 | PASS |
| `mcp-resilience` | 8/8 | 59/59 | PASS |
| `golden-validation-core` | 6/6 | 18/18 | PASS |

## Fresh 验证证据

功能 worktree 最终 HEAD 上执行：

- `uv run ruff check src tests`：`All checks passed!`
- 相对 base-ref 的 26 个新增/修改 Python 文件：`ruff format --check` 全部通过。
- 全仓 format 诊断仍只有 8 个未被本 change 修改的历史文件，不属于本次阻塞项。
- 8 文件专项矩阵：`603 passed, 3 skipped in 16.94s`。
- 完整 pytest，且 `RuntimeWarning`、`PytestUnraisableExceptionWarning` 提升为失败：`886 passed, 13 skipped in 26.22s`。
- 离线黄金 runner：退出 `0`；JSON schema `forgeagent.golden.v1` 与 Markdown 报告一致，`20/20`、失败 `0`、`100.0%`。
- `openspec validate hardening-core-correctness --strict`、type-specific strict validation 和 `git diff --check` 均通过。

本地 fast-forward 合并到 `main` 后重新执行：

- `uv run ruff check src tests`：`All checks passed!`
- 完整 pytest及相同 warning gate：`886 passed, 13 skipped in 28.04s`。

13 个 skip 均有明确环境原因：10 个 Docker/image 能力、1 个明确标记的慢 MCP hang probe、1 个本地 socket bind 能力和 1 个外网能力。没有人工 deselect。

## 设计与安全核对

- `guarded_urlopen()` 显式使用 `ProxyHandler({})`，共享 301/302/303/307/308 路径按 10 跳限制、最终 HTTP(S) scheme 和逐跳 SSRF 校验处理；WebFetch/search 消费端收敛规定的协议异常。
- MCP/WebFetch/FileWrite 使用类型安全 confirmer；非 TTY 无确认通道时拒绝。URL、MCP identity/arguments 和文件路径按固定最小披露与单行 literal 规则渲染。
- 文件工具使用 canonical root containment；固定 outcome 避免宿主路径泄漏；文档明确保留 hostile symlink target/ancestor swap 的 TOCTOU 残余威胁。
- `completed: true` 仅在无工具、无解析错误的独立响应中生效；显式 `completed: false` terminal status 保持既有语义。
- MCP required/public identity、loop-owned generation holder、startup transaction、唯一 shutdown drain、absolute deadline、重复 close 和 nested cancellation 契约均有回归测试。
- 黄金 manifest 固定 20 个离线核心与 5 个 real opt-in；文档锁定 G01-G380 和其余 360 个候选。真实模型入口按 spec 未运行且不属于 CI 门禁。
- 本 change 未新增依赖、硬编码凭证或新厂商端点。

CodeGraph 查询报告索引来自主 checkout，故只用于调用面定位；未运行 `codegraph init`。最终判断使用当前 worktree 的直接源码、diff、专项测试和全量测试，确认 WebFetch/search、run/REPL/Task/Step、MCP CLI 与 golden runner/pytest 调用方均覆盖。

## 独立评审

- 技术一致性 reviewer `Galileo`：APPROVED，无 Critical/Important。
- Whole-branch reviewer `Euclid`：最终 APPROVED；其唯一 Important 测试活性问题已由 `6f347d3` 修复并复评。
- 验收证据 reviewer `Kuhn`：APPROVED；原始命令、计数、skip、HEAD、黄金报告和任务状态一致。
- Verify reviewer `Dalton`：无 Critical/Important/Warning/Suggestion；Completeness、Correctness、Coherence 均 PASS。

## 分支处理与残余项

- 用户选择本地合并；`main` 从 `d1f6af1` fast-forward 到功能分支 `fb49b79`。仓库未配置 remote/upstream，因此没有可执行的 `git pull`。
- 用户未提交的 `ACTION_PLAN.md` M11/M12 内容已与 M13 合并结果一起恢复，SHA-256 为 `64ab3ca0b0b12e341233332481a5c83189d840f9bdf5b3a1ee0a8ed741bc5a15`，保持未暂存。
- 主检出原有未跟踪文件未修改、未暂存、未提交。
- 已记录的非阻塞项保持不变：README 旧 literal API-key 表述债务、完全 hard-stuck Python thread 无安全强杀、5 项真实模型未运行、8 个非本 change 的历史 format 差异。

## 最终评估

所有完整验证门禁通过，无需接受偏差。该 change 可以进入 Comet archive 阶段。
