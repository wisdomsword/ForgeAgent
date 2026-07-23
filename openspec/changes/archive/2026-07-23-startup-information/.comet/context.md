# Comet Design Handoff

- Change: startup-information
- Phase: design
- Mode: compact
- Context hash: 6af606c3e46106024517c05dab0cdd2a758bf1b2808e0e25af1d05653cb9964d

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/startup-information/proposal.md

- Source: openspec/changes/startup-information/proposal.md
- Lines: 1-35
- SHA256: 76f55da6f0583fb45d3269d2ce5de7ee103aa7164cb69a12c13d3ddac83fe8ac

```md
## Why

ForgeAgent 当前在所有 REPL 启动路径无条件打印交互 banner、提示符和逐项 MCP 状态，MCP SDK 又因未传 `errlog` 而把每个 stdio 子进程的 stderr 直接写入主进程终端。这使 Docker daemon 错误、server chatter 和 `ExceptionGroup` 等内部信息看起来像 ForgeAgent 自身的默认依赖或故障，并污染管道输出。

本变更要让交互式启动具有清晰的产品身份与就绪反馈，同时让非交互输出保持安静、可组合，并在不削弱现有 MCP required/optional、secret masking、确认门或 sandbox 语义的前提下提供可操作的诊断。

## What Changes

- 为真实交互式 REPL 增加纯 ASCII ForgeAgent Logo：初始化期间使用 Rich 做低频七色动画，就绪后定格；确认提示期间暂停；窄终端、`NO_COLOR` 和无颜色终端确定性降级。
- 用一条紧凑状态区替代当前 banner、帮助和逐项 MCP 启动输出，展示模型、实际 sandbox、项目路径，以及按启动快照计算的 MCP `available/enabled` 摘要。
- 新增 per-server、有界、内存内的 MCP stdio `errlog` 接管。成功服务的 chatter 不再进入宿主 stderr；失败服务只暴露经过 secret masking 和有限分类的友好诊断，未知原因不得猜测。
- 增强现有 `/mcp` 状态输出，按服务展示状态、工具数，以及失败时的 Reason / Impact / Action；Docker 只在相应配置服务的诊断中出现，并明确不是默认 sandbox。
- 修复既有非 TTY 行为：当 stdin 或 stdout 不是 TTY 时，不打印 Logo、启动 banner、交互提示符或可选 MCP 状态；管道任务仍可使用已连接的 MCP，但输出只保留既有任务结果；仅输入 `quit` 时 stdout/stderr 均为空且退出码为 0。
- required MCP 失败继续在任务执行前整体阻断并完成有界清理；错误写入 stderr、退出非零，且不得泄漏原始子进程 stderr 或内部异常文本。
- 不新增 `/doctor`、`--no-banner`、第三方动画依赖、持久 stderr 日志、MCP 权限能力或 sandbox 配置。

## Capabilities

### New Capabilities

- `repl-startup-information`: 交互式 Logo、启动状态摘要、终端能力降级和安静的非交互启动输出。

### Modified Capabilities

- `repl-interactive-input`: 将“非 TTY 保持原有输出”改为明确的无 banner、无 prompt、结果导向输出契约，同时保留 EOF、`KeyboardInterrupt`、空行、确认与 Survey 语义。
- `mcp-resilience`: 增加全新的 per-server `errlog` 接管、有界诊断、摘要计数和友好 `/mcp` 展示要求，同时保持 optional 降级与 required 阻断语义。

## Impact

- 主要代码：`src/forgeagent/cli.py`、`src/forgeagent/mcp_manager.py`。
- 主要测试：`tests/test_cli.py`、`tests/test_mcp_manager.py`，以及必要的 CLI 黑盒/管道回归。
- 文档：README、MCP/CLI 使用说明和必要的安全边界说明。
- 依赖：复用现有 Rich、prompt-toolkit 和 MCP SDK，不新增运行时依赖。
- 兼容性：交互式 REPL 启动呈现会改变；`run`、`serve`、MCP 工具调用、确认门和任务结果结构不变。非 TTY REPL 从带交互噪声改为安静输出，是有意修复而非兼容承诺。
- 工作区隔离：以下既存未提交路径不属于本变更，后续实现、diff review 和提交必须排除：`ACTION_PLAN.md`、`scripts/m16-filewrite-allowlist-blackbox.sh`、`.agent/`、`.agents/`、`.claude/commands/`、`.claude/rules/`、`.claude/skills/`、`.codex/`、`.superpowers/brainstorm/`、`skills-lock.json`、`work/`、`何为Harness.html`。

```

## openspec/changes/startup-information/design.md

- Source: openspec/changes/startup-information/design.md
- Lines: 1-82
- SHA256: 8b9b94fb304d2d580a30d0cf0b5d705a0cfa9032806b74deb594cab431900e5e

