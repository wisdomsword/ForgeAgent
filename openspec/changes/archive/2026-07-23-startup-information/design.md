## Context

M19 已归档，当前 REPL 启动链路仍由 `cli.repl()`、`build_mcp_manager()` 和 `MCPManager._holder()` 共同完成。`repl()` 无条件输出 banner 和 `forge>` prompt；`build_mcp_manager()` 直接逐项打印 `server_status()`；`_holder()` 调用 `stdio_client(params)` 时没有传 `errlog`，而当前 MCP SDK 的默认参数是 `errlog=sys.stderr`，因此每个 stdio 子进程的 stderr 直通 ForgeAgent 进程。该路径在交互式和管道模式都生效。

本 change 必须保留 M19 的 prompt-toolkit reader、MCP required/optional 语义、secret masking、确认门、sandbox、HTTP 生命周期和任务结果形状。现有工作区还有不属于本 change 的未提交内容，具体为：`ACTION_PLAN.md`、`scripts/m16-filewrite-allowlist-blackbox.sh`、`.agent/`、`.agents/`、`.claude/commands/`、`.claude/rules/`、`.claude/skills/`、`.codex/`、`.superpowers/brainstorm/`、`skills-lock.json`、`work/`、`何为Harness.html`。实现和 diff review 必须将其排除。

## Goals / Non-Goals

**Goals:**

- 为真实交互式 REPL 提供纯 ASCII Logo、初始化反馈、模型/sandbox/项目/MCP 摘要。
- 在初始化期间提供低频七色动画，并在就绪或失败时确定性结束；确认输入期间暂停。
- 新增 per-server、generation-local、有界内存 stderr sink，接管 MCP SDK 的 `errlog` 参数。
- 对 MCP stderr 和异常实现 secret masking + 固定原因分类；未知原因不猜测、不展示原文。
- 将 `/mcp status` 扩展为可操作的状态、工具数、Reason / Impact / Action 展示。
- 让 stdin 或 stdout 任一非 TTY 的 REPL 路径无 banner、无 Logo、无启动摘要、无交互 prompt，同时保留任务结果和既有 EOF/空行/确认/Survey 语义。
- 明确定义启动摘要分母：当前配置快照中 `enabled: true` 的服务数；disabled 服务不计入。available 服务数为分子。required 服务只有在成功时计入；required 失败在摘要前整体阻断。

**Non-Goals:**

- 不新增 `/doctor`、`--no-banner`、持久化诊断日志、远程 MCP 管理、权限能力或 sandbox 档位。
- 不改变 MCP 工具发现/路由、required/optional 关键语义、确认门、HTTP API 或任务结果结构。
- 不在 `run`、`serve`、CI 或非 TTY 路径显示 Logo/ANSI 动画。
- 不引入新的运行时依赖；复用 Rich、prompt-toolkit 和 MCP SDK。

## Decisions

### 1. 把启动呈现从连接逻辑中分离

`build_mcp_manager()` 不再负责面向用户的逐项打印，只负责加载配置、连接、required 失败阻断并返回 manager。REPL/CLI 调用方根据统一的 `interactive = console.is_terminal and sys.stdin.isatty()` 判定，决定是否启动启动呈现器和最终摘要。HTTP/serve 与非 TTY 调用不产生启动 UI；required 错误由专用 stderr 输出路径写出。

备选方案是继续在 `build_mcp_manager()` 内打印并增加 `quiet` 参数。该方案会让 HTTP、REPL、单次命令各自维护输出规则，容易重新产生 banner/status 泄漏，因此不采用。

### 2. 使用私有、可暂停的 Rich 启动呈现器

在 `cli.py` 内实现最小私有 `StartupRenderer` 生命周期对象，不新建公共模块或依赖。它持有纯 ASCII Logo、七色调色板（red/yellow/green/cyan/blue/magenta/white）和有限刷新状态；交互式初始化期间以不超过 8 FPS 更新 `Live`，成功/异常/`KeyboardInterrupt` 都在 `finally` 停止并恢复终端。需要身份或 Skill trust 确认时先 `pause()`，确认结束后再 `resume()`。

终端宽度不足时使用单行 `ForgeAgent` 字标；`NO_COLOR` 或 Rich 无颜色终端使用静态单色字标；stdin/stdout 非 TTY、`TERM=dumb`、CI、`run`、`serve` 不创建 renderer。动画不引入额外等待，初始化工作仍在现有调用路径执行。

### 3. 每个 MCP holder 接管自己的 stderr

在 `mcp_manager.py` 增加私有有界文本 sink（最大字节数固定、超过后只记录截断标记），每个 server/generation 在 `_holder()` 内创建并通过 `stdio_client(params, errlog=sink)` 传入。成功 holder 释放 sink 内容，不向宿主输出；失败 holder 只把 masked、截断后的内存文本交给确定性分类器。

