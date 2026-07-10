# 威胁模型（M1 设计文档）

> 范围：ForgeAgent 运行时 harness（LLM 生成 Python 程序 → 本地执行）。不覆盖开发 harness（subagent 派发、CI）本身的安全性——那是使用 Claude Code/工具链的既有边界，不重复建模。
> 前提（B2 后修订）：安全强度**按档位分级**——`trusted` 无隔离、`restricted`（默认）靠执行后端提供**跨平台应用层限权**（非 OS 级）、`container`（M10，待定或不做）才是 OS 级隔离。restricted 不是"仅防误操作"，它能挡住绝大多数越权与一部分蓄意逃逸（应用层能覆盖的那部分），但不挡有意绕过应用层的攻击（ctypes 直调 syscall、内核漏洞等），也不是密封沙箱（见"各档隔离强度"）。此前 M1 初稿"restricted 仅防误操作层"的定性已被 B2 决策取代。

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
| **蓄意绕过检测的恶意代码** | 有意绕开应用层限权的攻击——ctypes 直调 syscall、利用内核漏洞、供应链提权、持久化驻留 | restricted 应用层能挡的部分（如常规越权路径/网络）已被 T1-T3 覆盖；有意绕过应用层的高级攻击**超出 v1 restricted 范围**，需 M10 container 的 OS 级隔离，v1 仅识别与声明 |

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
- `container`（M10，待定或不做）→ **容器后端**（同一后端接口换更强隔离实现，架构不推倒）。

**restricted 的进程模型（跨平台锐化，B2 定稿）**：**每个代码块新起一个子进程执行，执行完退出**——不用常驻进程。理由：① 我们的跨块状态是**显式 `set_state()` 存取**（见 golden task G05），不是 agent 式隐式全 globals 持久，因此不需要常驻同一解释器；② 每块新进程让超时可干净强杀而不丢历史状态、且天然无状态污染。跨块状态由**主进程持有一个 state dict**，执行前注入子进程、执行后回收（仅限可 pickle 的值；文件落盘天然跨块共享，不受此限）。

**跨平台策略（B2 定稿）**：restricted 的隔离机制**统一走跨平台可用的应用层手段**，不用 Linux-only 的 namespace/unshare/chroot/seccomp（那些留给 M10 container）：

- **路径限制**：子进程 bootstrap 里装 `sys.addaudithook`（PEP 578），拦截 `open` 审计事件到 realpath 白名单校验（默认仅项目目录）。审计钩子拦截**底层操作**，无论上层用 `open`/`pathlib.Path.open`/`io.open`/`os.open` 哪种 API 都触发同一 `open` 事件——比 monkeypatch `open`（会漏掉 pathlib 等路径）覆盖面更全。
- **网络限制**：**默认全拒**——audithook 拦截 `socket.connect`/`socket.getaddrinfo` 等审计事件即失败（不依赖"禁导入"，因为审计事件在底层触发，绕过导入也拦得住）。v1 golden task 网络本就 mock 优先（G09），不需要真联网。将来需要联网时，通过主进程 Broker 代理开一条受控通道（v1 不做）。
- **进程 spawn 限制**：**默认全拒**——audithook 拦截 `subprocess.Popen`/`os.system`/`os.exec*`/`os.spawn*`/`os.posix_spawn` 审计事件。这是必要的堵漏：子进程**不继承** Python 审计钩子，若允许 spawn，恶意代码可起一个子进程去读文件/联网从而绕过 T1-T3 的全部限制。
- **资源限制**：`rlimit`（CPU/内存/文件数）——**Unix-only（Linux+macOS）**；Windows 无 `resource` 模块，降级为超时强杀 + 后续可选 Job Objects（v1 不做 Windows 资源硬限，仅超时）。
- **超时**：子进程到点 `SIGKILL`（`terminate`/`kill`），全平台可用。

| 档位 | 执行后端 | 跨块状态 | 强制隔离（真拦，跨平台应用层为主） | 静态层（AST，各档都跑） | 不缓解 |
|---|---|---|---|---|---|
| `trusted` | 同进程 `exec()` | globals 直接持久（借 agent `runtime.py`） | 无——用户显式 opt-in、自担风险 | 危险模式仅告警，不阻断（信任用户） | 一切 |
| `restricted`（**默认**） | 每块新起子进程 | 主进程持 state dict，执行前注入、执行后回收（仅可 pickle 值；文件落盘天然跨块共享） | 路径（audithook 拦 `open` 事件 → realpath 白名单）、网络（audithook 拦 `socket.*` 事件，默认全拒）、资源（`rlimit`，Unix-only）、超时（`SIGKILL`，全平台） | 导入/危险模式检查 + 自动修复 + 反馈 | 应用层限权的图灵完备绕过（如 ctypes 直接 syscall）；`rlimit` 之外的资源面；Windows 资源硬限 |
| `container`（预留，M10，待定或不做） | 容器 | 容器内执行，同 restricted 的状态传递模型 | restricted 全部 + 文件系统/网络 namespace 完全隔离 + seccomp | 同 restricted | 本文档不展开，仅占位 |

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

