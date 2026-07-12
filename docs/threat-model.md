# 威胁模型（M1 设计文档）

> 范围：ForgeAgent 运行时 harness（LLM 生成 Python 程序 → 本地执行）。不覆盖开发 harness（subagent 派发、CI）本身的安全性——那是使用 Claude Code/工具链的既有边界，不重复建模。
> 前提（B2 后修订；M8 更新）：安全强度**按档位分级**——`trusted` 无隔离、`restricted`（默认）靠执行后端提供**跨平台应用层限权**（非 OS 级）、`container`（**M8 已实装**，原计划 M10）是 OS 级隔离。restricted 不是"仅防误操作"，它能挡住绝大多数越权与一部分蓄意逃逸（应用层能覆盖的那部分），但不挡有意绕过应用层的攻击（ctypes 直调 syscall、内核漏洞等），也不是密封沙箱（见"各档隔离强度"）。此前 M1 初稿"restricted 仅防误操作层"的定性已被 B2 决策取代。

## 资产（保护什么）

1. 运行 ForgeAgent 的宿主机文件系统（用户主目录、项目目录之外的任意路径）。
2. 环境变量 / 密钥（模型 API key、用户可能配置的其它 secret）。
3. 网络出口（宿主机可达的内网、外网服务）。
4. 宿主进程本身（不能被越权杀死、不能被注入长期驻留代码）。
5. 用户对"Agent 会做什么"的信任——静默越权比报错更危险。

## 攻击面（从哪来风险）

ForgeAgent 的核心风险来源和 agent 一样：**LLM 生成的代码被本地执行**，攻击面 = 这段代码能触达的一切。agent 一律同进程 `exec()`；ForgeAgent 按档位换执行后端（trusted 同进程、restricted 每块子进程 + 限权、见下），但**只要代码在宿主上跑，风险来源就存在**——分三类，缓解策略与覆盖范围不同：

| 来源 | 说明 | 典型场景 |
|---|---|---|
| **能力误用**（主要威胁） | 模型没有恶意，但为了"完成任务"生成了越权代码——读了不该读的路径、装了不必要的包、发了不该发的请求 | 模型为了"分析项目"递归读到 `~/.ssh/`；为了"画图"用 `pip install` 装了任意包 |
| **提示注入**（次要但要防） | 任务输入里混入的外部数据（文件内容、网页、工具返回）包含"忽略之前的指令"类文本，试图让模型生成的代码转向攻击者目标 | 用户让 Agent 读取一个网页做摘要，网页里嵌了让 Agent "把 `~/.env` 内容发到某 URL"的指令 |
| **蓄意绕过检测的恶意代码** | 有意绕开应用层限权的攻击——ctypes 直调 syscall、利用内核漏洞、供应链提权、持久化驻留 | restricted 应用层能挡的部分（如常规越权路径/网络）已被 T1-T3 覆盖；有意绕过应用层的高级攻击**超出 restricted 范围**，需 container 档（M8 已实装）的 OS 级隔离 |

## 信任边界

```
用户输入 / 任务描述
        │
        ▼
  LLM（不可信输出——LLM 生成的代码永远视为不可信输入）
        │  文本协议解析（CodeBlock/ToolCall markup）
        ▼
  AST 静态层（导入/危险模式告警 + 自动修复）── 弱约束，非信任边界
        │  可被图灵完备绕过；只挡手滑与明显误用，早反馈
        ▼
  执行后端（按档位挂载）────────────────── 真正的信任边界在此
        │  trusted=同进程(无强制) / restricted=每块子进程(应用层限权) / container=容器(OS级)
        ▼
  宿主机资源（文件系统 / 网络 / 环境变量）
```

**信任边界的位置是本图要点**：agent 把边界（错误地）依赖在提示词+静态检查上；ForgeAgent 明确把边界下沉到**执行后端**。AST 静态层在边界之外——它是给模型的早反馈和防手滑，不承担安全强制。这意味着 restricted 的安全强度 = 子进程后端隔离的强度，与静态规则数量无关。