[TRUNCATED]

```md
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

```

Full source: openspec/changes/startup-information/design.md

## openspec/changes/startup-information/tasks.md

- Source: openspec/changes/startup-information/tasks.md
- Lines: 1-27
- SHA256: fb716061b05c0b0f54560f81adec9a3eb9ce86610e7d24438d009ec0a4299a5e

```md
## 1. MCP stderr 隔离与诊断

- [ ] 1.1 先写失败测试覆盖 per-server/generation `errlog` 注入、字节上限、成功 chatter 丢弃、secret masking、固定原因分类和旧 generation 不覆盖新诊断
- [ ] 1.2 实现有界 stderr sink、`stdio_client(..., errlog=...)` 接线和兼容现有 `server_status()` 的 masked diagnostic projection

## 2. 交互式启动呈现

- [ ] 2.1 先写失败测试覆盖真实 TTY、`NO_COLOR`、无颜色、窄终端、确认暂停、成功/异常/`Ctrl-C` 清理和无残留刷新线程
- [ ] 2.2 在 CLI 内实现最小 StartupRenderer、纯 ASCII 七色 Logo、初始化生命周期和模型/sandbox/project 摘要
- [ ] 2.3 实现 MCP `available/enabled` 摘要，确保 disabled 排除、optional 失败一行降级、required 失败不渲染部分 Ready

## 3. 非 TTY 与错误输出

- [ ] 3.1 先写失败的 CLI/子进程回归，固定 pipe quit 零 stdout/stderr、管道任务结果导向、`run`/`serve` 无 Logo 和 optional MCP 状态
- [ ] 3.2 统一 stdin/stdout TTY 判定，移除非交互 banner/prompt/启动状态，并把 required MCP 启动错误接到 sanitized stderr + 非零退出路径

## 4. `/mcp` 用户诊断

- [ ] 4.1 先写失败测试覆盖可用工具数、Reason / Impact / Action、Docker 非默认 sandbox 说明、unknown 降级、disabled 状态和 public label/secret masking
- [ ] 4.2 扩展 `/mcp status` 的结构化展示，保留 enable/disable、工具列表、timeout pending 和现有路由语义

## 5. 文档、评审与验证

- [ ] 5.1 更新 README 与相关 CLI/MCP 文档，记录交互/非交互输出契约、`/mcp` 诊断和无新依赖/权限边界
- [ ] 5.2 运行受影响测试、完整 pytest、ruff check/format、golden 20/20、OpenSpec strict、package build 和 diff check
- [ ] 5.3 完成两轮 whole-change 自审和独立代码评审，立即修复发现并重跑相关与完整验证
- [ ] 5.4 产出本 change 验证报告，执行 Comet verify/archive，并确认所有既存 dirty 路径未进入本 change 提交

```

## openspec/changes/startup-information/specs/mcp-resilience/spec.md

- Source: openspec/changes/startup-information/specs/mcp-resilience/spec.md
- Lines: 1-67
- SHA256: f1628639facbb9853b382490e03b785584721ef7730f63a00ba558af35e30cad

