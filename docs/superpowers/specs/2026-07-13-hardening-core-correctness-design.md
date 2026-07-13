---
comet_change: hardening-core-correctness
role: technical-design
canonical_spec: openspec
---

# ForgeAgent 核心正确性加固技术设计

## 1. 背景与证据

本设计深化 `hardening-core-correctness` 的 OpenSpec proposal、design 和五份 capability specs。OpenSpec 仍是需求与验收事实源；本文只定义实现边界、数据流、错误传播、测试结构和迁移顺序。

CodeGraph 和实证测试确认了以下当前路径：

- `guarded_urlopen()` 由 `WebFetchTool` 和 `web_search` 调用。它使用 `urllib.request.build_opener()` 加载 guarded HTTP/HTTPS handler，但没有显式提供空 `ProxyHandler`，因此 opener 会继承环境代理。
- `make_console_confirmer()` 的类型签名是通用 `Confirmer`，内部却只访问 `MCPArgs.server/tool/arguments`。CLI 的 run 和 REPL 又仅在 `mcp is not None` 时把 confirmer 传入 Task，导致无 MCP 时的 WebFetch/FileWrite 无法确认。
- `Step._handle_reply()` 先解析、注册代码块并执行工具，再调用 `_apply_declared_status()`；当前完成声明没有检查同轮工具调用或解析错误。
- `MCPManager.connect()` 并发启动每个 enabled server，并把服务级失败收敛为 unavailable；配置中没有 `required`。`close()` 会等待所有 holder，但同步 facade 没有独立 shutdown deadline、取消阶段和线程 join。
- MCP SDK 的 stdio transport 已提供进程级清理：关闭 stdin，等待 2 秒，随后执行进程树 SIGTERM/SIGKILL 升级。ForgeAgent 需要补齐的是其外层 holder、event loop 和线程的有界收尾。
- `docs/golden-tasks-seed.md` 列出 G01-G380，但 `tests/test_mock_replay_e2e.py` 只为少量场景提供直接 pytest 回放，没有统一 manifest、runner、机器报告或可信通过率。

## 2. 目标与非目标

### 2.1 目标

- 让 SSRF 校验地址与实际连接地址保持一致，默认网络路径不受环境代理影响。
- 让 MCP、WebFetch、FileWrite 共用类型安全且终端行为一致的 confirmer。
- 让完成状态只来自模型已经看到工具/解析反馈后的独立最终响应。
- 让 MCP 服务按 criticality 降级或阻断启动，并让关闭有界、幂等且不污染原结果。
- 建立 20 项完全离线、自动判定、可报告的黄金可信核心，以及 5 项显式 opt-in 真实模型子集。
- 消除测试对真实 HOME、全局进程计数和不受控环境能力的依赖。

### 2.2 非目标

- 不实现代理转发、代理认证、PAC、系统代理兼容或 `NO_PROXY` 行为。
- 不增加审批策略对象、运行时安全总线、MCP supervisor 或通用评测框架。
- 不改变 MCP 协议、工具发现方式、`autoApprove` 语义或运行期 enable/disable 权限。
- 不一次性工程化其余 360 个候选任务，也不把真实模型验证设为基础 CI 门禁。
- 不修改 `resource/agent/`，不增加厂商端点、凭证或依赖。

## 3. 总体方案

采用原模块边界内的最小加固：

```text
CLI
 ├─ load MCP config
 │   ├─ connect enabled servers concurrently
 │   ├─ optional unavailable -> diagnose and continue
 │   └─ required unavailable -> bounded close -> startup error 2
 ├─ choose confirmer
 │   ├─ REPL -> interactive confirmer
 │   ├─ run + stdin/stdout TTY -> interactive confirmer
 │   └─ run + non-TTY -> no confirmer, gated tools deny
 └─ Task -> Step
     ├─ parse response
     ├─ register blocks and dispatch tools
     ├─ tool calls or parse errors -> ignore completed=true, render feedback
     └─ no tools/errors + completed=true -> complete

WebFetch / search
 └─ guarded_urlopen
     ├─ ProxyHandler({})
     ├─ guard-owned redirect handler (HTTP/S only, max 10)
     ├─ guarded HTTP/HTTPS handler
     ├─ resolve and reject every blocked address
     └─ connect exact vetted sockaddr on every redirect hop
```

