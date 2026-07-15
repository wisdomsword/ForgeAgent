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
- 2026-07-14 的主 Agent 复审进一步证明：`http.client.HTTPException` 系列不继承 `OSError`，WebFetch 和 `/search` 的现有捕获边界会让 `IncompleteRead`、`BadStatusLine` 等异常逃出；WebFetch 落盘错误也位于捕获区外。
- `_validate_path()` 与 restricted audit hook 共用的 `realpath + startswith(base + os.sep)` 判定在 `allowed_root="/"` 时错误拒绝所有子路径；非法 NUL 路径会抛出未收敛的 `ValueError`，FileRead/FileList 失败文本还会回显宿主绝对路径。

## 2. 目标与非目标

### 2.1 目标

- 让 SSRF 校验地址与实际连接地址保持一致，默认网络路径不受环境代理影响。
- 让 WebFetch 和 `/search` 将预期的 URL、传输、HTTP 协议、响应解码和 WebFetch 落盘失败收敛为稳定结果，不让工具级异常逃出。
- 让 MCP、WebFetch、FileWrite 共用类型安全且终端行为一致的 confirmer。
- 让 FileRead/FileWrite/FileList 与 restricted audit hook 使用 root-safe 的路径包含判定，并让文件工具失败结果不暴露宿主绝对路径。
- 让完成状态只来自模型已经看到工具/解析反馈后的独立最终响应。
- 让 MCP 服务按 criticality 降级或阻断启动，并让关闭有界、幂等且不污染原结果。
- 建立 20 项完全离线、自动判定、可报告的黄金可信核心，以及 5 项显式 opt-in 真实模型子集。
- 消除测试对真实 HOME、全局进程计数和不受控环境能力的依赖。

### 2.2 非目标

- 不实现代理转发、代理认证、PAC、系统代理兼容或 `NO_PROXY` 行为。
- 不增加审批策略对象、运行时安全总线、MCP supervisor 或通用评测框架。
- 不增加通用异常翻译器、结果 sanitizer 或共享路径策略模块；各现有边界使用标准库和固定局部消息完成收敛。
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

WebFetch / search consumers
 ├─ SSRFGuardError -> blocked category
 ├─ expected URL/transport/HTTP failures -> stable consumer failure category
 ├─ unknown search charset -> UTF-8 replacement fallback
 └─ WebFetch artifact write failure -> fixed safe save-failure detail

File tools / restricted audit
 ├─ realpath both root and target
 ├─ commonpath containment, including allowed_root="/"
 ├─ invalid path -> structured failure, never an escaping ValueError
 └─ failure details never include model path or host root
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

环境代理禁用是当前版本的强制安全行为，不提供隐藏开关或环境变量回退：

- `ProxyHandler({})` 不安装任何 proxy handler，因此 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 和大小写变体均不会参与路由。
- `NO_PROXY`/`no_proxy` 只能告诉一个已经启用的代理 handler 哪些目标绕过代理，不能重新启用被空 mapping 移除的代理；它不是临时规避方法。
- 依赖企业代理才能出网的部署会在 WebFetch 和 `/search` 上直连失败。当前可用的迁移方式只有：在允许直连的网络运行、由用户在 ForgeAgent 外预取并把文件放入 `allowed_root` 后通过 FileRead 处理，或显式配置一个由用户信任且自行承担代理策略的 MCP fetch 工具。最后一种方式不是 WebFetch 的透明代理，也不改变 WebFetch 的 SSRF 契约。
- CLI 对普通网络失败继续使用稳定失败类别，不根据错误文本猜测“可能需要代理”；README、威胁模型和 `[SECURITY][BREAKING]` 发布说明必须直接列出上述行为和替代路径。

未来代理支持不能简单恢复默认 `ProxyHandler`。常规 forward proxy 会在代理端重新解析目标，使 ForgeAgent 无法证明实际连接地址仍是本地校验过的 IP。未来设计必须显式选择并记录以下一种信任模型：

1. **trusted forward proxy**：用户显式把代理声明为受信任的出网/SSRF 执行边界，ForgeAgent 只校验代理端点与配置，不声称自己验证最终目标 IP。
2. **guarded tunnel proxy**：ForgeAgent 逐跳解析并校验目标，把精确 vetted IP 交给 CONNECT/tunnel，同时保留原 hostname 用于 TLS SNI、证书和 Host 校验。该模式兼容性更窄，但保留当前 SSRF 不变量。

未来配置形态只能作为占位示例：

```yaml
network:
  mode: direct  # future: trusted_proxy | guarded_tunnel
  proxy:
    url: http://proxy.example:8080
    no_proxy:
      - example.internal
```

当前版本不解析这些字段，也没有任何可用 proxy mode。实现依赖显式空 ProxyHandler 屏蔽环境代理，不会通过 `os.environ.pop()` 修改进程全局环境；后者会影响并发调用方并制造新的竞态。

### 4.4 消费端异常收敛

`guarded_urlopen()` 继续只负责 scheme、代理、重定向和连接地址边界，不吞掉调用方读取响应时发生的错误。两个消费者分别维护自己的稳定结果契约：

- WebFetch 在打开、读取和关闭响应的同一 `try` 边界内处理 `SSRFGuardError`、`OSError`、`http.client.HTTPException` 和非法模型 URL 产生的 `ValueError`。SSRF 拒绝返回 `WebFetch blocked by network policy`；其余请求/协议失败返回 `WebFetch request failed`。
- WebFetch 完成响应读取后，单独包围 artifact `write_text()`；写入 `OSError` 返回 `WebFetch response save failed`。不得把一次成功请求误报为网络请求失败。
- `/search` 将 `OSError` 和 `http.client.HTTPException` 收敛为既有 `ERROR_UNAVAILABLE`。远端声明未知 charset 时不把可用响应判为网络故障，而是退回 UTF-8 `errors="replace"` 解码。
- 不使用覆盖整个工具主体的 `except Exception`。断言错误、类型错误和实现缺陷仍应在测试中显式暴露。

捕获 `http.client.HTTPException` 基类是有意的：Python 3.11+ 中 `IncompleteRead`、`BadStatusLine`、`InvalidURL`、`LineTooLong`、`UnknownProtocol`、`UnknownTransferEncoding` 和 connection-state errors 均继承该类且多数不继承 `OSError`；`RemoteDisconnected` 同时落入 `OSError` 和 HTTP 异常体系。测试不逐一伪造所有内部状态类，而是覆盖可由本调用路径产生的代表性叶子：open 阶段 `InvalidURL`、status/header 阶段 `BadStatusLine`/`LineTooLong`、body 阶段 `IncompleteRead`、disconnect 阶段 `RemoteDisconnected`，并用继承断言锁定这些类别仍被基类捕获。

## 5. 工具确认设计

### 5.1 保留现有接口

`Confirmer = Callable[[BaseModel], bool]` 保持不变。CLI 内部增加一个小型 formatter，由 `make_console_confirmer()` 调用：