```md
## MODIFIED Requirements

### Requirement: Optional MCP failures degrade predictably

ForgeAgent SHALL continue startup when an optional MCP server fails to connect, SHALL exclude that server's unavailable tools, and SHALL emit only a masked fixed failure category and bounded user-facing diagnostic. Each server/generation's child stderr SHALL be isolated in its own bounded in-memory sink; raw stderr, command, arguments, environment, server content, Python exception type and `ExceptionGroup` text MUST NOT reach startup output, `/mcp`, structured feedback or lifecycle logs.

#### Scenario: Optional server connection fails
- **WHEN** an optional MCP server cannot start or complete its connection handshake
- **THEN** the CLI remains usable with other tools and reports the degraded server using its public label and fixed failure category

#### Scenario: Optional server emits startup chatter
- **WHEN** an MCP child writes normal startup chatter to stderr before becoming available
- **THEN** the chatter is consumed by that server's sink and does not appear in ForgeAgent stdout or stderr

#### Scenario: Optional server failure carries a known secret
- **WHEN** an optional server failure stderr or exception contains a configured secret value
- **THEN** server status, startup diagnostics and `/mcp` output contain neither the secret nor raw failure text

#### Scenario: Docker runtime is unavailable
- **WHEN** an enabled optional server uses Docker and its stderr matches the known Docker daemon-unavailable condition
- **THEN** `/mcp` reports a fixed user-facing reason that Docker is not running, explains that only that configured integration is disabled, and offers starting Docker or disabling that server

### Requirement: Required MCP failures abort startup

ForgeAgent MUST return a non-zero CLI startup result when a required MCP server fails to connect, MUST NOT start the task, and MUST perform bounded cleanup of MCP resources that were already started. The required-startup error MUST be written through the sanitized stderr path and MUST NOT expose raw child stderr, command, arguments, environment, server content, Python exception type or `ExceptionGroup` text. Normal cleanup MUST release those resources. When an event-loop thread is hard-stuck, the required CLI failure MAY remain incomplete at the public deadline only while retaining cleanup evidence and emitting a sanitized warning. If the authoritative drain does not yet exist, the queued shutdown facade or fallback callback on the live loop/thread MUST keep the manager state strongly reachable; if the drain exists, that sole loop-owned drain MUST keep it reachable. When the loop recovers, queued work MUST create or reuse the sole authoritative drain and continue cleanup; an existing drain MUST continue directly. Because `build_mcp_manager()` closes and raises `MCPStartupError`, the CLI MUST NOT expose or promise a later `close()` handle, and this path MUST NOT add a global registry, `atexit` hook, or new API. A direct API caller that still holds the `MCPManager`, and ordinary manager lifecycle repeated `close()` calls, MAY use a new bounded close retry.

#### Scenario: Required server connection fails
- **WHEN** a required MCP server cannot start or complete its connection handshake
- **THEN** the CLI reports a fixed sanitized startup error, makes one bounded cleanup attempt for already-started MCP resources, and exits non-zero before running the task without exposing a manager or later-close handle

#### Scenario: Required startup failure cleans up normally
- **WHEN** a required server fails after one or more MCP resources have started and their loop thread remains responsive
- **THEN** bounded cleanup releases the started holder/session/loop/thread resources before the CLI returns its non-zero startup result, and no task starts

#### Scenario: Required startup failure encounters a hard-stuck loop
- **WHEN** a required server fails and cleanup cannot complete because the MCP event-loop thread is blocked in synchronous code
- **THEN** the CLI exits non-zero before task execution at its bounded deadline, retains holder/session/lifecycle/loop/thread evidence through either queued shutdown facade/fallback work on the live loop/thread or an already-created sole authoritative drain, emits only a sanitized incomplete-cleanup warning, and lets recovered queued work create or reuse that drain and continue cleanup; the CLI exposes no later `close()` handle and does not fabricate completion

#### Scenario: User changes a required server during an active REPL
- **WHEN** the REPL has already started with an MCP manager because at least one server was enabled at startup, and the user explicitly disables or enables a server configured with `required: true`
- **THEN** ForgeAgent updates and reports that server's runtime status without terminating the existing REPL session

#### Scenario: Runtime MCP update exceeds its facade wait
- **WHEN** `/mcp enable` or `/mcp disable` times out while its loop-owned operation continues
- **THEN** the CLI reports a fixed pending status for the named server and keeps the REPL running instead of propagating `TimeoutError`

#### Scenario: Every configured server is disabled at startup
- **WHEN** all MCP server entries are disabled when the CLI is assembled
- **THEN** ForgeAgent starts without an MCP manager or loop, does not fail because a disabled server is required, and does not promise runtime enable from that manager-less session

#### Scenario: Required server emits raw stderr before failing
- **WHEN** a required MCP child writes Docker, filesystem, or arbitrary stderr before its handshake fails
- **THEN** the required startup error contains only the fixed failure category and no raw child line

## ADDED Requirements

### Requirement: MCP child stderr is isolated per server and generation

ForgeAgent SHALL pass a distinct bounded text sink to each MCP SDK `stdio_client(..., errlog=...)` invocation. The sink SHALL retain only a fixed maximum number of bytes in memory, record whether truncation occurred, and release its content after the holder generation is finalized. Masking and fixed-category classification SHALL happen before any diagnostic projection; an older generation MUST NOT overwrite a newer generation's diagnostic.

#### Scenario: One server writes more than the bound
- **WHEN** an MCP child writes stderr beyond the configured sink limit
- **THEN** the sink remains bounded, records truncation, and the public diagnostic uses a fixed truncation marker without exposing the complete text

#### Scenario: A replacement generation starts
- **WHEN** generation N is unavailable and generation N+1 is explicitly enabled
- **THEN** generation N's sink and diagnostic cannot replace or mutate generation N+1's status or diagnostic

```

## openspec/changes/startup-information/specs/repl-interactive-input/spec.md

- Source: openspec/changes/startup-information/specs/repl-interactive-input/spec.md
- Lines: 1-21
- SHA256: 7b62853d7dd7f5b478149b90bdedf5dd9026c198179d3ef43a1776014e7182be