产品代码不新增跨模块策略对象。新的结构只存在于测试侧的 `tests/golden/`，用于表达固定的验证清单和报告协议。

## 4. 网络边界设计

### 4.1 显式直连

`guarded_urlopen()` 构造 opener 时显式传入 `urllib.request.ProxyHandler({})`，并继续传入 guard-owned redirect handler、`_GuardedHTTPHandler` 和 `_GuardedHTTPSHandler`。空 proxy mapping 会阻止 `build_opener()` 自动安装读取环境变量的默认 ProxyHandler。

该改动不调整函数签名。`WebFetchTool` 和 `web_search` 继续通过同一入口发起请求，因此两条用户路径自动获得相同行为。

### 4.2 SSRF 不变量

- 仅接受 HTTP/HTTPS scheme。
- 每个 DNS 结果都必须通过 `_is_blocked()`；任一结果被阻止时整个连接失败。
- NAT64 地址继续检查嵌入 IPv4。
- socket 连接到已经校验的 sockaddr，不进行第二次主机名解析。
- `_GuardedRedirectHandler` 自己在 Request 上传播 hop count，最多允许 10 跳；第 11 跳在打开目标前抛出带 `redirect limit exceeded` 原因的 `SSRFGuardError`。
- redirect handler 只接受解析后的 HTTP/HTTPS URL。urllib 默认允许的 FTP redirect 在 guard 层被拒绝，不能进入默认 FTP handler。
- 每次允许的重定向重新创建 guarded connection，因此每跳重新执行相同地址校验。

### 4.3 未来代理契约

威胁模型和配置文档预留以下未来形态：

```yaml
network:
  proxy:
    url: http://proxy.example:8080
    no_proxy:
      - example.internal
```