- `MCPArgs`：显示经过 `mask_secrets()` 的 `server:tool`。arguments 递归遍历 dict/list；原始键名匹配现有 `is_secret_name()` 时，无论值长度都显示 `<redacted>`；展示用 mapping key 本身也必须经过同一组 `sensitive_env_values()` 的 `mask_secrets()`，其他字符串 value 再替换已知环境 secret value。递归过程一次读取并传递 secret set，不能只保护 value 而让 secret 出现在 key。server/tool 不是可信元数据，不能绕过提示脱敏。
- `WebFetchArgs`：通过 `urllib.parse` 清除 URL userinfo 和 fragment，替换敏感 query key 的值，再用 `mask_secrets()` 处理已知 secret value。path 在匹配前 percent-decode。hostname 先 percent-decode，再以 ASCII DNS 大小写不敏感语义执行一次从左到右、非重叠替换；候选 secret 按长度降序排列，确保同一位置优先匹配最长值。替换只作用于 hostname component，不对原始 URL 做正则改写。重建前重新编码 hostname；percent-decode 后产生的 `@`、`/`、`?`、`#` 等结构字符不得直接进入 netloc，无合法 hostname 表示时返回 `<redacted malformed URL>`。IPv6 身份由原始 netloc 是否使用方括号决定：只有原始 bracketed host 才允许解码后的 `:`，普通 DNS hostname 中 encoded `:` 视为 malformed；合法 IPv6 和 RFC 6874 zone-id 保留结构化方括号与编码。
- `FileWriteArgs`：不回显 content。绝对路径在 cwd 内时显示项目相对路径，在 cwd 外时只显示 `.../<basename>`；相对路径保持规范化相对形式。安全路径摘要仍需经过 `mask_secrets()`，避免 basename 或相对路径段携带已知环境 secret。提示同时显示 `len(content)` 计算的字符数，并固定标记为 `characters`，不得误标为 bytes。
- 其他 `BaseModel`：只显示类型名，避免访问不存在的字段或意外回显敏感数据。

全局 `mask_secrets()` 的既有契约保持不变：它按敏感环境变量名收集长度至少 8 的值，再做最长值优先替换。结构化键脱敏只属于 confirmer formatter，避免改变 executor/MCP output 的既有行为和误报面。

WebFetch formatter 在一次调用开始时只读取一次 `sensitive_env_values()`，并按组件执行：先丢弃 userinfo/fragment，再处理 hostname、path、query。hostname 只经过局部 case-insensitive helper；path 和非敏感 query key/value 继续使用全局 case-sensitive `mask_secrets()`；敏感 query key 的 value 直接替换。重建后不再对完整 URL 做第二次 `mask_secrets()`，避免跨组件匹配、重复编码或对 redaction marker 二次替换。

输入仍只接受 `y`/`yes`。EOF、空输入和其他值全部拒绝。

### 5.2 终端选择与 REPL 路由

- REPL 只有在 stdin 与 stdout 均为 TTY 时才创建并传入 confirmer，不再以 MCP 是否存在为条件。`repl()` 接受 `confirmation_available: bool | None = None`；未指定时从 `sys.stdin.isatty()` 与 `console.is_terminal` 计算，不能因函数名为 REPL 就假定存在交互通道。
- 单次 `run` 只有在 `sys.stdin.isatty()` 与 `console.is_terminal` 同时为真时传入 confirmer。
- 非 TTY 的 confirmer 不读取确认输入，并向 Task 传 `None`；REPL 自身仍可从管道读取普通 goal。WebFetch/FileWrite 和仍需确认的 MCP 调用返回 `rejected: no interactive confirmation channel available`，与用户在 TTY 中明确回答 no 的 `not approved by the user` 区分。
- `--interactive` 继续只决定 Survey 是否获得 asker，不参与 confirmer 选择。
- MCP `autoApprove` 是用户配置中的显式预批准，继续在调用 confirmer 前短路；因此它可以在非 TTY 执行。WebFetch/FileWrite 没有对应例外。
- M9 声明的一个里程碑裸词兼容期已经结束。REPL 只把 `/model`、`/reload`、`/mcp` 等 slash-prefixed 输入解释为命令；裸 `models`、`reload`、`mcp` 和 `mcp ...` 都作为普通任务目标交给模型。顶层 CLI 子命令 `forgeagent models` 不属于 REPL 兼容层，继续保留。

### 5.3 执行结果的最小披露

实施期 thorough review 发现确认后的工具结果同样会进入 Step feedback 和 CLI console。用户于 2026-07-13 选择把该问题纳入当前 change，并批准固定安全结果消息方案：

- WebFetch 捕获 `SSRFGuardError` 时返回固定 `WebFetch blocked by network policy`；打开、读取或关闭响应时发生 `OSError`、`http.client.HTTPException` 或非法 URL `ValueError` 时返回固定 `WebFetch request failed`；response 已读取后，artifact digest/filename 推导、canonical path 验证或写入发生 `ValueError`/`OSError` 时返回固定 `WebFetch response save failed`。这包括 URL 的未配对 surrogate 位于不会发往服务器的 fragment、网络层成功但完整 URL 无法按 UTF-8 编码的情况。不得把底层异常、原始 URL、hostname 或宿主路径写入 `ToolOutcome.detail`。
- WebFetch 的可预测 artifact 名称直接位于 `allowed_root`，写入前必须交给 `_validate_path()`，并使用其返回的 canonical target；预置同名 artifact symlink 指向 root 外时返回 `WebFetch response save failed`，不得触碰外部目标。`allowed_root` 自身可以是用户明确配置的 symlink alias，其 `realpath` 才是授权根。通用后代/祖先 symlink component 解析继续由 File 工具的 `_validate_path()` 用例覆盖；当前 artifact filename 不虚构不存在的中间目录。该检查与 FileWrite 共享现有函数，不新增 artifact policy 层。
- FileWrite 通过 project-root 校验并成功写入后，只返回由已解析目标相对 canonical `allowed_root` 计算出的 project-relative 路径：`base = Path(os.path.realpath(ctx.allowed_root))`，再对 `_validate_path()` 返回的 `resolved` 使用 `relative_to(base)`。不复用模型提供的原始路径，也不假定 `ctx.allowed_root` 已经是绝对路径。
- FileWrite 写入阶段发生 `OSError` 或路径语法产生 `ValueError` 时返回固定 `FileWrite failed`。越界、无交互通道和用户拒绝继续使用既有固定消息。
- FileRead/FileList 的路径校验和文件系统失败分别返回固定 `FileRead failed` / `FileList failed`，不回显异常文本、模型提供的绝对路径或 canonical root。MCP 结果契约和全局 `mask_secrets()` 行为保持不变。
- 不新增通用 result sanitizer。固定消息牺牲部分底层诊断细节，以避免平台相关异常字符串重新引入 URL、hostname 或宿主绝对路径泄漏。
- 确认摘要最终作为 Rich `Text` 的 literal segment 输出，不把完整 f-string 交给 markup parser。MCP identifier、递归 arguments 的展示 key/string value 和 FileWrite display path 在 secret masking 后还要规范为单行可见文本：C0/C1、DEL、CR/LF、Unicode line/paragraph separator、Unicode category `Cf` 的格式控制符（含 bidi embedding/override/isolate 与 directional marks），以及 category `Cs` 的未配对 surrogate，使用 `\\xNN`/`\\uNNNN`/`\\UNNNNNNNN` 转义；普通 `[`/`]` 保持字面值。这样模型内容既不能闭合样式标签、伪造第二行提示、用不可见方向控制重排审批文本，也不能在 UTF-8 终端编码阶段触发审批前崩溃。整个摘要由 literal segments 组成；该 helper 只服务确认显示，不扩展为通用 sanitizer。

