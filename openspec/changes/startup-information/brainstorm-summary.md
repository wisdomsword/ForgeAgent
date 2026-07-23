# Startup-Information Brainstorm Summary

## 目标

把 REPL 启动过程从“原始子进程日志 + 分散状态行”改为面向用户的启动界面：真实交互终端显示七色动态 ASCII Logo 和一行摘要；非 TTY 保持可管道化；MCP 失败只展示固定、可操作的诊断，并把完整详情留给 `/mcp`。

## 已核实基线

- `repl()` 当前无条件打印两行 banner，非 TTY 并不干净；本 change 会修复这个既有行为。
- `build_mcp_manager()` 当前同时连接和打印每个服务状态，展示职责与资源装配耦合。
- `MCPManager._holder()` 调用 `stdio_client(params)`，SDK 默认把子进程 stderr 直通当前进程 `sys.stderr`；项目当前没有任何截获基础。
- SDK 最终调用 `anyio.open_process(..., stderr=errlog)`。实测 `io.StringIO` 因无 `fileno()` 失败，OS pipe 可正常捕获，因此不能用普通内存流假装实现。
- Rich `Live` 已提供刷新线程和 `get_renderable` 回调，可用单调时钟计算颜色帧，无需新增动画线程。

## 方案比较

### 方案 A：薄展示层 + generation 级有界 pipe 捕获（采用）

- `cli.py` 增加私有启动展示对象，只在真实交互 REPL 创建。
- 动画使用 `Live(get_renderable=..., refresh_per_second=8, transient=True)`；初始化结束后打印稳定 Logo 与摘要。
- `build_mcp_manager()` 只负责装配和连接，不打印。
- 每个 MCP holder generation 创建独立 OS pipe；后台读取端持续排空，内存只保留前 8 KiB，其余丢弃并标记截断。
- holder 成功时丢弃捕获文本；失败时立即脱敏、分类成固定诊断，再丢弃原文。
- `server_status()` 保持兼容，新增只读诊断快照供启动摘要和 `/mcp` 使用。

优点：边界清晰、满足硬上限、不阻塞高噪声子进程、复用现有依赖。代价：需要严谨处理 pipe、reader thread 和 generation 生命周期。

### 方案 B：主线程动画 + MCP 初始化工作线程（不采用）

把整个启动过程移到新工作线程，主线程绘制动画。这样会让 identity/skill 确认、异常传播和资源关闭跨线程，扩大现有线程模型，收益不抵复杂度。

### 方案 C：临时文件或全局 stderr 重定向（不采用）

临时文件不能提供可靠写入上限；全局 `redirect_stderr` 会串扰并发服务和进程其他日志。两者都不满足“按服务、按 generation、有界”的要求。

## 关键决策

1. 交互判定统一为 `console.is_terminal and sys.stdin.isatty()`；注入 reader 只服务测试，不把非 TTY 伪装成真实交互环境。
2. Logo 只含 ASCII 字符。终端宽度足够时显示多行字标，窄终端退化为单行 `ForgeAgent`；`NO_COLOR`、`TERM=dumb`、CI、`run`、`serve` 不启用动画。
3. 初始化动画最多 8 FPS。确认提示前停止并清除 Live，确认后重建 Live；所有退出路径在 `finally` 中清理并恢复光标。
4. MCP 摘要分母是配置快照中 `enabled: true` 的服务数；禁用服务不计入。分子是其中状态为 available 的服务数。required 失败在摘要前终止启动。
5. optional 失败只显示一行固定摘要；已知 Docker daemon 模式映射为 `Docker unavailable`，说明 MCP 能力降级和启动 Docker 的操作建议，不暗示 Docker 是默认必需项。
6. `/mcp` 展示每个已配置服务的状态、工具数、固定原因、影响和建议；不显示命令、参数、环境变量、路径、原始 stderr、异常文本或 Python 异常类型。
7. 非 TTY 的 `printf 'quit\n' | forgeagent ...` 必须 stdout/stderr 均为 0 bytes；管道输入任务仍正常初始化 MCP 并只输出任务结果。
8. 原始 stderr 的内存上限为每 generation 8 KiB。reader 在达到上限后继续排空并丢弃，避免子进程因 pipe 写满而死锁。
9. 旧 generation 的诊断发布必须通过既有 generation/holder slot 校验；重启后的旧 reader 不能覆盖新状态。
10. 不新增依赖、全局配置项、`/doctor`、持久日志或 HTTP 输出变化。

## 实现风险与验证

- pipe 关闭顺序错误可能导致 reader 泄漏或 holder 卡死：用真实子进程测试成功、超量 stderr、初始化失败、取消和关闭。
- Rich Live 与确认提示可能互相覆盖：对 pause/resume/finally 写生命周期测试，并做人类 TTY smoke test。
- 非 TTY 清洁输出可能被 prompt 或 identity/skill 诊断破坏：增加 subprocess 黑盒测试，同时覆盖 quit 和真实目标两条路径。
- 状态兼容性：保留 `server_status()` 和 required cleanup 的既有测试，新增诊断投影测试，不修改调用工具的公开行为。

## 双重自审结论

第一次审查从需求覆盖出发：Logo、摘要、非 TTY、optional/required、`/mcp`、有界捕获、generation 隔离均有明确落点。

第二次审查从失败与生命周期出发：排除了无 `fileno()` 的伪实现；补充持续排空、确认暂停、异常清理、旧 generation 防覆盖和 required 先失败后摘要的顺序约束。未发现需要扩大为第二个 change 的事项。