这只是未来契约说明。当前版本不解析这些字段，不实现代理，不读取 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY` 或大小写变体。实现依赖显式空 ProxyHandler 屏蔽环境代理，不会通过 `os.environ.pop()` 修改进程全局环境；后者会影响并发调用方并制造新的竞态。文档必须明确配置该片段当前不会启用转发。

## 5. 工具确认设计

### 5.1 保留现有接口

`Confirmer = Callable[[BaseModel], bool]` 保持不变。CLI 内部增加一个小型 formatter，由 `make_console_confirmer()` 调用：

- `MCPArgs`：显示 `server:tool`。arguments 递归遍历 dict/list；键名匹配现有 `is_secret_name()` 时，无论值长度都显示 `<redacted>`；其他字符串再用 `mask_secrets(..., sensitive_env_values())` 替换已知环境 secret value。
- `WebFetchArgs`：通过 `urllib.parse` 清除 URL userinfo 和 fragment，替换敏感 query key 的值，再用 `mask_secrets()` 处理已知 secret value。hostname 和 path 在匹配前先 percent-decode；hostname 按 DNS 大小写不敏感语义匹配，再结构化重建显示 URL。不得用字符串正则直接改写 URL 结构。
- `FileWriteArgs`：不回显 content。绝对路径在 cwd 内时显示项目相对路径，在 cwd 外时只显示 `.../<basename>`；相对路径保持规范化相对形式。提示同时显示 content 字符数。
- 其他 `BaseModel`：只显示类型名，避免访问不存在的字段或意外回显敏感数据。

全局 `mask_secrets()` 的既有契约保持不变：它按敏感环境变量名收集长度至少 8 的值，再做最长值优先替换。结构化键脱敏只属于 confirmer formatter，避免改变 executor/MCP output 的既有行为和误报面。

输入仍只接受 `y`/`yes`。EOF、空输入和其他值全部拒绝。

### 5.2 终端选择

- REPL 本身就是交互入口，始终创建并传入 confirmer，不再以 MCP 是否存在为条件。
- 单次 `run` 只有在 `sys.stdin.isatty()` 与 `console.is_terminal` 同时为真时传入 confirmer。
- 非 TTY 不读取 stdin，向 Task 传 `None`。WebFetch/FileWrite 和仍需确认的 MCP 调用返回 `rejected: no interactive confirmation channel available`，与用户在 TTY 中明确回答 no 的 `not approved by the user` 区分。
- `--interactive` 继续只决定 Survey 是否获得 asker，不参与 confirmer 选择。
- MCP `autoApprove` 是用户配置中的显式预批准，继续在调用 confirmer 前短路；因此它可以在非 TTY 执行。WebFetch/FileWrite 没有对应例外。

### 5.3 执行结果的最小披露

实施期 thorough review 发现确认后的工具结果同样会进入 Step feedback 和 CLI console。用户于 2026-07-13 选择把该问题纳入当前 change，并批准固定安全结果消息方案：

- WebFetch 捕获 `SSRFGuardError` 时返回固定 `WebFetch blocked by network policy`，捕获 `OSError` 时返回固定 `WebFetch request failed`。不得把底层异常、原始 URL 或 hostname 写入 `ToolOutcome.detail`。
- FileWrite 通过 project-root 校验并成功写入后，只返回由已解析目标相对 `allowed_root` 计算出的 project-relative 路径；不复用模型提供的原始绝对路径。
- FileWrite 写入阶段发生 `OSError` 时返回固定 `FileWrite failed`。越界、无交互通道和用户拒绝继续使用既有固定消息。
- 不新增通用 result sanitizer，不修改 FileRead/FileList/MCP 的结果契约，也不改变全局 `mask_secrets()` 行为。固定消息牺牲部分底层诊断细节，以避免平台相关异常字符串重新引入 URL、hostname 或宿主绝对路径泄漏。

测试必须覆盖：percent-encoded 且大小写变化的 hostname secret；携带原始 URL/hostname 的 WebFetch guard/network 异常；FileWrite 使用绝对 cwd 内路径成功时只回显 project-relative 路径；FileWrite 写入异常包含绝对路径时结果仍为固定消息。以上结果还需通过现有 Step feedback 渲染路径验证不再泄漏。

## 6. 完成状态设计

### 6.1 状态门控

`Step._handle_reply()` 在 parse 后计算：

```python
allow_completed = not parsed.tool_calls and not parsed.errors
```

工具仍按当前顺序执行，确保其 outcome 被记录。随后 `_apply_declared_status()` 接收 `allow_completed`：

- `status.completed is True` 且 `allow_completed` 为真：设置 `Termination.COMPLETED`。
- `status.completed is True` 且 `allow_completed` 为假：忽略完成声明，不设置 terminal reason。
- `completed: false` 携带 refused/need_info/failed：保持现有映射，不在本 change 扩大语义。

### 6.2 反馈与终止

被忽略完成声明的工具 outcome 或 parse error 通过 `_render_feedback()` 进入下一条 user message。模型必须在后续轮次返回无工具、无解析错误的独立完成响应。

工具失败不直接把任务标为 failed；它仍是模型可修正的反馈。若模型始终不能给出合法最终响应，现有 max_rounds、client_error、truncated、empty_response 等终止分类继续生效。

不采纳“工具全部成功即可接受同轮 completed”的优化：该完成声明由模型在看到工具结果之前生成，工具是否 auto-approved 只描述授权来源，不证明模型已经验证结果。接受它会重新引入本 change 要关闭的时序漏洞。额外一轮是明确且有意的正确性成本。

## 7. MCP 启动与关闭设计

### 7.1 配置模型

`MCPServerConfig` 增加：

```python
required: bool = False
```

只有 `enabled=True` 的 required server 构成初始启动要求。`required=True, enabled=False` 表示该服务当前明确关闭，不阻断启动。

### 7.2 启动判定

`MCPManager.connect()` 保持并发连接和 per-server unavailable 状态。新增只读查询返回 enabled required failures，例如 `required_failures() -> dict[str, str]`。

`build_mcp_manager()` 的流程：

1. 加载配置并构造 manager。
2. 无 enabled server 时返回 `None`。
3. 调用 `connect()`。服务级连接失败继续由 holder 收敛为状态；manager 基础设施异常则 best-effort close 后转为启动错误。
4. 收集 required failures。
5. 若非空，先调用不会抛出的 `close()`，再抛 `MCPStartupError`，消息包含服务名和状态。`close()` 进入后第一项动作必须是设置 closed state，避免二次错误让启动清理重新进入。
6. 否则打印全部状态；optional unavailable 使用黄色诊断，返回 manager。

CLI 捕获 `MCPStartupError`，打印单行错误并返回 2。run 与 REPL 都使用同一构造函数，因此行为一致。

运行期 `/mcp enable|disable` 保持用户显式控制。required 只约束启动，不会因为会话中状态变化强制退出 REPL。

### 7.3 有界关闭

manager 构造参数增加仅供内部/测试注入的 `shutdown_timeout=10.0` 和 `thread_join_timeout=2.0`。不写入 mcp.yaml。`connect_timeout=15.0` 已经是现有的每服务连接上限，超时 server 会被标记 unavailable；本 change 不增加重复的用户配置。

`close()` 顺序：

1. 用 `getattr(self, "_closed", False)` 检查重复调用；否则立即置真，保证后续任意异常都不会重新进入关闭状态机。
2. 未创建 loop 时直接清理引用并返回。
3. 用 `time.monotonic()` 建立唯一绝对 deadline：当前时间加 `shutdown_timeout + thread_join_timeout`。所有阶段只读取 `remaining = max(0, deadline - monotonic())`，不累计相对 timeout。
4. 在 loop 上运行 `_shutdown()` 并向全部 state.stop 发信号。正常 holder 阶段最多消费 5 秒，但必须为 thread join 保留最多 `thread_join_timeout`；若提前完成，未使用额度自动留给 cancel 阶段。
5. cancel 仍 pending 的 holder，并用 `remaining - join_reserve` 作为第二阶段预算。预算为 0 时不再等待。
6. 清空 holder/session；任何单 holder 异常被收集而不传播。
7. `loop.call_soon_threadsafe(loop.stop)`，`thread.join()` 使用 `min(thread_join_timeout, remaining)`，不会越过同一个绝对 deadline。
8. 线程已停止时关闭 loop；仍存活时记录 warning，不对活跃 loop 调用 close。
9. 公开 `close()` 边界在 closed state 设置后用 `try/except Exception/finally` 包围内部操作。Exception 只记录 warning，finally 尽最大可能执行 loop stop、join 和引用清理；KeyboardInterrupt/SystemExit 不被吞掉。
10. 返回 None，不向调用方传播关闭异常。

正常和无响应 fixture 必须证明 SDK 的进程树清理可以在上限内结束子进程。极端情况下 Python daemon thread 可能在 join 上限后仍存活；CLI 仍能返回，warning 保留诊断证据。

## 8. 测试环境隔离

根 `tests/conftest.py` 不在模块全局作用域修改环境。它通过 `pytest_sessionstart` 为当前 pytest 进程创建唯一临时 home，并设置 `HOME` 与 `USERPROFILE`；该 hook 发生在测试模块收集前，因此 `mcp_manager`、`model_registry`、`web_search` 和 `model_discovery` 的 import-time 默认路径都指向隔离目录。`pytest_sessionfinish` 删除目录。

pytest-xdist 当前不是项目依赖；若调用方安装并使用它，每个 worker 是独立进程，各自运行 session hook、拥有独立环境和唯一目录，不共享可变 `os.environ`。函数级 monkeypatch 无法回溯已经计算的模块常量，因此仅用于需要自定义 home 内容的具体测试，不承担全局隔离。

测试若需要特定用户配置，必须在隔离 home 内显式创建或通过已有 path 参数注入。禁止读取真实 `~/.forgeagent`。

SSRF 测试调整：

- loopback 初始目标拒绝不需要启动 HTTP server，直接证明 guard 在 socket connect 前抛错。
- 环境代理回归使用假公有代理地址和 socket 插桩：旧实现会尝试连接代理，修复后会直接校验并拒绝 loopback 目标。
- redirect handler 单测覆盖第 10 跳允许、第 11 跳拒绝，以及 HTTP 跳转 FTP/file 被拒；本地 server 集成只验证允许跳的逐跳 connection 复核。
- 真正需要本地 redirect server 的测试先做 bind capability probe；权限不允许时以明确理由 skip。

MCP 子进程测试调整：fixture server 可通过测试环境变量写出自身 PID。测试使用每服务唯一 PID 文件，检查启动后 PID 存活、close 后在 deadline 内消失，替换依赖机器全局状态的进程数量比较。

## 9. 黄金可信核心

### 9.1 文件结构

```text
tests/golden/
├── __init__.py
├── manifest.py   # GoldenScenario + 固定 20 项清单
├── cases.py      # setup / offline execution / real execution / judge
└── runner.py     # preflight、循环、报告、exit code