**T1-T7 的分层原则**：静态 AST 层负责"早反馈、修手滑、挡明显误用"，但**绝不作为安全边界**——它可被图灵完备绕过（T7 就是例证）。真正的强制在【后端】层。但要诚实：v1 后端的路径/网络限权是**应用层 `sys.addaudithook`**（跨平台代价），比 OS 级隔离弱——`ctypes` 直接调 syscall 绕过 Python 运行时、内核漏洞等仍可能绕过（审计钩子在 Python 层，不拦纯 native 代码）。因此 restricted 的定位是"挡住绝大多数越权 + 相当一部分蓄意逃逸"，不是"密封"。要密封隔离用 M10 container（OS namespace + seccomp）。trusted 无【后端】层，安全性等于零（设计如此，用户显式 opt-in）。

T7 同时是本文档对 agent 现有 `ForbiddenImportRule`（仅处理 `ast.Import`/`ast.ImportFrom`）的已知缺口提示——`code_analyzer.py:88` 不处理动态导入，ForgeAgent 扩展该规则引擎时必须补上；但即便补上，静态层仍只是弱约束，不能替代后端隔离。

## 明确声明（写进 README / 文档，避免误解）

> **各档隔离强度（写进 README，让用户据此选档）**：
> - `trusted`：无隔离，同进程执行，代码能碰宿主一切。仅在你完全信任任务来源时用。
> - `restricted`（默认）：每块新起子进程 + 应用层限权（`sys.addaudithook` 拦 `open`/`socket.*` 事件、超时强杀、`rlimit` 资源限制[Unix]）。**能挡住绝大多数越权与相当一部分蓄意逃逸**，但限权是 Python 层审计钩子、非 OS 级隔离，`ctypes` 直调 syscall 绕过 Python 运行时等仍可绕过；也不防内核漏洞。适合日常使用与来源基本可信的任务。
> - `container`（M10，待定或不做）：OS 级隔离（namespace + seccomp），用于来源不可信或高风险场景。
>
> 一句话原则：**隔离强度 = 你选的档位对应后端能提供的强度**，与提示词或静态规则数量无关。若代码来源完全不可信且后果严重，用 container 档或干脆不在敏感环境运行。
> **平台差异**：`rlimit` 资源硬限仅 Unix（Linux+macOS）；Windows 下 restricted 的资源类缓解只有超时强杀（无内存/CPU 硬限），路径/网络限权跨平台一致。

## 未决 / 明确不做（v1 范围声明）

- **做** CPU/内存/文件数资源限额——子进程后端经 `rlimit` 实现，**仅 Unix（Linux+macOS）**；Windows 无 `resource` 模块，v1 不做 Windows 资源硬限（仅超时强杀），Job Objects 留待需要时再加。与超时（`SIGKILL`）一起构成资源类缓解。
- 不做多用户/多租户隔离（ForgeAgent 是单用户本地工具定位）。
- 不做代码签名/供应链完整性校验（超出轻量定位）。
- **不做** OS 级隔离（namespace/unshare/chroot/seccomp）——全是 Linux-only，违背跨平台与轻量。v1 restricted 统一走跨平台应用层限权；OS 级隔离留待 M10 container 档（待定或不做）。
- **不做**联网 Broker——v1 网络默认全拒即可（golden task 网络 mock 优先）。Broker（主进程代理出站请求 + 逐请求策略 + 日志）是将来"需要真联网"时才做的受控通道，架构已为它留位（子进程无网 + 主进程代理），但 v1 不实现。
- **子进程 IPC 协议是 M2 交付物**：主进程↔执行子进程的通道（代码/状态注入、结果/新状态回收、异常传播、超时/崩溃处理）需在 M2 明确设计。因每块新进程、无长连接，协议可极简（一次 spawn 一轮往返），但仍要显式规范序列化格式与错误传播，不留隐式行为。
