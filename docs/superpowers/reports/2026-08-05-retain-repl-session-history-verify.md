---
comet_change: retain-repl-session-history
phase: verify
language: zh-CN
---

# retain-repl-session-history 验证报告

## 总结

| 维度 | 结果 |
| --- | --- |
| 完整性 | 11/11 tasks，3/3 能力规格场景组已实现 |
| 正确性 | 会话配对、重置、协作公开投影、Task 授权隔离均有实现和回归测试 |
| 一致性 | 遵循 design.md：每个顶层输入创建新 Task，system/runtime authority 每轮刷新，transcript 仅作上下文 |

## 验证证据

- `rtk uv --cache-dir /tmp/forgeagent-verify1-final-cache run pytest tests/test_step.py tests/test_task.py tests/test_context.py tests/test_cli.py tests/test_collaboration_integrations.py tests/test_http_server.py tests/test_http_task_service.py -q`：736 passed，10 skipped。
- `rtk uv --cache-dir /tmp/forgeagent-verify1d-uv-cache run pytest tests/test_cli.py -q`：343 passed；新增回归断言确认 reset 保留 model、tier、Memory、MCP 和累计 usage 对象。
- `rtk uv --cache-dir /tmp/forgeagent-verify1-uv-cache run ruff check src tests`：通过。
- `rtk openspec validate retain-repl-session-history --strict`：通过。
- `rtk git diff --check e742b35708d65c56c78ee26e88de7c3b0b13faa2...HEAD`：通过。
- 受控真实 `repl()` smoke 已验证第二个任务收到 `SYSTEM, USER, ASSISTANT, USER`，`/reset` 后下一请求恢复为 `SYSTEM, USER`。
- 完整测试的首次运行受 sandbox loopback、审计文件和构建缓存权限影响；同一失败组在授权环境重跑为 16 passed。该环境限制已记录在 Task 4 报告中。

## 对照结论

- `Task.run(session_messages=...)` 总是重新构造 system prompt 和 Runtime Authority，并拒绝非法/不完整的历史。
- REPL 普通、Single、Duo、Triad 任务只在任务输入完成后更新 transcript；管理命令不污染上下文。
- Duo/Triad 只投影用户可见、脱敏、有界报告，不带 planner/evaluator 私有内容。
- `/new` 和 `/reset` 清空 transcript 与暂存图片，不创建 Task、不调用 provider，保留模型、sandbox、Memory、MCP、输入历史和 usage。
- `TaskOutcome.session_messages` 不进入 model dump 或 HTTP 公共结果；历史文本不能恢复下一 Task 的文件系统授权。
- sliding window 保留 system、首个 user 和最新完整 assistant/user 单元，不拆分 ToolCall/feedback，不原地修改真实 conversation。

## 问题与风险

未发现 CRITICAL 或 IMPORTANT 问题。审查员提出的 reset 状态测试缺口已由 `9e4a427` 补齐。`mypy` 在环境中未安装，原有 `tests/test_task.py` 有 8 行基线格式问题；两者均未由本 change 引入。完整 TTY smoke 需要项目外审计文件写权限，受控进程内 smoke 已覆盖相同会话顺序和 reset 语义。

## 收尾决策

两轮自审均判断变更满足规格且没有需要回退到 build 的问题。按用户的持续授权，保留当前功能分支，不合并、不推送、不删除工作区。