测试必须覆盖：percent-encoded、大小写变化和重叠的 hostname secret；encoded `@`、`/`、`?`、`#`、`:`；普通 IPv6 与 zone-id 字面量；userinfo/fragment 丢弃；hostname 局部 helper 与 path/query 全局 `mask_secrets()` 不重复或漏脱敏；携带原始 URL/hostname 的 WebFetch guard/network/HTTP protocol 异常；WebFetch artifact 写入异常包含绝对路径；未配对 surrogate fragment 在 response 成功后的 artifact naming 固定失败；预置同名 artifact symlink 指向 root 外且外部目标不变；mock `_validate_path()` 返回不同 root 内 target 时实际写入该返回值；FileWrite 使用绝对路径和相对 `allowed_root="."` 时只回显 canonical project-relative 路径；FileRead/FileWrite/FileList 的越界、非法路径和文件系统异常不回显宿主路径。失败结果还需通过现有 Step feedback 与 CLI `render_outcome()` 路径验证不再泄漏。

### 5.4 共享路径边界

WebFetch artifact 与 FileRead/FileWrite/FileList 在主进程内复用 `_validate_path()`；`_sandbox_worker._install_audit_hook()` 保持独立实现，避免为了两个进程边界引入共享模块，但使用同一不变量：

1. 用 `os.path.realpath()` 得到 canonical root 和 target。
2. 用 `os.path.commonpath((root, target))` 判断包含关系；`realpath()` 或 `commonpath()` 因不同驱动器、NUL 等非法路径抛出的 `ValueError` 视为不允许。
3. 比较时遵循平台路径语义，允许 root 自身和任意真实子路径，因此 `allowed_root="/"` 不再错误拒绝 `/tmp/...`。
4. 安全边界异常不携带输入路径或 root。工具层转换为上述固定失败消息；restricted worker 保留 `PermissionError` 类型，但消息只说明访问位于 allowed root 外。

`_validate_path()` 返回 canonical target，因此校验后替换模型最初提供的 symlink alias 不会改变实际写入目标。仍存在一个更窄但真实的 TOCTOU：外部并发写者若在校验后、打开前把 canonical target 本身或其某个祖先路径组件替换为指向外部的 symlink，后续按 pathname 打开仍可能越界。实证 probe 已复现 ancestor-component swap；final-target swap 具有同一 pathname race 根因。

本 change 不用“再做一次 realpath/lstat”伪装成修复，因为检查与打开之间仍有竞态；也不引入 POSIX-only 的逐组件 `openat(dir_fd, O_NOFOLLOW)`、Linux `openat2(RESOLVE_BENEATH)` 或平台专用 fd-path 反查。完整消除需要重写 FileRead/Write/List 的文件描述符接口并处理 Windows 兼容，超出本次最小加固。

残余威胁按档位记录：restricted/container 的模型执行块在工具调用前已经结束，不能靠普通模型代码保留一个并发线程稳定制造竞态；但 trusted 同进程代码、用户配置的 MCP 进程或宿主其他进程仍可能并发修改目录。当前保证是阻止静态 symlink 逃逸、修复 root predicate、收敛非法路径和错误文本；不把 File 工具描述为抵抗恶意宿主并发写者的 OS 级边界。

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

`MCPManager.connect()` 保持并发连接和 per-server unavailable 状态，但并发不仅指 holder task 同时创建：全部 enabled holder 必须在第一次 await 前启动，ready wait 从同一个 monotonic 起点并发计时，外层 synchronous facade timeout 也使用同一 `connect_timeout` 加固定调度余量而不乘 server 数。因此 N 个无响应服务的初始等待接近一个 `connect_timeout`，而不是 N 倍 timeout。单个超时 holder 仍保留 generation slot；它后续只能在 generation、desired state 和 closing barrier 都匹配时发布，required 失败触发的 close 则会把它纳入 snapshot 清理。

新增只读查询返回 enabled required failures，例如 `required_failures() -> dict[str, str]`。holder 的公开 unavailable 状态只包含固定类别和异常类型，不保存或输出异常字符串；`server_status()` 与 `required_failures()` 在返回前仍用既有 secret-value mask 做防御性处理。optional 黄色诊断、required startup error 和 REPL `/mcp status` 因而都不会泄漏 command、args、env、server content 或异常携带的 secret。

`build_mcp_manager()` 的流程：

1. 加载配置并构造 manager。
2. 无 enabled server 时返回 `None`。直接使用 `MCPManager` 时，`connect()` 在无 enabled server 的情况下不创建 loop 且保持可在修改 desired config 后再次显式 connect 的 pre-start 状态；`enable()` 本身不隐式创建一个此前不存在的 manager/loop。
3. 调用 `connect()`。服务级连接失败继续由 holder 收敛为状态；initial holder submission/result 发生普通 manager 基础设施异常时，`connect()` 先对已发布 loop/holder 执行 bounded close，再让组装层转成不含异常文本的 `MCPStartupError`。cleanup 抛出的 `asyncio.CancelledError` 等非进程控制 `BaseException` 只能记录固定类型，不能替换 primary startup error；新的 `KeyboardInterrupt`/`SystemExit` 仍按进程控制语义传播。primary 本身是控制异常时也必须先 best-effort cleanup，再原样传播。
4. 收集 required failures。
5. 若非空，先调用不会抛出普通 `Exception` 的 `close()`，再抛 `MCPStartupError`，消息只包含服务名和已脱敏的固定状态。`close()` 进入后第一项动作必须是设置 closed state，避免二次错误让启动清理重新进入。
6. 否则打印全部状态；optional unavailable 使用黄色诊断，返回 manager。

CLI 捕获 `MCPStartupError`，打印单行错误并返回 2。run 与 REPL 都使用同一构造函数，因此行为一致。

运行期 `/mcp enable|disable` 保持用户显式控制。required 只约束启动，不会因为会话中状态变化强制退出 REPL。

### 7.3 有界关闭

manager 构造参数增加仅供内部/测试注入的 `shutdown_timeout=10.0` 和 `thread_join_timeout=2.0`。不写入 mcp.yaml。`connect_timeout=15.0` 已经是现有的每服务连接上限，超时 server 会被标记 unavailable；本 change 不增加重复的用户配置。

`close()` 顺序：

