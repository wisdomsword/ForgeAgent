---
comet_change: startup-information
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-23-startup-information
status: final
---

# Startup-Information Technical Design

## 1. 设计目标

为 ForgeAgent REPL 提供安静、可预测的启动体验，同时不改变任务执行、MCP 工具调用、HTTP 服务或配置格式。需求真源是 `openspec/changes/startup-information/`；本文只定义实现结构和验证策略。

## 2. 启动编排

`repl()` 在完成 reader 选择后计算一次：

```python
interactive = console.is_terminal and sys.stdin.isatty()
```

仅 `interactive` 为真时创建 `_StartupDisplay`。启动序列为：

1. 启动 transient Live 动画。
2. 执行 registry/context 校验、identity、memory、skills 和 MCP 初始化。
3. 任何需要用户输入的 confirmer 先 pause display，输入结束后 resume。
4. MCP required 失败：清理动画，由 `main()` 向 stderr console 输出固定错误并返回 2。
5. 成功或只有 optional 失败：停止动画，打印稳定 Logo、单行摘要和至多一条 optional MCP 提示。
6. 进入 REPL prompt。

`_StartupDisplay` 是 `cli.py` 私有类，不成为跨模块 UI 框架。它持有 `Console`、当前阶段文本和可空 `Live`。`Live` 使用 `get_renderable`，每次刷新根据 `time.monotonic()` 选择七色调色板的相位，刷新率固定为 8 FPS。`stop()` 幂等，所有启动路径用 `try/finally` 保证恢复 cursor。

确认适配器通过一个很小的私有 context manager 包住既有 reader 调用；pause 后不保留 Live 实例，resume 创建新实例，避免依赖 Rich 对同一 Live 重启的内部状态。

## 3. Logo 与降级

Logo 源码是 ASCII 字符串常量，不读取外部资源。宽度足够时使用多行 `ForgeAgent` 字标；不足时使用单行 `ForgeAgent`。颜色调色板依次为 red、yellow、green、cyan、blue、magenta、bright_magenta；整段字标每帧取调色板中的一种颜色，按 `int(time.monotonic() * 8) % len(palette)` 随时间以 8 FPS 依次循环，形成连续七色变化。

以下条件只输出稳定、无动画的必要内容或完全不输出启动 UI：

- 非 TTY；
- `TERM=dumb`；
- 存在 `NO_COLOR`；
- CI 环境；
- `run`、`serve`、`models`、`smoke` 子命令。

本 change 不增加命令行开关或配置项。

## 4. MCP stderr 捕获

### 4.1 `_BoundedStderrCapture`

`mcp_manager.py` 增加私有 context manager：

- `os.pipe()` 创建每 server generation 独立管道；
- 写端包装为文本流并传给 `stdio_client(params, errlog=capture.stream)`；
- daemon reader thread 从读端持续读取 bytes；
- 只将前 `8192` bytes 保存到受锁保护的 `bytearray`，以后继续读取但丢弃；
- 超限设置 `truncated=True`；
- 关闭时先关闭父进程写端，再等待 reader 看到 EOF，最后关闭读端；
- `text()` 使用 UTF-8 replacement 解码并返回内存快照。

选择 pipe 而非 `StringIO` 是 SDK 约束：`anyio.open_process` 要求 stderr 对象具有 `fileno()`。选择持续排空是为了防止子进程在 pipe 缓冲区写满后阻塞。捕获对象属于 holder generation，不存入全局日志。

### 4.2 发布规则

`_holder()` 为每次 generation 创建 capture。session 可用时丢弃捕获内容并发布 available。异常时：

1. 仅在 `_holder_slot_matches(...)` 且 manager 未 closing 时处理；
2. 对捕获文本执行 `mask_secrets`；
3. `_classify_startup_failure()` 将内容映射为固定类别；
4. 写入该 generation 对应的结构化诊断；
5. 清空捕获缓冲，不保留原始文本。

分类首期只有少量确定模式：Docker daemon/socket 连接失败映射为 `docker_unavailable`；connect timeout 映射为 `timeout`；其余映射为 `startup_failed`。公开文本来自常量表，不拼接原始 stderr 或异常字符串。

## 5. 诊断模型

新增冻结 dataclass `MCPServerDiagnostic`：

```python
@dataclass(frozen=True)
class MCPServerDiagnostic:
    name: str
    enabled: bool
    required: bool
    status: str
    tool_count: int
    reason: str | None
    impact: str | None
    action: str | None
```

`_ServerState` 仅增加 `diagnostic_code: str | None`；显示文案不存进状态。`MCPManager.diagnostics()` 在 facade 线程生成脱敏、不可变 tuple。禁用服务也在 `/mcp` 详情中出现，但启动摘要分母只统计 enabled 服务。