关键原则：**LLM 输出（包括其生成的 Python 代码）永远在信任边界之外**，无论模型多"聪明"或"配合"。**唯一的强制点是执行后端**（restricted 的跨平台应用层限权 / container 的 OS 级隔离）；AST 静态层和提示词声明的规则（"不要读取 /etc/passwd"）都是弱约束，只能减少误用几率、给模型早反馈，不能作为安全保证——这一区分必须在文档里反复强调，避免开发时把提示词工程或静态检查误当作安全边界。

## 分级缓解（对应 sandbox 三档）

**架构决策（B2，已定稿——含跨平台锐化）**：executor 抽象出统一的后端接口，按档位挂不同后端——**档位语义即隔离强度，一一对应，人类选档就是选执行机制**：

- `trusted` → **同进程 `exec()` 后端**（等价 agent 现行为，零开销、满血、跨块状态走 globals）。
- `restricted`（默认）→ **每块新起子进程后端**（不是常驻）：主进程序列化传递跨块状态 + 应用层限权 + 资源限制 + 超时强杀。
- `container`（**M8 已实装**）→ **容器后端**（同一后端接口换更强隔离实现，架构不推倒）。

**restricted 的进程模型（跨平台锐化，B2 定稿）**：**每个代码块新起一个子进程执行，执行完退出**——不用常驻进程。理由：① 我们的跨块状态是**显式 `set_state()` 存取**（见 golden task G05），不是 agent 式隐式全 globals 持久，因此不需要常驻同一解释器；② 每块新进程让超时可干净强杀而不丢历史状态、且天然无状态污染。跨块状态由**主进程持有一个 state dict**，执行前注入子进程、执行后回收（仅限可 pickle 的值；文件落盘天然跨块共享，不受此限）。

**跨平台策略（B2 定稿）**：restricted 的隔离机制**统一走跨平台可用的应用层手段**，不用 Linux-only 的 namespace/unshare/chroot/seccomp（那些留给 container 档）：

- **路径限制**：子进程 bootstrap 里装 `sys.addaudithook`（PEP 578），拦截 `open` 审计事件到 realpath 白名单校验（默认仅项目目录）。审计钩子拦截**底层操作**，无论上层用 `open`/`pathlib.Path.open`/`io.open`/`os.open` 哪种 API 都触发同一 `open` 事件——比 monkeypatch `open`（会漏掉 pathlib 等路径）覆盖面更全。
- **网络限制**：**默认全拒**——audithook 拦截 `socket.connect`/`socket.getaddrinfo` 等审计事件即失败（不依赖"禁导入"，因为审计事件在底层触发，绕过导入也拦得住）。v1 golden task 网络本就 mock 优先（G09），不需要真联网。将来需要联网时，通过主进程 Broker 代理开一条受控通道（v1 不做）。
- **进程 spawn 限制**：**默认全拒**——audithook 拦截 `subprocess.Popen`/`os.system`/`os.exec*`/`os.spawn*`/`os.posix_spawn` 审计事件。这是必要的堵漏：子进程**不继承** Python 审计钩子，若允许 spawn，恶意代码可起一个子进程去读文件/联网从而绕过 T1-T3 的全部限制。
- **资源限制**：`rlimit`（CPU/内存/文件数）——**Unix-only（Linux+macOS）**；Windows 无 `resource` 模块，降级为超时强杀 + 后续可选 Job Objects（v1 不做 Windows 资源硬限，仅超时）。
- **超时**：子进程到点 `SIGKILL`（`terminate`/`kill`），全平台可用。

