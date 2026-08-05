# Context 限额与执行指引验证报告

## 结论

实现通过专项行为验证，环境相关失败已被隔离。最终两轮审查未发现需要继续修改的产品代码问题。

## 证据

- 专项回归：context、CLI、identity、protocol、Task、HTTP 共
  `742 passed, 10 skipped`。
- 完整测试在受限沙箱中为 `2953 passed, 23 skipped, 15 failed`。失败均来自
  loopback 绑定、审计临时文件权限或 `uv build` 权限；对应测试提升权限后为
  `52 passed in 27.02s`。
- `ruff check src tests scripts`：通过。
- `ruff format --check src tests scripts`：只报告 `tests/test_task.py` 的既有格式基线；
  相对第二个 change 基线 `b2716e2`，本里程碑没有修改对应旧断言。
- `mypy src`：当前环境未安装，原始错误为 `Failed to spawn: mypy`。
- `openspec validate improve-context-limits-and-execution-guidance --strict`：通过。
- 真实模型、项目内注入审计的 REPL smoke：`repl-finished=true`、报告存在、包含
  `Exec` 执行证据；报告记录扫描 4 个文件、1 组重复、2 个重复文件。第二条输入在
  同一 REPL session 中继续，审计工具记录只有 `Exec`。默认 TTY 命令在模型执行前
  被权限门阻止，因为默认审计路径 `~/.forgeagent/audit.jsonl` 需要单独的项目外写入授权。

### 提升权限补充验证（2026-08-06）

- 完整 pytest：`2980 passed, 11 skipped in 159.20s`。
- `uv build`：source distribution 与 wheel 均成功生成。
- 受限沙箱中的 15 条失败保持原样作为环境边界记录；提升权限后的完整结果证明它们不是产品回归。

## 审查

两轮审查确认：resolver 保持原公式和校验语义；REPL 限额只在交互边界显示，不包含
secret，并关闭注入 probe；候选模型或 reload 失败时保留旧状态；固定协议保留全部
ToolCall schema、runtime API、sandbox 权威和诚实终态规则，同时新增 Survey、Exec 与
完整文件交付路由。diff 仅包含计划中的源码、测试及 Comet/OpenSpec 工件。

外部配置复查确认：两条授权目标行均已消失，权限仍为 `0600`，
`load_context_config` 返回自适应默认值。修改前的 filtered digest 与修改后的 digest
不一致；换行、行数、文件尾换行和尾随空白检查未发现畸形，但修改后无法证明每个
非目标字节均与修改前完全一致。该项作为明确残余风险保留，不冒充已验证。