`server_status()` 保持现有返回结构和固定状态语义；`required_failures()` 继续只选择 enabled + required + unavailable。新诊断 API 不参与 tool routing。

启动摘要由 CLI 从 `diagnostics()` 计算：

```text
Ready | MCP 1/2 | model claude-sonnet-5 | sandbox restricted
```

optional 失败另输出一行：

```text
MCP github unavailable: Docker is not running; GitHub tools are disabled. Start Docker to enable them. Details: /mcp
```

文案说明能力降级，不把 Docker 描述为 ForgeAgent 默认依赖。

## 6. CLI 输出边界

`build_mcp_manager()` 签名移除 `console`，只装配、连接、required 检查和 cleanup。REPL 调用方负责交互展示；`run` 和 `serve` 不打印 MCP 启动状态。

`main()` 创建 stdout console 和 stderr console。配置、container、MCP、identity、HTTP 启动错误写 stderr；任务正常结果仍使用 stdout。这样 `printf 'quit\n' | forgeagent ...` 可以严格达到两路 0 bytes，而 required 启动失败仍可脚本化观察。

`repl()` 不再无条件打印旧 banner。真实交互 REPL 的稳定 Logo 后保留一行简短操作提示；非 TTY 不打印 Logo、banner、MCP 摘要或 prompt。Python `input(prompt)` 会把 prompt 写到 stdout，因此非 TTY reader 使用不带 prompt 的读取路径。

## 7. `/mcp`

保留 `/mcp status|tools|enable|disable` 兼容行为，并让裸 `/mcp` 输出诊断详情。每个服务最多固定五行：状态、工具数、原因、影响、建议。字段来自 `MCPServerDiagnostic`；不存在可公开详情时省略，不回退到原始异常。

enable/restart 产生新 generation 时先清空旧 `diagnostic_code`。旧 holder 的异常或 reader 完成只能在 generation slot 仍匹配时发布，避免覆盖新状态。

## 8. 测试策略

### MCP 单元测试

- `stdio_client` 收到不同 generation 的独立 `errlog`；
- 小量、超过 8 KiB 和非 UTF-8 stderr；
- 超限后仍持续排空，不死锁；
- 成功时不保留文本；Docker/unknown/timeout 分类；
- secret、命令、路径、异常文本不进入 diagnostics；
- disable/re-enable 和旧 generation 竞争不覆盖新诊断；
- cancel、close、required cleanup 后无 reader thread/holder 泄漏。

### CLI 单元测试

- 真实 TTY 才启动动画；七色帧、8 FPS、窄宽度和 no-color 降级；
- confirmer 前 pause、之后 resume，异常与 Ctrl-C 必清理；
- 分母排除 disabled；required 在摘要前失败；optional 只一行；
- `/mcp` 固定字段与敏感内容负断言；
- `build_mcp_manager()` 不再打印。

### 黑盒测试

- `printf 'quit\n' | forgeagent ...`：exit 0，stdout/stderr 都是 0 bytes；
- 管道目标：MCP 仍初始化，只输出任务结果；
- optional Docker 故障不泄漏 SDK/Docker 原文；
- required 故障：exit 2，仅 stderr 固定诊断；
- 人类 TTY smoke：动画可见、无残影、prompt 不重叠、退出恢复光标。

## 9. 实施顺序

1. 先写并运行 capture 可行性与边界测试。
2. 实现 capture、分类和 diagnostics 投影。
3. 写 renderer 生命周期测试，再实现启动展示。
4. 拆除 `build_mcp_manager()` 打印并修复非 TTY reader/output。
5. 扩展 `/mcp`，补黑盒脚本和文档。
6. 运行定向测试、全量 pytest、ruff、mypy、package build 和人类 TTY smoke。

## 10. 范围与工作区保护

不修改 `ACTION_PLAN.md`、`scripts/m16-filewrite-allowlist-blackbox.sh`、`.agent/`、`.agents/`、`.claude/commands/`、`.claude/rules/`、`.claude/skills/`、`.codex/`、`.superpowers/brainstorm/`、`skills-lock.json`、`work/`、`何为Harness.html`。这些是 change 开始前已存在的修改或未跟踪路径。

不新增依赖、配置面、持久日志、`/doctor` 或 HTTP 启动输出。

## 11. 双重自审

第一次按 canonical specs 逐条追踪：所有 MUST 都映射到组件和测试，disabled 分母、required 失败顺序、非 TTY 既有 bug 修复均明确。

第二次按并发、资源和安全审查：`StringIO` 不可行已由实验确认；pipe 持续排空、8 KiB 上限、generation 发布门、Live finally 清理、stderr/stdout 分离均闭环。结论：采用本设计进入实现计划，无需拆分 change 或新增依赖。