| 档位 | 执行后端 | 跨块状态 | 强制隔离（真拦，跨平台应用层为主） | 静态层（AST，各档都跑） | 不缓解 |
|---|---|---|---|---|---|
| `trusted` | 同进程 `exec()` | globals 直接持久（借 agent `runtime.py`） | 无——用户显式 opt-in、自担风险 | 危险模式仅告警，不阻断（信任用户） | 一切 |
| `restricted`（**默认**） | 每块新起子进程 | 主进程持 state dict，执行前注入、执行后回收（仅可 pickle 值；文件落盘天然跨块共享） | 路径（audithook 拦 `open` 事件 → realpath 白名单）、网络（audithook 拦 `socket.*` 事件，默认全拒）、资源（`rlimit`，Unix-only）、超时（`SIGKILL`，全平台） | 导入/危险模式检查 + 自动修复 + 反馈 | 应用层限权的图灵完备绕过（如 ctypes 直接 syscall）；`rlimit` 之外的资源面；Windows 资源硬限 |
| `container`（**M8 已实装**） | 每块一次性 `docker run` 容器（同一 worker/JSON 协议） | 同 restricted 的状态传递模型（JSON 跨界） | mount namespace（仅挂 allowed_root，宿主其余文件系统**不可见**）+ `--network none`（无网络设备）+ `--pids-limit`/`--memory`/`--cpus` 硬限 + `--cap-drop ALL`/no-new-privileges/非 root/只读 rootfs + `--tmpfs /sys` 遮蔽（T9b）+ 超时 `docker kill` | 同 restricted（各档都跑） | 容器逃逸类：内核 0-day、docker 守护进程漏洞（T9a）；`/proc` 基础信息可读（cpuinfo/meminfo/version，T9b 如实声明） |

**为什么每块新进程而非常驻/同进程**：同进程 `exec()` 无法可靠强制路径/网络/超时——受限 builtins 可被 `getattr`/`__class__.__bases__` 等图灵完备手法逃逸（已知老问题），`while True` 在同进程里 signal 不可靠、线程无法强杀。子进程才能挂 `rlimit`/`SIGKILL`。而**每块新进程**（相对常驻子进程）额外换来：超时强杀不丢历史跨块状态、块间无内存污染、IPC 极简（起进程→喂代码+状态→收结果+新状态→退出，无长连接/崩溃恢复）。**代价**：跨块状态仅限可 pickle 值（活的 DB 连接/socket 对象不跨块），但 golden task 不涉及、文件状态天然存活，且"每块独立、要持久就显式 set_state"对用户心智更清晰——这是相对 agent 全 globals 持久的有意语义缩减，可接受。进程启动开销（~30-80ms/块）在 code-as-action 的 LLM 秒级延迟面前可忽略。

## 具体威胁 → 缓解映射（v1 restricted 档需覆盖的逃逸用例，供 M4 编写 escape tests）

下表的"缓解手段"列区分三类落点：**【后端】**= 执行后端强制（restricted=跨平台应用层 `sys.addaudithook`，container=OS 级；真拦，restricted 及以上生效）；**【流程】**= 执行前的人工确认门（如装包确认，既非后端强制也非静态检查，独立一类）；**【静态】**= AST 层告警/修复（弱约束，各档都跑但可被图灵完备绕过）。trusted 档只有【静态】的告警形态，无【后端】强制。