1. manager 增加内部 `_shutdown_future` 引用。用 `getattr(self, "_closed", False)` 检查重复调用。首次调用立即置真并执行完整 holder shutdown；重复调用不得重新提交 shutdown coroutine 或重新等待 holders，只能再次 cancel 已保存的 future、唤醒既有 loop-owned drain、等待 completion event并 bounded join。只有 cleanup completion 已证明且线程停止时才关闭 loop并清理引用。
2. 未创建 loop 时直接清理引用并返回。
3. 用 `time.monotonic()` 为每次公开 `close()` 建立唯一绝对 deadline：当前时间加 `shutdown_timeout + thread_join_timeout`。主线程等待 shutdown facade 时必须为 join 预留 `thread_join_timeout`，所有公开等待阶段只读取 `remaining = max(0, deadline - monotonic())`，不累计相对 timeout。该 deadline 约束调用方等待时间，不授权 loop 在 async context finalizer 尚未完成时提前停止。
4. `_holders` 的值是 `(generation, holder_task, stop_event)`。主线程提交前只能保存 server-name fallback 供超时诊断；精确 slot snapshot 必须由 shutdown coroutine 在 loop thread 设置 closing barrier 后创建，避免与已排队的 enable/disable reconcile 竞态。shutdown 只处理该 loop-owned snapshot 中的 `(name, generation, task, stop)`，不会漏掉刚启动的 holder，也不会 cancel 后续 generation。
5. loop thread 创建并发布唯一 `_shutdown_task`。`_ensure_shutdown_task(deadline)` 在第一次 await 前原子设置 closing barrier、创建精确 slot snapshot并启动 drain；重复 ensure 返回同一 task。drain 设置 snapshot slot 的精确 stop event，正常阶段最多消费 5 秒并为 join 保留预算，再 cancel/await 仍 pending 的精确 holder。公开 deadline 到达而 holder 仍在 async context cleanup 时，`close()` 返回，但 shielded drain 必须留在仍运行的 loop 上继续等待；它不能为了满足调用 deadline 提前 `loop.stop()`。session、status、tools 和 holder slot 的写入/删除都必须验证 generation；holder slot 只能在 task 已 done 后由 loop-owned finalizer/reconcile 删除。
6. `_shutdown_task` 对每个 holder/result/finalizer 的普通 `Exception` 分别收集并只记录固定异常类型，然后执行一次幂等的最终清理检查；普通异常不得让 task 提前失败并绕过其余 holder。只有 snapshot task 全部 done、精确 slot/session 已完成条件清理且没有 replacement 后，才设置 `_shutdown_complete` 并请求 `loop.stop()`。若最终不变量仍不成立，则保留 complete 未设置和全部证据；同一个 task 等待一个 loop-owned retry event，不返回、不 busy-loop。重复 close 的 `_ensure_shutdown_task(new_deadline)` 只唤醒这个既有 task做下一次有界清理尝试，不能创建第二个 task或第二份 snapshot。loop 停止且 completion 已证明后，主线程才可丢弃 `_shutdown_task` 引用，这不属于活跃 loop 上的跨线程 mutation。
7. 主线程保存 `asyncio.run_coroutine_threadsafe(_wait_for_shutdown(), loop)` 返回的 `_shutdown_future`；`_wait_for_shutdown()` 在 loop 内用 `asyncio.shield(_shutdown_task)`，因此 concurrent future timeout/cancel 不会取消真正的 drain。若 facade 提交本身失败，主线程只能关闭未调度 coroutine并向仍存活的 loop best-effort 提交 `_ensure_shutdown_task` callback；它不能因为 `_holders`、`_sessions`、`_lifecycle_tasks` 暂时为空就在 caller thread 设置 `_shutdown_complete`，因为排队 callback、尚未发布的 task 或未跟踪的 call 仍可能存在。若 outer coroutine 在 ensure 前即被取消，同一 fallback 创建或复用唯一 task，绝不重复 snapshot/holder shutdown。主线程 cancel 但保留 `_shutdown_future`，并使用 pre-submit name fallback 作诊断。
8. 主线程不在 cleanup incomplete 时直接 stop loop。第一次 close 通过 concurrent facade 等待；该 future 一旦取消就不可复用，因此重复 close 在唤醒既有 drain 后，改用线程安全的 `_shutdown_complete.wait(max(0, remaining - thread_join_timeout))` 等待同一 task 的 completion，不创建第二个 coroutine/future/task。随后 `thread.join()` 使用 `min(thread_join_timeout, remaining)`。
9. 只有 `thread.is_alive() is False` 且 `_shutdown_complete` 已由 loop-owned drain 或已批准的 pre-holder startup rollback 设置，主线程才能尝试 close loop；只有 loop close 成功后才清空 shutdown future/task、holders、sessions、lifecycle operations、loop、thread。loop close 抛普通异常时 public close 只记录固定类型并保留全部 stopped-loop 证据，重复 close 再次尝试。thread 已死但 completion 未被证明时，即使 holder/session/lifecycle 容器为空或 `_shutdown_task` 为 `None`/done，也按 incomplete 处理并保留 shutdown future、排队 callback 与 loop 引用。warning 至少包含固定 thread name、ident、alive 状态、经 secret-value mask 的 snapshot pending server 名称和 timeout，不输出 MCP arguments、env、server content 或 stack。
10. `_stop_and_join()` 必须在 join 返回后重新读取 `_shutdown_complete`，不能使用 join 前缓存值；若 drain 在 join 期间完成且线程已经停止，同一次 close 应立即关闭 loop 和清除引用，不得误报 incomplete 或强制用户再调用一次。
11. 公开 `close()` 在设置 closed state 后用 `try/except Exception/finally` 包围内部操作。Exception 只记录 warning并继续 best-effort drain/join；KeyboardInterrupt/SystemExit 不被吞掉。cleanup incomplete 时无论 thread 是否暂时存活，都不得从主线程清空 loop-owned slot/session 引用。
12. 返回 None，不向调用方传播普通关闭异常。

正常和 holder 无响应 fixture 必须证明 SDK 的进程树清理可以在上限内结束子进程。更极端的情形是 event-loop thread 本身被同步代码卡死：cancel 和 SDK context exit 可能尚未执行，daemon thread 可能暂时保有 transport、file descriptor，甚至 MCP child process。Python 不提供安全强杀线程的 API，manager 也没有 SDK child handle 可供主线程可靠终止，因此 CLI 仍按 deadline 返回，warning 明确标记 `shutdown incomplete; resources may remain` 并保留上述诊断证据。若线程随后停止，第二次 `close()` 必须关闭遗留 loop 并清除引用；若仍存活，第二次调用仍只能在自己的新 absolute deadline 内等待 completion 与 join。默认不抓取线程堆栈：`sys._current_frames()` 是 CPython 私有诊断接口，输出冗长且可能包含宿主路径；固定线程身份和 pending holder 足以定位本层问题。

### 7.4 Loop-owned reconcile 与 generation token

连续两轮窄修复证明，仅在 `close()` 周围补 timeout/cancel 不能解决 `enable()`、`disable()`、holder `finally` 和 startup publication 之间的所有权竞态。生命周期改为以下单一规则：**loop thread 决定 desired state 如何变成 holder/session slot；每个 slot 带 generation，旧代只能清理自己。**

内部结构固定为：

