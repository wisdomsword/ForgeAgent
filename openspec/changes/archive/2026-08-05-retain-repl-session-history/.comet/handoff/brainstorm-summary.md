# Brainstorm Summary

- Change: retain-repl-session-history
- Date: 2026-08-05

## 确认的技术方案

采用 REPL 持有结构化 `Message` transcript 的方案。每条顶层输入仍新建 Task；Task 使用本轮新 system prompt，加上不含 system 的历史和当前 user message。Step 暴露实际追加后的 conversation，TaskOutcome 通过排除序列化的内部字段把安全 transcript 返回给 REPL。Single 保留真实消息，Duo/Triad 读取相同外层历史但只把最终用户可见报告投影写回外层历史。

未采用复用 Task，因为它会复用 backend、task ID 和授权状态；未采用自然语言摘要，因为它破坏原生消息及工具调用配对，也会让 context policy 无法按真实轮次裁剪。

## 关键取舍与风险

- 每轮刷新 system prompt，避免 `/model`、`/reload` 后身份与 Runtime Authority 过期。
- 历史文本绝不初始化本轮授权；真实权限仍由新 Task 的宿主对象决定。
- Task 在 provider 无回复但产生终态时使用有界、宿主生成的 assistant 状态投影保持消息交替。
- 身份回答被宿主修复时，同步修复写入会话的最后 assistant 文本，避免显示与后续上下文不一致。
- 历史图片保留结构化内容；切换到不支持图片的模型时沿用能力校验并提示用户 `/new` 或 `/reset`，不静默丢图。

## 测试策略

先写失败测试，覆盖 Task history 输入输出、序列化排除、context 跨输入配对与裁剪、REPL 普通/Single/Duo/Triad 连续性、管理命令隔离、`/new`/`/reset`、图片清理、usage 保留，以及上一 Task 授权无法跨轮恢复。随后运行 Task/context/CLI/collaboration/HTTP 全量回归和多轮 REPL smoke。

## Spec Patch

无。OpenSpec delta spec 已覆盖会话连续、重置、协作安全投影和授权隔离。
