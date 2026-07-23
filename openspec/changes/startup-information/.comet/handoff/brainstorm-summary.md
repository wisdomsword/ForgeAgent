# Brainstorm Summary

- Change: startup-information
- Date: 2026-07-23
- Language: zh-CN
- Decision: 采用方案 A；用户已授权由代理在两次自审后自行选择，无需再次阻塞确认。

## 确认的技术方案

- 交互 REPL 使用私有 `_StartupDisplay` 和 Rich `Live(get_renderable=...)`，按单调时钟以最多 8 FPS 渲染七色 ASCII Logo；确认提示前 pause，之后 resume，所有路径 finally 清理。
- `build_mcp_manager()` 只负责加载、连接、required 检查和 cleanup，不打印；真实 TTY 由 REPL 打印稳定 Logo/摘要，run/serve/non-TTY 不打印启动 UI。
- MCP 每个 server generation 使用独立 OS pipe 捕获 stderr。reader thread 持续排空，内存只保留前 8 KiB；成功即丢弃，失败只做脱敏和固定分类，绝不公开原始文本。
- 诊断通过不可变投影提供给 CLI：启动摘要分母为 enabled 配置服务，disabled 排除；required 失败在摘要前终止；optional 失败显示一行友好降级信息；`/mcp` 提供固定详情。
- 非 TTY `printf 'quit\n' | forgeagent ...` 要求 stdout/stderr 均为 0 bytes，任务管道仍保留结果输出。

## 关键取舍与风险

- `StringIO` 已实测不可用：SDK 需要 `fileno()`；OS pipe 是满足 SDK 和有界排空的最小实现。
- 不采用主线程动画 + 初始化工作线程，避免扩大现有线程、确认和异常传播边界。
- 不采用临时文件或全局 stderr 重定向，避免无界持久化或并发串扰。
- generation 发布门、pipe 关闭顺序和 Rich Live 清理是主要生命周期风险。

## 测试策略

- MCP：真实子进程 stderr、小量/超量/非 UTF-8、分类、脱敏、关闭取消和 generation 竞争。
- CLI：renderer 生命周期、TTY/no-color/窄宽度、摘要分母、required/optional、`/mcp` 和无打印装配。
- 黑盒：非 TTY quit 零输出、管道任务结果、Docker optional 故障不泄漏、required 故障 exit 2、人类 TTY smoke。

## Spec Patch

无。现有 OpenSpec delta 已覆盖本实现所需验收场景。