- `_ServerState.generation: int`：只在 loop thread 每次真正启动新 holder 时递增；initial connect、显式 enable 和 runtime replacement 使用同一 `_start_holder()` 分配入口。
- `_ServerState.tearing_down_generation: int | None`：只绑定正在 cleanup 的精确 generation，不能用跨代 bool。disable、当前 session 的 call failure，或用户对 unavailable/finishing slot 的显式 enable 会设置它；新 generation 启动时清空，旧代 callback 只有 generation 匹配时才能修改。
- `_ServerState.restart_after_generation: int | None`：只表示用户 enable 已明确要求在该代 cleanup 后 replacement。disable/close 清空它；enable 遇到 tearing-down 或 unavailable-finalizing slot 时设为该代；initial connection failure 和 call failure 本身都不设置，避免永久配置错误或一次工具失败触发未声明的自动重连。
- `_holders: dict[str, tuple[int, asyncio.Task, asyncio.Event]]`，slot 原子携带 generation、task 和该代专属 stop event；删除 `_ServerState.stop` 单值字段，避免 close/disable signal 到错误代。
- `_sessions: dict[str, tuple[int, object]]`。`call_tool()` 只使用 generation 与当前 state/holder slot 一致的 session。
- `_lifecycle_tasks: set[asyncio.Task]` 只跟踪 enable/disable/initial-connect 的 loop-owned operation，不包含 tool call。同步 waiter 可取消，但 operation 必须通过单独的 loop callback 必达启动；task 完成时由 done callback 消费结果并从集合移除。shutdown entry 在 loop 内对该集合取精确快照并取消/等待，最终不变量还要求集合为空，防止停止 loop 时遗留 waiter 背后的 operation。
- `_shutdown_task: asyncio.Task | None` 只由 loop thread 创建和发布；`_shutdown_future` 只是主线程等待该 task 的 concurrent facade。两者不得混为同一 completion 证据；仅在 loop 已停止且 completion 已证明后，主线程才可随其余引用一起清空它。
- `_lifecycle_barrier: threading.Lock` 只仲裁主线程首次 `close()` 发布 `_closed=True` 与 loop thread `_start_holder()` 的无 await 分配临界区。`_start_holder()` 持锁后再次检查 closed/closing，再一次性分配 generation、创建 task、发布完整 slot并注册 finalizer；`close()` 持同一锁设置 `_closed`。若 close 先获得锁，不得递增 generation；若 start 先获得锁，slot 必须在释放锁前可被随后 loop-owned shutdown snapshot 观察。锁不得包围 await、SDK 调用或 holder cleanup，也不扩展成通用多调用线程支持。
- `config.enabled` 是 desired state。loop 存在时，runtime enable/disable 必须通过提交到 loop 的 reconcile coroutine更新 desired state 和 slot，不从主线程直接替换 `_holders`/`_sessions`；manager closed/closing 后 connect/enable 不得创建 generation。
- holder 驱动的 `status`、`tools`、session publish/finally，以及 call failure 的 session invalidation，都必须在 loop thread 检查 generation 后执行。同步 `call_tool()` 不从主线程读取或持有 ClientSession；它提交 loop-owned wrapper，由 wrapper 在实际执行时原子选择仍匹配 current holder 的 `(generation, session)`、await SDK call，并在失败时只 invalidation/停止该 generation。旧 session 不会在 replacement 已发布后才被主线程重新提交。
- holder 在 `initialize()`/`list_tools()` 等 await 后、发布 available/session/tools 前，必须再次验证当前 holder slot 仍匹配自身 generation、desired enabled、stop 未设置且 manager 未 closing；任一条件不满足就退出 context并只做本代 cleanup。per-start ready event 无论成功、失败或被 supersede 都必须设置，避免 `_start_holders()` 等待到额外 timeout；ready timeout 写 unavailable 前也必须复核该 generation 的 ready 尚未设置且没有成功发布，不能用迟到 timeout 覆盖 available。

每个 server 的状态转换：

```text
disabled or unavailable/no slot
  -- explicit enable reconcile --> desired enabled + allocate gen N --> alive(gen N)

alive(gen N)
  -- disable reconcile --> desired disabled + tearing_down_generation=N
                          + restart_after_generation=None
                          + status disabled/tools empty + signal stop(N)
  -- active call failure --> tearing_down_generation=N + status unavailable/tools empty
                             + remove session(N) + signal stop(N)
  -- enable reconcile while tearing_down/unavailable --> desired enabled
                                                         + restart_after_generation=N
                                                         + status restarting/tools empty
                                                         + keep gen N slot

tearing_down(gen N)
  -- holder task done --> loop finalizer removes only exact (N, task/stop/session)
  -- restart_after=N + desired enabled --> allocate gen N+1 --> alive(gen N+1)
  -- no restart intent/desired disabled/manager closed --> no replacement
```

`disable()` timeout 只表示同步调用方停止等待，不取消 loop-owned holder teardown，也不摘除 slot。随后 `enable()` 看见 tearing-down slot 时不得立即覆盖；它只更新 desired enabled 并为该 generation 记录 restart intent。holder coroutine 的 `finally` 只做 generation-conditional session/status cleanup；task 真正 done 后，loop-owned done finalizer 才移除精确 holder slot并调用 reconcile。reconcile 同时验证最终 desired state 与 restart intent，必要时启动 replacement。测试 `test_enable_during_timed_out_disable_restarts_after_old_holder_cleanup` 锁定该顺序；另加 `test_re_enable_old_holder_finally_does_not_delete_replacement_session`，证明旧 generation 无法删除新 session或把新 status/tools 改为 unavailable。

enable 遇到 status unavailable 且同代 task 正在 finally 时，必须把该 generation 标为 tearing down并设置 `restart_after_generation`，而不是因 slot 尚在就视为幂等成功；task 已 done 时先走同一 finalizer。这样显式 retry 不会在 done-callback 竞态中丢失，也不会自动重试从未成功建立的永久失败服务。当前 active session 的 call failure 在 loop 内清空 tools/session、设置本代 teardown 并 signal 本代 stop，但保持 unavailable 且不自行设置 restart intent；用户随后显式 enable 才触发 replacement，保留既有“调用失败后降级、由用户决定重试”的外部语义。调用前，session generation 必须同时匹配 `state.generation` 和当前 holder slot generation；任一不一致都返回无 live current session，不调用 stale SDK object。

slot finalization 使用单一幂等函数 `_finalize_holder_slot(name, generation, task)`。`_start_holder()` 在 `_lifecycle_barrier` 临界区内同步创建 generation、ready、stop、task 和原子 slot，并给 task 注册 done callback；callback 在 loop thread 调 finalizer。task/coroutine 创建任一点失败都要关闭尚未调度的 coroutine、把本代状态收敛为固定 unavailable 类别且不留下半个 slot，并向 initial/runtime waiter 返回立即 ready-failure，不能再消耗一次 `connect_timeout`。禁止在 `create_task()` 返回后因 close barrier 已改变而 cancel 后直接 return：若 task 已创建，它必须已进入 generation slot和 finalizer ownership；临界区规则则保证 shutdown snapshot 不会漏掉它。shutdown 的 `asyncio.wait()` 不得假设 done callback 已先运行，因此 await snapshot task 后也显式调用同一 finalizer。finalizer 只有在当前 slot 精确匹配时才 pop；只有 `restart_after_generation` 匹配、desired enabled 且 manager 非 closed/closing 时，才清空 restart intent并同步调用 `_start_holder()` 分配下一代，否则不 restart。该函数不 await、不创建未追踪 reconcile task；done callback 还必须消费 task 的普通异常以避免后台 warning。

shutdown 对 snapshot lifecycle operation 的 `cancel()` 也按 slot 隔离普通 `Exception`；单个自定义 task/future 的 cancel hook 失败不能终止唯一 drain、跳过其余 holder stop/cancel，或使 repeated-close retry event 永远不可达。

同步 lifecycle API 的等待同样分成 ownership 与 facade，但不能把 `run_coroutine_threadsafe()` 返回的 future 直接等同于纯 waiter：loop 尚未开始 coroutine 时取消该 future 会连 reconcile intent 一起丢失。每次 enable/disable/initial-connect 因此先构造一个 loop-owned operation；同步 facade 只等待一个 shielded wrapper。若 `Future.result()` timeout 或 caller 收到控制异常，主线程取消 concurrent waiter，并用 `call_soon_threadsafe()` 幂等确保 operation 已经或最终会在 loop 启动。enable/initial-connect operation 只等 generation-specific ready，disable operation 用 `asyncio.shield(holder_task)` 等本代退出，holder/slot 始终由 loop 拥有。operation task 进入 `_lifecycle_tasks`，完成回调消费结果并摘除；close 的 loop entry 排在前序 ensure callback 后，先建立 closing barrier 和精确 holder/lifecycle snapshots，再取消 lifecycle operation、signal holder stop 并完成统一 drain。这样 timeout 不丢 desired-state intent，close 也不会在停止 loop 时遗留未跟踪 operation。initial enabled holders 在第一次 await 前全部创建，ready waits 并发使用同一 start deadline。