```md
## MODIFIED Requirements

### Requirement: 非交互与测试输入保持兼容

系统必须（SHALL）只在默认 reader 且 stdin/stdout 均为交互式终端时启用增强输入和交互式启动呈现。显式注入的 `read_line` 和非 TTY 输入必须（MUST）保持原有 EOF、KeyboardInterrupt、空行、确认与 Survey 行为；同时不得输出 Logo、启动 banner、MCP 可选状态或交互式 goal prompt。管道任务仍可使用已经连接的 MCP 和既有任务结果渲染。

#### Scenario: 注入 reader 不创建终端会话
- **WHEN** 测试或嵌入方显式传入 `read_line`
- **THEN** REPL 只调用该 reader，且不访问增强终端输入对象或启动 Logo renderer

#### Scenario: 非 TTY 使用普通输入
- **WHEN** REPL 默认启动但 stdin 或输出不是 TTY
- **THEN** 系统使用普通输入路径，保持现有 EOF、KeyboardInterrupt、空行、确认与 Survey 语义，并不打印交互式启动或 goal prompt

#### Scenario: 管道只输入退出命令
- **WHEN** 用户执行 `printf 'quit\\n' | forgeagent ...` 且没有任务输入
- **THEN** 进程以 0 退出，stdout 和 stderr 均为空

#### Scenario: 管道提交任务
- **WHEN** 用户通过非 TTY 输入提交一个 goal
- **THEN** MCP 可继续为任务提供能力，但启动 banner、Logo、MCP optional 状态和交互 prompt 不出现在输出中，既有任务结果仍被输出

```

## openspec/changes/startup-information/specs/repl-startup-information/spec.md

- Source: openspec/changes/startup-information/specs/repl-startup-information/spec.md
- Lines: 1-45
- SHA256: d6be03e4e5633bb4bc7ac5f950a61876a572e4cd2968f5215d6caf372d47d767

```md
## ADDED Requirements

### Requirement: 交互式启动展示产品标识

ForgeAgent SHALL only in a real interactive REPL (stdin and stdout are TTYs, default reader in use) render a pure ASCII ForgeAgent product mark before the first goal prompt. During initialization the mark SHALL use a bounded low-frequency seven-color animation, SHALL stop deterministically when startup succeeds, fails, or receives process control, and SHALL pause while an interactive confirmation or Survey answer is being read.

#### Scenario: Interactive startup reaches ready state
- **WHEN** the default REPL starts with TTY stdin and stdout and initialization completes
- **THEN** the user sees the pure ASCII ForgeAgent mark, the animation ends, and the first goal prompt is rendered without residual refresh lines

#### Scenario: Interactive startup requires confirmation
- **WHEN** initialization reaches an identity, Skill, or other confirmation prompt
- **THEN** the Logo renderer pauses before the prompt and resumes or terminates after the answer without corrupting the input line

#### Scenario: Interactive startup is interrupted
- **WHEN** the user presses `Ctrl-C` while the startup renderer is active
- **THEN** the renderer stops in bounded time, no background renderer remains, and the original process-control behavior is preserved

### Requirement: 启动摘要反映实际能力

ForgeAgent SHALL render one compact startup summary after successful interactive initialization containing the selected model, the actual sandbox tier, the resolved project root, and an MCP availability summary when at least one MCP server is enabled. The summary denominator SHALL be the number of servers with `enabled: true` in the startup snapshot; disabled servers SHALL be excluded. The numerator SHALL be the servers that completed startup and are available. A required-server failure SHALL abort before a partial summary is rendered.

#### Scenario: One optional server fails
- **WHEN** two servers are enabled, one available and one optional unavailable
- **THEN** the summary reports `MCP 1/2`, keeps the REPL usable, and emits one compact optional-degradation line

#### Scenario: Disabled server is present
- **WHEN** a configured server is disabled and another enabled server is available
- **THEN** the disabled server is excluded from the startup denominator and does not create an optional-degradation warning

#### Scenario: No MCP server is enabled
- **WHEN** every configured MCP entry is disabled or no MCP configuration exists
- **THEN** the startup summary omits MCP counts and the REPL starts normally

### Requirement: 终端能力决定 Logo 降级

ForgeAgent SHALL render the Logo animation only when the interactive startup requirement is met. A `NO_COLOR` or color-disabled terminal SHALL receive a static monochrome mark; a narrow terminal SHALL receive a compact single-line `ForgeAgent` mark; non-TTY, `TERM=dumb`, CI, `run`, and `serve` paths SHALL receive no Logo or ANSI animation.

#### Scenario: Color is disabled
- **WHEN** `NO_COLOR` is set or Rich reports no color system
- **THEN** the interactive user receives a static monochrome mark with no ANSI color sequences

#### Scenario: Terminal is narrow
- **WHEN** the terminal width cannot contain the full ASCII mark
- **THEN** ForgeAgent uses the compact single-line mark without wrapping or corrupting the first prompt

```