tests/test_golden_runner.py
artifacts/golden/                 # generated, gitignored
├── offline/results.json
├── offline/report.md
└── real/<model-id>/...
```

### 9.2 Manifest 合约

`GoldenScenario` 是不可变 dataclass，至少包含：

- `scenario_id`
- `title`
- `run_offline: Callable`
- `run_real: Callable | None`

runner preflight 必须验证：

- 总数恰好 20，ID 唯一。
- ID 集合严格等于 G01/G03/G05/G06/G08/G11/G13/G14/G15/G17/G27/G43/G58/G59/G324/G329/G330/G332/G333/G355。
- 只有 G01/G03/G08/G11/G43 提供 `run_real`，数量恰好 5。
- 每个 manifest ID 在 `docs/golden-tasks-seed.md` 中仍有 heading 或表格任务定义。该检查只验证引用存在，不在 Markdown 中维护第二套 `[CORE]` 标签。

### 9.3 场景执行

每个场景获得独立临时工作目录。case callable 负责 fixture 创建、Task/CLI/工具调用和显式 judge，并返回标准化 evidence。判定不得依赖 Python `assert`，以免 `python -O` 改变结果；失败通过专用 check error 或结构化结果表达。

离线模式只使用 MockClient、本地文件、测试 double 和本地 MCP fixture。基础运行不得访问公网、Docker、真实模型配置或用户 home。

G13 的离线脚本在工具失败/成功轮携带提前 `completed: true`，同时验证错误反馈环和严格两阶段完成。MCP required/close 的细粒度故障矩阵保留在专项测试；G355 只承担产品级状态/工具目录和 optional 降级冒烟。

现有 `test_mock_replay_e2e.py` 的 G01/G05/G13 逻辑迁移到 cases 供 runner 与 pytest 共享，不复制一套脚本和 judge。

### 9.4 报告和退出码

runner 接受默认离线模式、`--real-model <model-id>` 和可选 `--output-dir`。

JSON 结果包含：schema version、mode、model、开始/结束时间、total/passed/failed/pass_rate，以及逐项 ID、title、passed、duration、detail 和 evidence。Markdown 从同一个结果对象生成摘要和逐项表格，不进行第二次判定。

- 全部场景通过：写报告，退出 0。
- 任一场景失败或异常：继续运行剩余场景，写完整报告，退出 1。
- manifest 不合法、真实模型无法解析/鉴权、输出目录不可用等 preflight 失败：退出 2，不生成通过率报告。

默认输出为 `artifacts/golden/offline/` 或 `artifacts/golden/real/<sanitized-model-id>/`，覆盖同模式上一次结果，提供稳定 CI 路径。每个文件使用同目录临时文件加 `os.replace()` 原子写入，避免进程中断留下半文件。`artifacts/` 加入 `.gitignore`。

runner 本里程碑明确顺序执行，不承诺多个进程同时写同一个 output-dir；并发调用方必须提供不同的 `--output-dir`。因此不增加跨进程锁或并行写测试。

## 10. 测试矩阵

| 能力 | 关键测试 | 主要证据 |
| --- | --- | --- |
| 代理/SSRF | 大小写 proxy env、loopback、private、NAT64、redirect private、11 跳、FTP/file redirect | 实际校验 host 是目标而非代理；blocked target 未连接；redirect limit/scheme 明确拒绝 |
| confirmer 与结果最小披露 | MCP/WebFetch/FileWrite formatter、EOF、空输入、带空白的 yes/no、嵌套 secret key、encoded/case hostname、URL/path mask、WebFetch 失败、FileWrite 成功/失败 outcome | 无属性错误；prompt、ToolOutcome、Step feedback 不回显敏感 URL/hostname/宿主绝对路径；TTY 与非 TTY 原因正确 |
| CLI 注入 | REPL、TTY run、非 TTY run、`--interactive` | confirmer 与 MCP 解耦；Survey 语义不漂移 |
| 完成门控 | 工具成功/失败/parse error + completed；后续独立完成 | 同轮不完成；反馈后完成；max_rounds 诚实 |
| MCP 配置 | required 默认、enabled/disabled required | optional 降级；required 启动失败；禁用项不阻断 |
| MCP close | 正常、完全忽略 stop、内部异常、重复 close、结果保留 | 绝对 deadline 内返回；cancel/join 分支执行；PID 消失；原结果不被覆盖 |
| 测试隔离 | 真实 home 放置恶意 mcp.yaml 后运行 suite | 测试只读取临时 home，结果不变 |
| 黄金 runner | manifest 变异、20 pass、单项 fail、preflight fail | ID/数量锁定；JSON/Markdown 同源；退出码 0/1/2 |
| 真实模型入口 | 缺配置、有效单模型 | 缺配置无报告且退出 2；只执行 5 项 |

## 11. 文档与迁移

实现完成后同步：

- `docs/model-client-contract.md`：当前 complete/streaming 和多模态支持。
- `docs/text-protocol-spec.md`：WebFetch、FileRead/FileWrite/FileList、MCP 与两阶段完成。
- `docs/threat-model.md`：环境代理禁用、guarded direct connection、确认门边界和未来 proxy 契约。
- MCP/CLI 文档：`required`、optional 降级、TTY/non-TTY、`autoApprove` 例外。
- `docs/golden-tasks-seed.md` 与 README：20 项可信核心、360 项候选、5 项 opt-in 真实模型和报告命令。
- ACTION_PLAN、加固里程碑和 `milestones/latest`：只记录实证运行结果；不改写用户已有 M11/M12 规划内容，里程碑编号在收尾时按现有空位和 `MILESTONE_GUIDE.md` 确定。

迁移无需数据转换。MCP 新字段默认 false，旧配置兼容。环境代理被禁用属于 `[SECURITY][BREAKING]` 安全加固：发布说明必须提示依赖企业代理的用户当前会直连失败，且本里程碑没有可用的显式代理替代。

## 12. 实施顺序

1. 固化回归与测试 home/PID 隔离。
2. 修复 ProxyHandler 和 SSRF 测试。
3. 修复 confirmer formatter、TTY 注入和完成门控。
4. 增加 MCP required、启动错误和 bounded close。
5. 建立 20 项 golden manifest/cases/runner/report。
6. 同步协议、威胁模型、README 和里程碑文档。
7. 运行 Ruff、隔离全量 pytest、专项测试、离线黄金 runner 和 CodeGraph 复审。

每组先写失败测试再实现，不跨组引入共享抽象。真实模型 5 项仅在用户显式提供模型和凭证时补充报告，不阻断基础验收。

## 13. 回滚与失败处理

- 网络修复可独立回滚，但文档必须同步恢复，不能继续声称环境代理已禁用。
- confirmer 与完成门控分别有独立测试；若任一回滚，黄金报告不得把对应场景标为可信通过。
- MCP `required` 默认 false，回滚不会破坏旧 YAML；若 close 变更回滚，必须恢复到不会泄漏子进程的最后已验证实现，不能回到已知无界等待状态。
- 黄金 runner 是测试基础设施，可不影响产品运行时独立回滚；文档中的“可信核心”声明必须与可运行工件同时存在。

## 14. 完成判据

- 五份 OpenSpec capability specs 的场景均有对应测试或黄金证据。
- Ruff 通过。
- 隔离 HOME 的完整 pytest 通过；环境能力不足只产生有理由的 skip，不使用人工 deselect 隐藏失败。
- 20 项离线黄金核心生成 20/20 机器和 Markdown 报告，退出 0。
- required MCP 失败、close deadline、代理环境和严格完成专项测试通过。
- redirect 第 11 跳与非 HTTP/HTTPS scheme 在 guard 层被明确拒绝。
- CodeGraph 复审确认所有受影响调用方已覆盖，文档不再声称未执行的 380 项已验证。