| # | 威胁场景 | 缓解手段（落点） | M4 验收用例方向 |
|---|---|---|---|
| T1 | 读取 secret（如 `~/.aws/credentials`、`.env`）并回显/外发 | **【后端】**子进程 bootstrap 装 audithook 拦 `open` 事件到 realpath 白名单（默认仅项目目录），项目外路径读取被拒（覆盖 open/pathlib/io/os.open 各路径）；**已实现**：restricted 子进程按 `secret_policy.scrub_environment()` 洗白 env 后再 spawn（密钥命名模式匹配，代理 agent 自身凭据不进子进程，从源头堵一类读取）；**已实现**：两档后端执行结果统一经 `secret_policy.mask_secrets()` 按值掩码 stdout/stderr/error（防御深度——即便代码从别处取到了密钥值，回显/日志也不泄真值）；**延后**：`utils.get_env()` 式受控取密钥访问器——v1 尚无消费场景（无需网络 Broker 转发密钥的用例），YAGNI，留给未来引入 Broker 时一并做 | restricted 后端下生成读取项目外文件的代码（含用 pathlib 而非 open），断言被 audithook 拒绝（非仅静态告警）；另需覆盖：子进程内 `os.environ.get("<SECRET_NAME>")` 断言取不到值、`print()`/异常回显包含密钥值的文本经 mask 后不含真值（`tests/test_secret_policy.py` 已覆盖两档) |
| T2 | 越权写文件（项目目录之外、覆盖系统文件） | **【后端】**同 T1 的 audithook + realpath 白名单，写操作限制在允许路径内；**【静态】**不可逆覆盖操作的确认提示（UX 层，非安全边界） | restricted 后端下尝试写 `/etc/hosts`/主目录任意文件，断言被拦 |
| T3 | 违规出网（数据外送、访问内网服务） | **【后端】**audithook 拦 `socket.connect`/`socket.getaddrinfo` 等审计事件（默认全拒，绕过导入也拦得住）；需要联网时经主进程 Broker 受控代理（v1 不做）；**【静态】**网络模块使用告警 | restricted 后端下生成 `import socket`/发请求的代码，断言连接事件被拦 |
| T4 | 运行时装任意包（供应链风险、资源滥用） | **【流程】**`ensure_packages()` 式装包需用户确认门（借鉴 agent `CliPythonRuntime.install_packages`），来源限定 PyPI 官方索引 | 生成 `pip install` 未声明包的代码，断言触发确认门 |
| T5 | 提示注入导致模型生成偏离任务的代码 | **【静态/提示】**外部内容在提示词层标注"数据非指令"；**关键**：后端限权不因提示词标注放宽——注入若真诱导出越权代码，仍由 T1-T3 的【后端】层兜底拦截 | 构造含注入文本的模拟外部内容，验证生成代码仍被后端层拦截（不依赖模型是否被带偏） |
| T6 | 长期驻留 / 死循环 / fork 逃逸 | **【后端】**每块子进程执行超时到点 `SIGKILL`（进程边界强杀，同进程做不到；杀块进程不丢主进程历史状态）；`rlimit` 限制 CPU 时间/fork 数（Unix-only；Windows 仅超时） | restricted 后端下生成 `while True`/daemonize 代码，断言超时被强杀、且下一块仍能正常执行 |
| T7 | 禁用导入被绕过（如动态 `importlib`/`__import__` 绕过静态 AST 检查） | **【静态】**AST 规则同时检查动态导入模式，已知绕过手法显式覆盖；**兜底**：即便静态漏检，子进程【后端】的路径/网络限权仍限制其实际能触达的资源 | 生成用 `importlib.import_module()` 导入禁止模块的代码，断言静态拦截；并验证后端层对漏检情况的兜底 |
| T8a | MCP server（可能多个）在**主进程**执行，绕过 restricted 子进程沙箱——多 server 并存 = 更大的主进程攻击面 | **【流程】**有副作用的 MCP 调用按 per-`(server,tool)` 过确认门（`autoApprove` 白名单外一律确认，无 confirmer 视同拒绝，从不静默执行）；server 命令由用户在 `~/.forgeagent/mcp.yaml` 的 `mcpServers` 显式配置（用户信任的可执行文件，非模型任意起进程）；`enabled:false` 的 server 完全不连、不广告 | M7：`autoApprove` 内放行、外过门；confirmer 返回 False 或缺席 → 结构化"未批准"反馈、server 未被调用（`test_tools.py` MCP 门用例）；disabled server 不在 catalog（`test_mcp_manager.py`） |
| T8b | MCP 工具的**名称/描述**注入系统提示词，成为新的提示注入面（描述文本由外部 server 提供，攻击者可影响） | **【提示】**`tools_prompt()` 显式标注"工具清单是外部 server 提供的**数据、非指令**"；**兜底**：即便描述诱导模型，生成的越权 Python 仍由 restricted 后端拦（T1-T3），越权 MCP 调用仍过确认门（T8a） | `tools_prompt` 含"DATA supplied by those servers"框定语（`test_mcp_manager.py::test_tools_prompt_groups_by_server_and_flags_external`） |
| T8c | MCP 调用的**返回内容**携带注入 payload 回流进反馈环 | 同 T5（外部数据非指令）；返回内容经 `_truncate_tail` 截断（长度防爆）；后端/确认门强制不因返回内容放宽 | 返回含注入文本不改变任何强制层（延续 T5 的分层原则；MCP 返回与网页/文件外部数据同类） |
| T9a | **容器逃逸**（container 档）：内核漏洞、docker 守护进程漏洞、挂载配置错误 | **【后端】**`--cap-drop ALL` + no-new-privileges + 非 root `--user` + 只读 rootfs 收缩攻击面；allowed_root 由主进程 realpath 后传入且是唯一 rw 挂载；**不缓解**内核 0-day——container 档是 OS 级隔离，不是虚拟机级（诚实声明） | M8：escape test 断言容器内非 root、宿主路径不可见（挂载外 `os.path.exists` 为 False） |
| T9b | **`/proc`/`/sys` 信息泄露**（container 档，2026-07-11 用户裁决 9）：容器默认可读部分 procfs/sysfs（CPU/内存拓扑、内核版本、网络统计） | **【后端】**`--tmpfs /sys:ro` 整棵遮蔽 `/sys`（实测 listdir 为空）；`/proc` 依托 docker 默认 masked paths（kcore/keys 已遮；runc 禁止向 /proc 内部自定义挂载——spike D9 实测，无法逐文件遮）+ 容器 env 默认全无（docker run 不继承宿主 env），`/proc/*/environ` 无 secret 可泄；**不缓解**`/proc` 基础信息（cpuinfo/meminfo/version/net 统计）——风险为环境指纹，接受并声明 | M8：escape test 断言 `/sys` 为空、容器内 os.environ 无宿主 secret 变量 |
| T10a | **WebFetch SSRF**（内网服务、云 metadata 端点如 `169.254.169.254`）——M10 引入的第一个主进程真实出网 Tool | **【后端】**`ssrf_guard.py`：`urllib` 的 `_create_connection` hook 拦截每个候选地址，`getaddrinfo` 拿到的每个 sockaddr 逐一过 `is_global`/`is_multicast`/NAT64（`64:ff9b::/96`）解包复检，命中即拒；直连已过校验的 sockaddr（不重新解析域名，堵 DNS rebinding 的 TOCTOU 窗口）；`urllib.request.HTTPRedirectHandler` 每跳重新触发 `http_open`/`https_open`，同一 hook 逐跳复检（免费获得，无需额外代码）；**【流程】**`restricted`/`container` 档下 WebFetch 强制走确认门——这是**真实安全边界**（而非 UX 层）：这两档下 Exec 已被 audithook 全拒出网（T3），WebFetch 是当前唯一出网路径，拒绝确认即等于拒绝全部出网 | `tests/test_ssrf_guard.py`：127.0.0.1/169.254.169.254/224.0.0.1/NAT64 包裹的私有地址断言拒绝；两个本地 `HTTPServer` 构造的跨跳重定向断言在被拦截的那一跳即挡住，不透传上一跳的放行结果；`file://` 等非 http(s) scheme 断言拒绝 |
| T10b | **FileWrite 越权写出项目根目录**（`../../etc/passwd` 式路径穿越） | **【后端】**`tools.py::_validate_path` 对写入路径做 realpath 前缀校验，穿越即抛 `PermissionError` 转为失败 `ToolOutcome`；**【流程】**`restricted`/`container` 档下确认门——**仅 UX 层提示，非安全边界**：模型代码经 Exec 本就能在 `allowed_root` 内任意写（executor 后端的 audit hook 早已放行项目目录内写操作），拒绝 FileWrite 确认门不能阻止等价的 Exec 写入，只是减少一次"未经用户过目就落盘"的路径 | `tests/test_web_file_tools.py`：项目根目录内写入断言成功、内容逐字节匹配（不掩码）；`../../` 穿越尝试断言被拒 |
| T10c | **FileRead 经工具返回内容外泄 secret** | **【后端】**读取范围同样锁在 `allowed_root`（`_validate_path` 复用）；返回内容经 `secret_policy.mask_secrets()` 按值掩码后才进入 `ToolOutcome.detail`，与 T1 的 Exec 输出掩码同一机制、同一防御深度原则 | `tests/test_web_file_tools.py`：读取含伪造 secret 值的文件，断言返回内容中该值已被掩码、原值不出现 |
| T11a | **`/search` 出网被滥用**（构造指向内网的查询 URL） | **【后端】**查询词经 `urllib.parse.quote` 编码后拼进固定 host 的 URL 模板（host 不可被查询词改写）；请求经 `guarded_urlopen` 走 T10a 同一套 SSRF 复检。与 T10a 的区别：`/search` 是用户在 REPL 亲手键入的命令，视为用户亲手键入即授权，不额外过确认门 | `tests/test_web_search.py`：查询词含 `&`/空格等字符时断言仅被编码进 query 参数、host 不变；SSRF 拦截路径复用 `test_ssrf_guard.py` 的覆盖 |
| T11b | **搜索结果/图片文件内容作为外部数据携带提示注入** | **【提示/流程】**`/search` 结果只打印给用户看、从不自动注入对话历史（design doc §3.5）；`--image`/`/image` 加载的是用户自选的本地文件，信任级别等同用户输入本身；模型若被搜索结果文本或图片内嵌指令带偏，生成的越权代码仍由 T1-T3 的【后端】层兜底（延续 T5 分层原则，不因数据来源是搜索/图片而放宽） | `tests/test_cli.py`：`/search` 结果断言只出现在打印输出、不出现在传给 `Task.run()` 的 goal 内容里 |
| T11c | **流式中途断线导致半截协议文本进入解析器** | **【后端】**中途失败的一轮整体收敛为 `ClientError`（§3.1 错误语义），半截 Block/ToolCall 标记不会被当作完整协议文本解析、不进对话历史 | `tests/test_step.py`：模拟流式中途抛错，断言该轮结果为 `ClientError`、历史里没有半截文本 |