所有在同步 caller thread 上运行的 facade/startup/close cleanup 使用同一个异常优先级：若 primary 已是 `KeyboardInterrupt`/`SystemExit`，始终保留该对象；若 primary 是普通异常或 timeout，而后续 coroutine close、future cancel、must-deliver scheduling、gate release/stop/join 或 shutdown fallback 首次产生进程控制异常，则继续其余有界 cleanup 后传播该首个控制异常；普通 cleanup 异常只记录固定类型，绝不替换 primary。不能在一个 cleanup site 修复而让相邻 site 继续吞掉控制异常。loop-owned lifecycle operation 本身或其 task-creation cleanup 产生的进程控制异常不能直接越过 asyncio Task 边界，否则 `run_forever()` 会退出；它必须被私有 result value 捕获，穿过 concurrent facade 返回，再由同步 `_submit()` 在 caller thread 解包并抛出同一对象。真实 loop/thread 测试必须证明 caller 收到正确对象、loop 仍存活且没有 unretrieved-task warning。

该 caller-thread 规则不适用于 holder task 分配、holder/`call_tool` coroutine 内 MCP SDK/测试 double，或 done-finalizer 自动启动 replacement 时产生的 `KeyboardInterrupt`/`SystemExit`：这些 loop-local background 路径没有观察到操作系统主线程控制信号。它们必须隔离为对应 generation 的固定 unavailable/structured call failure，完成 ready/finalizer，清除半发布或失效的 slot/session/tools、signal 精确 holder且不形成 restart loop；让异常直接穿过 asyncio Task 或 callback 会击穿独立 loop thread，却无法安全地向主线程原样传播。`asyncio.CancelledError` 保持任务取消语义，不被 `call_tool` failure 分支吞掉。操作系统送达主线程的真实用户中断仍由上述同步 facade 路径传播。真实 loop 测试锁定显式 enable、finalizer replacement 和 SDK call 三条路径隔离后 loop 仍可清理/服务其他 generation，且状态/结果不包含异常文本。

`close()` 先在主线程持 `_lifecycle_barrier` 置 `_closed=True`，再由 loop-owned shutdown entry 设置 `_closing=True` 并创建 `(name, generation, task, stop)` snapshot。所有已排队 reconcile 在启动 generation 前都在同一 barrier 临界区复核 closed/closing；shutdown entry 之后的 reconcile 也不得启动。disable teardown 中的 holder 在 task done 前始终留在 `_holders`，因此 snapshot 不会漏掉。stop、cancel 与 conditional remove 都使用 snapshot generation。主线程仅保存 pre-submit name fallback 供 hard-stuck warning，不跨线程复制 Task slot作为权威 snapshot。

`enable()`/`disable()` 仅在 initial connect 之前（`_started=False`、loop 尚未创建、manager 未 closed）可以直接更新配置 desired state；loop 存在时必须走 reconcile。manager closed/closing 后两者可返回“server name known”，但不得重启资源；`connect()` 在 closed manager 上也不得 reopen。增加 enable-after-close 与 close/enable queue-order 回归。全 disabled 配置在 CLI 组装层必须在调用 `MCPManager` 构造器之前返回 `None`，本 change 不新增“无 manager 的 REPL 动态建 loop”能力。

REPL `/mcp enable|disable` 是同步 facade 的用户边界。若 manager waiter 抛 `TimeoutError`，loop-owned operation 仍按 must-deliver 规则继续；CLI 捕获该 timeout，输出不含异常文本的固定 `MCP <action> pending: <masked-server>` 状态并返回 handler，不退出 REPL，也不谎报最终 available/disabled。未知 server 与非 timeout 控制异常保持原语义。

同步 facade 的线程契约保持不变：CLI/Task 使用单一调用线程，不承诺多个 OS caller thread 同时调用 enable/disable/call/close。这里的 overlap 专指同步 `_submit(...).result(timeout)` 已返回或超时、但先前 loop operation 仍在运行，随后同一 caller 发出下一操作。只新增 lifecycle operation 集以证明 shutdown 完整性，不增加通用 tool-call registry。SDK `call_tool` 继续依赖 inner read timeout 早于 outer facade timeout；若 loop 被同步代码完全卡死，未完成 call 与 transport 一并属于 7.3 已记录的 hard-stuck residual。

Loop startup 也是 transaction：先创建局部 loop、publication gate、cancel event 和固定名称 thread；worker 用短周期 gate wait 同时检查 cancel，未见 published gate 时不得进入 `run_forever()`，即使 gate release 本身在真正 set 前抛错也能因 cancel 退出。`connect()` 在 closed manager 上直接返回且不得 reopen。只有 manager 的 `_loop/_thread/_started` 发布成功后才 release gate。`Thread.start()`、状态发布或 gate release 任一点抛出 `BaseException` 时：保存 primary，设置 cancel 并 best-effort release gate；无论 worker 尚未检查 cancel 还是已经进入 `run_forever()`，都 best-effort `call_soon_threadsafe(loop.stop)`，再在 `thread_join_timeout` 内 join。rollback 内每个 cleanup 操作独立捕获后续 `BaseException`、只记录固定异常类型，并按上一段 caller-thread 规则选择最终异常：primary control 保持 identity；ordinary primary 遇到的首个 cleanup control 升级为最终异常；其余 cleanup 仍继续。线程停止且 `loop.close()` 成功后才清空 refs、恢复 `_started=False`/`_closed=False` 与未设置的 shutdown state，使 manager 可重试。若线程仍活，或线程已停但 `loop.close()` 抛普通异常，都不能清空 refs：保留 `_loop/_thread`、置 `_started=True/_closed=True`，因该 pre-holder rollback 没有 holder 而把 startup cleanup 标为 complete，记录仅含固定类型/线程身份的 warning，再传播按规则选出的异常；后续 `close()` 对停止的 loop 重试 close，成功后才清理并允许新 manager 实例继续。

transaction 直到 initial `_start_holders()` submission/result 成功才结束。publication 后的 `_submit` 若抛普通 `Exception`，`connect()` 先调用 bounded close 清理已创建 generation；cleanup 的普通异常被 close 收敛，若 cleanup 自身收到新的 `KeyboardInterrupt`/`SystemExit` 则按进程控制语义传播，否则原 infrastructure Exception 交给 `build_mcp_manager()` 转成只含固定类别与异常类型的 `MCPStartupError`。若 primary 本身是 `KeyboardInterrupt`/`SystemExit`，`connect()` 必须保存该对象，cleanup 中捕获并仅记录任何后续 `BaseException` 的固定类型，再重抛同一 primary 对象，不能让第二异常替换它。所有路径都不能输出原异常字符串、command、args 或 env。增加 submission rejection/timeout 后无 loop、holder、PID 泄漏的回归。

现有未提交回归必须作为重设计第一轮 RED：

- `test_enable_during_timed_out_disable_restarts_after_old_holder_cleanup` 对应 generation/reconcile。
- `test_connect_interrupt_releasing_publication_gate_stops_running_loop` 对应 startup transaction rollback。

实现完成后再扩展 disable+enable+close overlap、旧代 finally 隔离和 startup partial-success matrix；不得先删除或放宽这两个失败断言。

新增回归至少包含：