分类顺序固定为：已知 Docker daemon 不可用 → `runtime_unavailable`；可执行文件不存在 → `executable_not_found`；权限拒绝 → `permission_denied`；握手/连接超时 → `startup_timeout`；进程提前退出 → `process_exited`；其他 → `startup_failed`。分类器只输出固定用户文案，不输出命令、参数、环境、路径、原始 stderr 或 Python 异常类型；敏感值先 masking，再参与分类。每次 generation 独立保存诊断，旧 generation 不能覆盖新 generation。

备选方案是继续让 SDK 使用默认 `sys.stderr`，并在 CLI 外层重定向全局 stderr。该方案无法按 server 隔离、会吞掉模型/宿主错误，也无法安全支持并发 holder，因此不采用。

### 4. 保持兼容的 MCP 状态接口，新增诊断投影

保留 `server_status()` 的现有字符串状态，避免破坏 Tool/CLI 测试和内部调用；新增仅供 CLI 使用的 masked diagnostic projection，包含 public server label、status、tool count、固定 reason、impact 和 action。`/mcp status` 先打印状态和工具数，再对 unavailable server 打印缩进的三行诊断。启用/禁用仍沿用现有 `_handle_mcp_command()`，不把 Docker 启动动作自动化。

启动摘要使用连接前快照中的 enabled 服务集合：`available / enabled`。disabled 服务不进入分母、不触发 optional warning；required 失败在摘要生成前按既有语义抛出并关闭 manager。

### 5. 非 TTY 输出是结果导向的显式契约

`repl()` 只在 `interactive` 为真时打印 Logo、启动摘要和 `forge›` prompt。默认 reader 在非 TTY 下仍按普通输入读取；传入显式 `read_line` 的测试/嵌入方不创建 prompt-toolkit 会话。管道任务仍可连接并使用 MCP，但启动阶段不打印可选服务状态；仅输入 `quit` 时不产生任何 stdout/stderr。任务本身的既有结果渲染保持不变。

备选方案是仅隐藏 Logo，保留已有 banner/prompt。实际管道基线已经证明这仍会污染机器输出，并把 zsh prompt 粘在 `forge> ` 后面，因此不采用。

### 6. 测试分层

- `tests/test_mcp_manager.py`：sink 字节上限、errlog 注入、成功 chatter 丢弃、失败分类、secret masking、generation 隔离。
- `tests/test_cli.py`：interactive/non-TTY banner 分支、摘要计数、disabled 排除、`/mcp` Reason/Impact/Action、required stderr/non-zero、颜色与窄终端降级、renderer 异常清理。
- 新增 CLI 黑盒/子进程回归：`printf 'quit\\n' | ...` 的 stdout/stderr 均为空；管道任务只输出结果；MCP 子进程 stderr 不穿透。
- 保留既有 MCP resilience、Skills、golden 20/20 和 HTTP 回归；不修改 verified core 标准。

## Risks / Trade-offs

- **[动画与交互确认竞争]** Live 刷新可能干扰 trust/Survey 输入 → 所有确认入口前显式 pause，确认后 resume，并在 `finally` 强制 stop。
- **[MCP stderr 恶意膨胀]** 外部 server 可无限写 stderr → 每 generation 固定字节上限，超过只保留截断标记。
- **[诊断误分类]** stderr 文案可能随工具版本变化 → 仅对稳定模式做分类，其他一律 `startup_failed`，不猜测。
- **[非 TTY 兼容变化]** 旧脚本可能依赖 banner → 这是有意的结果导向修复，`run` 子命令不变；新增黑盒测试固定新契约。
- **[工作区归属混淆]** 既存 untracked/tooling 文件可能进入 diff → 实施前后按 proposal 列表核对 `git diff` 和 `git ls-files --others`，不覆盖、不格式化、不暂存这些路径。
- **[状态计数误读]** `server_status()` 包含 disabled entries → 摘要只使用 enabled snapshot，`/mcp` 仍可显示 disabled 的明确状态，但不计入启动分母。

## Migration Plan

无持久数据或配置格式迁移。现有 `mcp.yaml`、required/optional、MCP 工具路由和 sandbox 配置保持兼容。回滚只需回滚本 change 的代码与文档；旧行为会恢复为 banner、prompt 和 SDK stderr 直通，但不会修改用户配置。

## Open Questions

无用户级开放问题。动画刷新上限、stderr sink 上限、固定分类集合、enabled 分母和非 TTY 零启动输出已在本设计中固定；具体常量值必须在实现测试中以命名常量锁定并保持可审计。