**T10a 与 T3 的边界差异（重要）**：T3 管的是"代码块内部代码能不能联网"（答案：restricted/container 两档全拒，无 Broker），T10a 管的是"主进程 Tool 本身能不能替 LLM 发起一次受限的出网请求"——两者是正交路径，互不影响：WebFetch 的 SSRF Guard 收紧不会放宽 T3 的全拒判断，T3 的全拒也不代表 WebFetch 天然安全（所以才需要独立的 SSRF Guard + 确认门）。详见 `docs/m10-usage-observability-and-tools.md` "未决/明确不做"一节。

**T8 与 T1-T7 的边界差异（重要）**：T1-T7 的威胁都在**执行后端内**（restricted 子进程），后端层是强制点。**T8（MCP）不同——MCP server 运行在主进程、后端隔离对它完全不适用**，所以 T8 的强制点是执行**前**的人工确认门（per-`(server,tool)` + `autoApprove` 白名单），不是后端。这是 v1 首个"不由执行后端兜底"的能力：一旦确认门放行，MCP server 就以主进程权限运行，restricted 的路径/网络/资源限权一概不作用于它。因此 MCP server 必须是用户显式配置的可信可执行文件，`autoApprove` 只列真正只读的工具。

**T1-T7 的分层原则**：静态 AST 层负责"早反馈、修手滑、挡明显误用"，但**绝不作为安全边界**——它可被图灵完备绕过（T7 就是例证）。真正的强制在【后端】层。但要诚实：v1 后端的路径/网络限权是**应用层 `sys.addaudithook`**（跨平台代价），比 OS 级隔离弱——`ctypes` 直接调 syscall 绕过 Python 运行时、内核漏洞等仍可能绕过（审计钩子在 Python 层，不拦纯 native 代码）。因此 restricted 的定位是"挡住绝大多数越权 + 相当一部分蓄意逃逸"，不是"密封"。要密封隔离用 container 档（OS namespace + seccomp，M8 已实装）。trusted 无【后端】层，安全性等于零（设计如此，用户显式 opt-in）。