- `test_re_enable_old_holder_finally_does_not_delete_replacement_session`：旧代 session/status/tools cleanup 不影响新代。
- `test_close_snapshots_generation_on_loop_before_reconcile`：close barrier 与 slot snapshot 在 loop 内原子完成，排队 enable 不能逃出 snapshot 或在 closing 后启动。
- `test_call_failure_does_not_invalidate_replacement_session`：旧代 call failure 只能 invalidation 自己的 `(generation, session)`。
- `test_call_selection_occurs_on_loop_for_current_generation`：main thread 不能在代际切换前缓存旧 ClientSession；wrapper 执行时选择 current generation。
- `test_current_call_failure_waits_for_explicit_enable_before_replacement`：当前代失败会 cleanup 并降级，但不会仅因 desired enabled 隐式自动重连。
- `test_disable_during_holder_initialization_never_publishes_available`：initialize/list_tools 阻塞期间 disable 后，旧代不得发布 session/tools/status且 ready wait 能结束。
- `test_enable_racing_failed_holder_finalizer_starts_one_replacement`：显式 retry 落在 unavailable holder 的 finally 窗口时不丢 intent，且不出现双 replacement。
- `test_enable_after_failed_holder_finalized_starts_one_generation`：desired 已是 enabled 但 slot 已清理时，显式 enable 仍执行 retry。
- `test_timed_out_disable_then_close_leaves_no_lifecycle_waiter`：timeout 只取消 facade waiter，close 后无 pending waiter warning，holder cleanup 仍完成。
- `test_enable_after_close_does_not_start_holder`：closed/closing manager 不 reopen。
- startup matrix 覆盖 start 前抛错、OS thread 已启动后抛错、publication gate release 在 set 前/后抛 `KeyboardInterrupt`/`SystemExit`、正常 rollback 可 retry，以及 still-alive 分支保留 refs。
- initial holder submission/result 抛普通 Exception、`KeyboardInterrupt`/`SystemExit` 时均先 cleanup；普通异常映射为固定 CLI startup error，控制异常保持 identity。
- 多个 hung initial holder 的 ready timeout 从共享起点并发计时，启动等待不随 server 数量线性增长；optional/required 公共状态均不包含注入的 secret 异常文本。
- ready publish 与 timeout 同边界时成功状态不被迟到 timeout 覆盖；holder task 创建失败关闭 coroutine、立即报告 unavailable且不留下 partial slot。
- public close deadline 到达后 shielded drain 仍完成 holder finalizer 再 stop loop；注入单个 shutdown 普通异常不会跳过其余 slot或伪造 `_shutdown_complete`。
- normal/cancel holder 测试使用可区分 outcome marker，证明 graceful holder 收到自身 stop event，不能只比较相同 thread id。

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
└── real/<sanitized-model-id>/...
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

每个场景获得独立临时工作目录。case callable 负责 fixture 创建、Task/CLI/工具调用和显式 judge，并返回标准化 evidence。判定不得依赖 Python `assert`，以免 `python -O` 改变结果；失败通过专用 check error 或结构化结果表达。evidence 只能递归包含 JSON 标准值：`None`、`bool`、`str`、`int`、finite `float`、`list` 和键严格为 `str` 的 `dict`。递归检查使用精确内建类型（`type(value) is ...`，其中 `None` 用 identity），不能用 `isinstance` 接受 `IntEnum`、自定义 scalar 或 list/dict 子类；runner 再用 `json.dumps(..., allow_nan=False)` 做最终编码验证。tuple、非字符串 mapping key、Path/自定义对象、容器子类和非有限浮点都必须在编码前拒绝，不能依赖 encoder 把整数 key或 int 子类静默转换。非法 evidence 转成该场景的固定失败结果并继续其余场景，不能让最终报告阶段整体崩溃。

离线模式只使用本地 fixture：进入 Agent 循环的场景使用 MockClient；网络、CLI、Tool、RestrictedBackend 和 MCP 生命周期等边界场景可以直接调用对应入口及本地 test double，而不伪造一次无意义的模型轮次。基础运行不得访问公网、Docker、真实模型配置或用户 home。`tests/test_golden_runner.py` 必须包含一条不替换 manifest/case 的完整 20 项离线集成测试，使普通 `pytest` 基础 CI 真正执行可信核心，而不只验证 runner 的 fake-suite 合约。

standalone runner 还必须在配置敏感 import 之前建立隔离边界。`tests/golden/__init__.py` 保持无副作用，`runner.py` 顶层只导入标准库；offline `main()` 解析参数后先创建临时 home并临时设置 `HOME`、`USERPROFILE`、`XDG_CONFIG_HOME`，再 local-import manifest、cases、CLI、MCP 和模型配置相关模块，完成 suite/report 后在 `finally` 恢复三个变量的原值或未设置状态。standalone 测试从一个含恶意 `~/.forgeagent/mcp.yaml` 的父环境启动真实子进程，证明该文件既不会被 import-time default path 捕获，也不会影响 20 项结果；另一个 in-process `main()` 测试证明正常返回和 runner 异常路径都恢复环境，不能用“子进程本来就无法修改父环境”替代。临时 home 只属于 offline 分支；显式 `--real-model` 分支保留调用者原始 `HOME`/`USERPROFILE`/`XDG_CONFIG_HOME`，在该环境下 local-import 并解析用户 `~/.forgeagent/models.yaml`/`config.yaml` 与凭证，否则合法的自定义模型会被隔离目录静默隐藏。real opt-in 可以消费显式模型/凭证环境，但不能让 offline 路径提前 import 配置敏感模块。

G13 的离线脚本在工具失败/成功轮携带提前 `completed: true`，同时验证错误反馈环和严格两阶段完成。G03 judge 必须解析并逐行核对扁平 CSV；G05 必须用 tests-only RestrictedBackend wrapper 在执行第二块前包装 `utils.get_state` 的返回值，记录读取的 key/value 和返回值 use marker，同时断言第一块副作用恰好一次。仅有 use marker 不是充分条件：judge 还要以不可由脚本预知的替代 state 在测试侧因果重放同一第二块，要求输出随之精确变为 `alternate_state + 8`，并在重放后恢复受控 state/output；无用读取、无用数值转换或无用加法后硬编码 50 都必须失败。wrapper、marker 和替代 state 不进入生产代码或持久 state。G08 必须核对给定测试文件 hash 不变；G15 必须同时验证 Edit version+1、旧历史保留、仅目标 diff 和 AST；G27 必须验证初始 FAIL、最终 PASS 和 Edit 版本链。G329 通过 confirmed `WebFetchTool` 精确断言固定 network-policy outcome 和零 connector；G330 用 resolver/redirect/connection doubles 验证第二跳私网在连接前拒绝；G332 无 confirmer 时精确断言 no-channel outcome 和零 fake-network 调用，批准分支只使用 fake public response。最终值或测试通过只是这些场景的必要条件，不是充分条件。MCP required/close 的细粒度故障矩阵保留在专项测试；G355 必须通过真实 `/mcp` slash handler核对状态和工具描述，只承担产品级 CLI 冒烟与 optional 降级。

现有 `test_mock_replay_e2e.py` 的 G01/G05/G13 逻辑迁移到 cases 供 runner 与 pytest 共享，不复制一套脚本和 judge。

### 9.4 报告和退出码

runner 接受默认离线模式、`--real-model <model-id>` 和可选 `--output-dir`。

JSON 结果包含：schema version、mode、model、开始/结束时间、total/passed/failed/pass_rate，以及逐项 ID、title、passed、duration、detail 和 evidence。Markdown 从同一个结果对象生成摘要和逐项表格，不进行第二次判定。

- 全部场景通过：写报告，退出 0。
- 任一场景失败或异常：继续运行剩余场景，写完整报告，退出 1。
- manifest 不合法、真实模型无法解析、所需本地凭证缺失、输出目录不可用等 preflight 失败：退出 2，不生成通过率报告。远端供应商是否接受凭证只能由首次真实场景请求证明；该类运行期鉴权失败按场景失败记录并退出 1，不额外发起 preflight 网络探测。