T7 同时是本文档对 agent 现有 `ForbiddenImportRule`（仅处理 `ast.Import`/`ast.ImportFrom`）的已知缺口提示——`code_analyzer.py:88` 不处理动态导入，ForgeAgent 扩展该规则引擎时必须补上；但即便补上，静态层仍只是弱约束，不能替代后端隔离。

## 明确声明（写进 README / 文档，避免误解）

> **各档隔离强度（写进 README，让用户据此选档）**：
> - `trusted`：无隔离，同进程执行，代码能碰宿主一切。仅在你完全信任任务来源时用。
> - `restricted`（默认）：每块新起子进程 + 应用层限权（`sys.addaudithook` 拦 `open`/`socket.*` 事件、超时强杀、`rlimit` 资源限制[Unix]）。**能挡住绝大多数越权与相当一部分蓄意逃逸**，但限权是 Python 层审计钩子、非 OS 级隔离，`ctypes` 直调 syscall 绕过 Python 运行时等仍可绕过；也不防内核漏洞。适合日常使用与来源基本可信的任务。
> - `container`（M8 已实装）：OS 级隔离——每块一次性 docker 容器，仅挂载 allowed_root（宿主其余文件系统不可见）、无网络设备、资源硬限、非 root + cap-drop ALL + 只读 rootfs。用于来源不可信或高风险场景。需要本机 docker；**不防内核 0-day/守护进程漏洞**（是 OS 级隔离，不是虚拟机级），`/proc` 基础信息（CPU 型号/内存总量/内核版本）在容器内可读。
>
> 一句话原则：**隔离强度 = 你选的档位对应后端能提供的强度**，与提示词或静态规则数量无关。若代码来源完全不可信且后果严重，用 container 档或干脆不在敏感环境运行。
> **平台差异**：`rlimit` 资源硬限仅 Unix（Linux+macOS）；Windows 下 restricted 的资源类缓解只有超时强杀（无内存/CPU 硬限），路径/网络限权跨平台一致。