默认输出为 `artifacts/golden/offline/` 或 `artifacts/golden/real/<sanitized-model-id>/`，覆盖同模式上一次结果，提供稳定 CI 路径。`sanitized-model-id` 固定为：把原始 model id 中连续的非 ASCII 字母数字/`_`/`-` 字符替换为 `-`，去掉首尾 `-`/`_`，空结果使用 `model`，截断到 48 字符，再追加 `-` 与原始 UTF-8 model id 的 SHA-256 前 8 位。这样 `/`、`..`、Unicode 和标点不能形成路径段，规范化后相同的不同 ID 也不会静默共用目录。每个文件使用同目录临时文件加 `os.replace()` 原子写入，避免进程中断留下半文件。`artifacts/` 加入 `.gitignore`。

runner 本里程碑明确顺序执行，不承诺多个进程同时写同一个 output-dir；并发调用方必须提供不同的 `--output-dir`。因此不增加跨进程锁或并行写测试。

## 10. 测试矩阵

| 能力 | 关键测试 | 主要证据 |
| --- | --- | --- |
| 代理/SSRF | 大小写 proxy env、loopback、private、NAT64、redirect private、11 跳、FTP/file redirect | 实际校验 host 是目标而非代理；blocked target 未连接；redirect limit/scheme 明确拒绝 |
| 网络消费端错误 | WebFetch InvalidURL/BadStatusLine/LineTooLong/IncompleteRead/RemoteDisconnected/close error/artifact OSError；search representative protocol error/unknown charset | HTTPException 基类覆盖代表性叶子；工具级异常不逃逸；固定消息不含 URL/hostname/path；search 返回 unavailable 或 UTF-8 fallback |
| confirmer 与结果最小披露 | MCP/WebFetch/FileWrite formatter、EOF、空输入、带空白的 yes/no、非 TTY REPL、MCP identifier/FileWrite path secret、Rich markup/terminal controls、嵌套 secret key、encoded/case/overlap hostname、encoded delimiters、IPv6/zone id、URL component mask、WebFetch 失败、artifact symlink escape、FileWrite 成功/失败 outcome、到期裸词路由 | 无属性错误；模型文本按单行 literal 渲染且不注入样式/换行；无跨组件或双重脱敏；prompt、ToolOutcome、Step feedback 不回显敏感 URL/hostname/宿主绝对路径；artifact 不写出 root；TTY 与非 TTY 原因正确；仅 slash command 被路由 |
| 文件路径边界 | root allowed_root、相对 root、NUL、越界、symlink resolve、FileRead/List/Write OSError、restricted audit | commonpath 正确接受 root 子路径并拒绝越界；无 ValueError 逃逸；固定失败消息无绝对路径 |
| CLI 注入 | REPL、TTY run、非 TTY run、`--interactive` | confirmer 与 MCP 解耦；Survey 语义不漂移 |
| 完成门控 | 工具成功/失败/parse error + completed；后续独立完成 | 同轮不完成；反馈后完成；max_rounds 诚实 |
| MCP 配置 | required 默认、enabled/disabled required、optional/required secret-bearing status | optional 降级；required 启动失败；禁用项不阻断；公共诊断只含脱敏固定类别/异常类型 |
| MCP lifecycle - generation | timed-out disable→enable replacement、unavailable-finalizer retry、当前 call failure 不自动重连、旧 gen finally/call failure、state/holder/session mismatch、disable+enable+close overlap、enable-after-close | `(gen, task, stop)` slot 在 task done 前可见；replacement 需精确 restart intent 且至多一个；call 仅使用同时匹配 state 与 holder 的 current session；旧 gen 不能改新 holder/session/status/tools；close 在 loop 内 snapshot 精确 slot |
| MCP lifecycle - facade wait | enable/disable/connect timeout、timed-out disable 后立即 close | timeout 只取消 concurrent waiter；shielded holder ownership 继续；loop stop 前无 pending lifecycle waiter warning |
| MCP lifecycle - startup transaction | Thread.start 抛错、start 后 gate release 在 set 前/后抛 KeyboardInterrupt/SystemExit、initial holder submission/result 异常、多个 hung holder、join timeout | cancel-aware gate→loop stop→bounded join；停止后 rollback 为可重试状态；ready timeout 不随 server 数量线性增长；仍活时保留 refs/closed warning；普通异常固定 startup error，原控制异常不被替换 |
| MCP close | 正常、完全忽略 stop、lifecycle cancel/内部异常、重复 close、结果保留、thread join 超时 warning、join 期间 completion、公开 deadline 后 finalizer 完成、延迟停止后再次 close | 绝对 deadline 内返回；future timeout cancel 并保留引用；loop drain 可越过 caller deadline但 finalizer 完成后才 stop；单个 cancel/cleanup 异常不跳过其他 slot或伪造 completion；同次 join 后重读 completion；cleanup complete + thread stopped 后才 close/clear；PID 消失；warning 无敏感参数；原结果不被覆盖 |
| 测试隔离 | 真实 home 放置恶意 mcp.yaml 后运行 suite | 测试只读取临时 home，结果不变 |
| 黄金 runner | manifest 变异、standalone 恶意 HOME、20 pass、单项/非法 evidence fail、preflight fail | 配置敏感 import 前隔离 home；ID/数量锁定；非标准 JSON evidence 只失败单项；JSON/Markdown 同源；退出码 0/1/2 |
| 真实模型入口 | 缺配置、有效单模型 | 缺配置无报告且退出 2；只执行 5 项 |

## 11. 文档与迁移

实现完成后同步：

- `docs/model-client-contract.md`：当前 complete/streaming 和多模态支持。
- `docs/text-protocol-spec.md`：WebFetch、FileRead/FileWrite/FileList、MCP 与两阶段完成。
- `docs/threat-model.md`：环境代理禁用、guarded direct connection、确认门边界和未来 proxy 契约。
- MCP/CLI 文档：`required`、optional 降级、TTY/non-TTY、`autoApprove` 例外。
- `docs/golden-tasks-seed.md` 与 README：20 项可信核心、360 项候选、5 项 opt-in 真实模型和报告命令。
- ACTION_PLAN、加固里程碑和 `milestones/latest`：只记录实证运行结果；不改写用户已有 M11/M12 规划内容，里程碑编号在收尾时按现有空位和 `MILESTONE_GUIDE.md` 确定。

迁移无需数据转换。MCP 新字段默认 false，旧配置兼容。环境代理被禁用属于 `[SECURITY][BREAKING]` 安全加固：发布说明必须提示依赖企业代理的用户当前会直连失败，`NO_PROXY` 不能恢复代理，本里程碑没有透明代理替代。发布说明同时列出三条可操作路径：允许该进程直连、外部预取到 `allowed_root` 后用 FileRead、或使用用户显式信任的 MCP fetch 工具；不得建议重新启用环境 ProxyHandler。

## 12. 实施顺序

1. 固化回归与测试 home/PID 隔离。
2. 修复 ProxyHandler 和 SSRF 测试。
3. 修复 confirmer formatter、TTY 注入、网络消费端异常、文件路径边界和完成门控。
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
- WebFetch/search 的预期 URL、HTTP 协议、解码和 artifact 写入失败均被稳定收敛，没有工具级异常逃逸。
- 文件工具与 restricted audit 的 commonpath 判定正确处理 filesystem root；非法和失败路径不进入模型反馈或 CLI 输出。
- CodeGraph 复审确认所有受影响调用方已覆盖，文档不再声称未执行的 380 项已验证。