## 未决 / 明确不做（v1 范围声明）

- **做** CPU/内存/文件数资源限额——子进程后端经 `rlimit` 实现，**仅 Unix（Linux+macOS）**；Windows 无 `resource` 模块，v1 不做 Windows 资源硬限（仅超时强杀），Job Objects 留待需要时再加。与超时（`SIGKILL`）一起构成资源类缓解。
- 不做多用户/多租户隔离（ForgeAgent 是单用户本地工具定位）。
- 不做代码签名/供应链完整性校验（超出轻量定位）。
- restricted 统一走跨平台应用层限权，不做 Linux-only 的 namespace/unshare/chroot/seccomp；OS 级隔离已由 container 档（M8）提供。
- **执行子进程（restricted/container 两档）仍不做联网 Broker**——代码块内部网络默认全拒不变（golden task 网络 mock 优先）。这里说的 Broker 特指"让被执行的代码块本身能发出经审查的出站请求"这一模式（子进程无网 + 主进程代理转发），v1 未实现，架构留位但暂无需求驱动，继续不做。
- **M10 WebFetch 不是上面说的 Broker，是另一条正交路径**：WebFetch 是主进程 `Tool`（同 MCPTool，走 `ToolRegistry`，不经 executor 后端），由 LLM 的工具调用直接触发、不由代码块内部代码触发。它是 ForgeAgent 第一个引入真实（但受限）出网能力的组件，隔离手段是 SSRF Guard（逐跳复检 IP、拒绝私有/环回/链路本地/多播地址）+ 确认门（`restricted` 档强制），与"代码块能不能联网"这一问题完全无关——代码块联网能力仍是全拒，不受 WebFetch 影响。详见 `docs/m10-usage-observability-and-tools.md`。
- **子进程 IPC 协议是 M2 交付物**：主进程↔执行子进程的通道（代码/状态注入、结果/新状态回收、异常传播、超时/崩溃处理）需在 M2 明确设计。因每块新进程、无长连接，协议可极简（一次 spawn 一轮往返），但仍要显式规范序列化格式与错误传播，不留隐式行为。
