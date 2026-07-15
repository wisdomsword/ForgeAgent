## Context

ForgeAgent 已具备 WebFetch、文件写入、MCP、文本协议工具调用和 MockClient 测试基础，但本次评审验证出四类边界不一致：`urllib` opener 会隐式继承环境代理；CLI confirmer 只理解 `MCPArgs` 且绑定条件错误；Step 会在同轮工具失败后接受完成声明；MCP 启动和关闭会受真实用户配置与无界等待影响。与此同时，380 项黄金任务目前只是文档目录，无法生成自动化通过率。

这些问题跨越 CLI、执行环、网络边界、MCP 生命周期、测试和文档。保持为一个 change，是因为它们共同定义“任务结果可信”的核心契约，且黄金验证核心需要统一覆盖其他四项能力；拆分会制造重复验收工件和跨 change 状态依赖。

约束包括：`spec.md` 优先、基础 CI 完全离线、不增加厂商专用逻辑、不修改 `resource/agent/`、优先复用现有标准库与测试设施、真实模型验证不作为合并门禁。

## Goals / Non-Goals

**Goals:**

- 关闭环境代理造成的 SSRF 校验与真实连接目标分离。
- 让受限工具共享一致、类型安全、可预测的确认行为。
- 让任务完成状态只反映经过反馈闭环后的最终响应。
- 让 MCP 服务故障按配置降级或失败，并保证关闭有界且不污染任务结果。
- 用 20 个离线场景建立可运行、可报告、可扩展的黄金验证核心。
- 让协议、威胁模型和里程碑文档与真实行为一致。

**Non-Goals:**

- 不实现代理转发、代理认证或 `NO_PROXY` 兼容逻辑。
- 不把 380 个候选任务一次性工程化，也不把真实模型结果设为 CI 门禁。
- 不引入新的通用框架、测试服务或外部依赖。
- 不借机重构无关 CLI、执行器、模型客户端或 MCP 协议。

## Decisions

### 1. 默认网络路径显式直连并收敛消费端失败

WebFetch 与 `/search` 使用禁用代理的 opener/handler，忽略 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 及大小写变体。现有 SSRF 地址分类、DNS 解析和重定向逐跳复核继续作为事实源；连接实现不得绕开这些检查。

ForgeAgent 专用显式代理契约只在文档中定义为未来能力，运行时本里程碑不接受代理转发。选择这一方案，是因为在没有可验证的“代理解析最终目标”机制前，启用代理会再次分离校验地址与连接地址。备选方案“信任系统代理”和“校验代理地址”均无法满足当前威胁模型。

该行为是 `[SECURITY][BREAKING]`：依赖企业环境代理的部署会直连失败，`NO_PROXY` 不能重新启用被空 `ProxyHandler` 移除的代理。当前迁移路径只包括允许进程直连、外部预取到 `allowed_root` 后通过 FileRead 处理，或使用用户显式信任并自行承担代理边界的 MCP fetch 工具。未来代理能力必须显式选择 trusted-forward-proxy 或 guarded-tunnel 信任模型，不能静默恢复环境 ProxyHandler。

`guarded_urlopen()` 只定义网络安全边界，WebFetch 和 `/search` 分别负责将打开、读取、关闭、HTTP 协议和响应解码阶段的预期异常收敛为稳定结果。WebFetch 的网络、SSRF 和 artifact 保存失败使用不同的固定安全消息；`/search` 的协议失败继续映射为 unavailable，未知 charset 回退 UTF-8 replacement decode。不得使用通用 `except Exception` 隐藏实现缺陷。

### 2. 扩展现有 confirmer，而非新增审批子系统

保留当前 callable confirmer 注入方式，使其能够格式化 `MCPArgs`、`WebFetchArgs` 和 `FileWriteArgs`。CLI 是否提供交互 confirmer 由终端能力决定，而不再依赖是否配置 MCP：单次 run 和 REPL 都只有在 stdin/stdout 为 TTY 时自动询问；非 TTY 时返回拒绝且不读取确认输入。`--interactive` 只保留 Survey 语义。MCP server/tool 标识、arguments mapping key 和 FileWrite 安全路径摘要也必须经过已知环境 secret 脱敏，并以 Rich literal 单行显示；C0/C1、换行、Unicode line separator、`Cf` 格式控制符和 `Cs` surrogate 必须显示为转义序列，不能把它们当作可信元数据、允许 bidi 控制重排审批文本，或在终端编码时使确认崩溃。

M9 规定的一个里程碑裸词兼容期已经结束。REPL 只路由 slash-prefixed 内嵌命令；裸 `models`、`reload`、`mcp` 和 `mcp ...` 恢复为普通模型目标。顶层 `forgeagent models` 子命令保持不变。

2026-07-13 至 2026-07-14 的实施期审查进一步确认，仅保护确认提示不足以覆盖同一数据流：WebFetch 的底层异常和 FileWrite 的成功/失败结果也会进入 Step feedback 与 CLI console；FileRead/FileList 失败文本还会回显宿主路径。用户已确认扩展当前 change。扩展仍不引入统一 sanitizer：WebFetch 的 SSRF、请求/协议和 artifact 保存失败使用固定安全类别消息；FileWrite 成功只返回 canonical `allowed_root` 内的 project-relative 路径，文件工具失败使用固定消息。确认 URL 的 hostname 在已知 secret 匹配前先 percent-decode，并以最长优先、单次非重叠、ASCII DNS 大小写不敏感语义匹配后重新编码；hostname helper 与 path/query 的全局 `mask_secrets()` 按组件各执行一次，不对重建 URL 二次全局脱敏。

备选方案是引入新的审批对象、策略引擎或 CI 预批准参数；当前没有足够需求支撑这些配置面，因此不采用。

### 3. 完成状态采用严格两阶段门控

每轮先解析响应。只要存在工具调用或解析错误，该轮就必须生成反馈并进入下一轮，忽略同轮 `completed: true`。工具成功与失败都遵循同一门控；只有后续响应同时满足“无工具调用、无解析错误、明确声明完成”时才结束任务。

该规则比“仅工具失败时阻止完成”更容易推理，也避免模型在尚未看到工具输出时提前确认结果。代价是工具任务至少增加一次模型往返，这是可信完成所需成本。

### 4. MCP 失败策略由服务级 `required` 决定

MCP 配置在每个服务上增加布尔字段 `required`，默认 `false`。可选服务连接失败时记录只含服务名与固定类别/异常类型的脱敏诊断并从可用工具集合移除；任一已启用的必需服务连接失败时，CLI 启动失败并返回非零状态，同时清理已启动服务。全部 initial holder 在第一次 await 前创建，并从共享 monotonic 起点并发等待 ready，避免多个卡死服务把启动等待放大为 N 倍连接 timeout。运行期 enable/disable 只承诺 manager 已因至少一个初始 enabled server 存在的 REPL；全 disabled 配置继续不创建 manager/loop，本 change 不增加 manager-less 会话动态启动能力。

`MCPManager.close()` 使用单一 absolute deadline 约束公开 holder wait、cancel 和 thread join，允许重复调用，收集或记录关闭错误但不替换已有任务结果或启动错误。主线程保存的 concurrent shutdown future 只是首次 bounded waiting facade；loop thread 保存唯一 generation-aware shutdown task，outer await 用 shield，future timeout/cancel 不得取消或复制权威 drain。facade 提交本身失败时，主线程关闭未调度 coroutine并 best-effort 请求同一 loop-owned drain，但绝不能根据暂时为空的 holder/session/lifecycle 容器伪造 completion。公开 deadline 到达后，若 async context finalizer 尚未完成，drain 继续在 live loop 上清理，不能提前 stop loop；普通内部异常按 slot 隔离，只有最终 cleanup 不变量成立才发布 completion，否则同一 task 等待 repeated-close retry signal，不结束也不 busy-loop。loop task 独占 closing state、slot snapshot、Task wait/cancel 和 conditional remove。主线程使用 pre-submit name fallback 诊断，不与活跃 loop 竞态修改 holders/sessions。loop thread 使用固定名称；warning 记录 thread name/ident、alive 状态和脱敏 pending server 名称，不记录 arguments、env 或 server 内容。daemon thread 若被同步代码完全卡死，可能暂时保有 transport、file descriptor 或 MCP child process；Python 没有安全强杀线程的 API且 manager 没有 SDK child handle，CLI 必须优先按 deadline 返回并明确报告 shutdown incomplete。此时保留 shutdown future/task、holders、sessions、loop、thread 引用；重复 close 唤醒既有 drain并用线程安全 completion event 消费新 shutdown 预算，再 bounded stop/join，不创建第二个 facade/task。只有 cleanup completion 已证明、线程停止且 `loop.close()` 成功后才清除引用；loop close 失败保留停止的 loop 供后续 close 重试。

实施期并发审查证明 holder 不能仅以 server name 表示所有权，也证明不能把 `run_coroutine_threadsafe()` 的 future 直接当成纯 waiter：loop 尚未开始 coroutine 时取消 future 会丢失 reconcile intent。重设计采用 loop-owned reconcile 与 generation token：`_holders` 保存 `(generation, task, stop_event)`，`_sessions` 保存 `(generation, session)`；generation 只在 loop thread 真正启动 holder 时递增，`restart_after_generation` 将 replacement intent 与 teardown state 分开。disable teardown 完成前 holder slot 始终可见，enable 在旧代 tearing down 或 unavailable-finalizing 时只记录本代 restart intent，task done 后由 generation-conditional finalizer 摘除旧 slot，再由 loop reconcile 启动至多一个 replacement。call failure 清理当前代但不隐式自动重连，保留显式 enable 重试语义。holder 的 status/tools/session 写入和 call failure handling 都必须验证 generation；`call_tool()` 由 loop wrapper 在执行时选择 current session，main thread 不缓存 ClientSession。enable/disable/connect 使用必达的 loop-owned operation 和独立可取消 waiter；timeout 后 loop callback 幂等确保 operation 启动，operation task 进入 lifecycle 集，disable 内部用 shield 保证 holder cleanup 不被取消。主线程首次 close 发布 `_closed` 与 loop thread 的 generation/task/slot/finalizer 分配使用一个只覆盖无 await 代码的最小 lifecycle lock 原子排序：close-first 不分配，start-first 在释放锁前留下完整可 snapshot slot。随后 shutdown entry 在 loop thread 设置 closing state并 snapshot 精确 holder 与 lifecycle operation；manager closed/closing 后禁止 replacement，shutdown completion 还要求 lifecycle 集为空。这样 timed-out disable、立即 re-enable、并发 close、旧 finally、旧 call failure 和 pending lifecycle operation 都无法误删或污染新代资源。

Loop startup 同样是 transaction，并持续到 initial holders submission/result 完成。局部 worker 在 publication gate 前不得进入 `run_forever()`，并在短周期 gate wait 中同时检查 cancel，使 gate release 在真正 set 前抛错时也可退出；manager refs 与 started state 发布成功后才 release。start、publication 或 gate release 抛出控制异常时，cancel/release gate，必要时请求 loop stop，bounded join；线程停止且 loop close 成功后才 rollback 为可重试状态。线程仍活，或线程已停但 loop close 失败时，都保留 refs、置 started/closed、标记批准的 pre-holder cleanup completion并记录仅含固定类型/线程身份的 warning，使后续 `close()` 可以重试而不会分配第二个 loop。publication 后 initial holder 基础设施失败也必须由 `connect()` 先 bounded close；普通 Exception 再映射为固定 startup error，`KeyboardInterrupt`/`SystemExit` cleanup 后原样传播，其他 cleanup `BaseException` 只记录固定类型。不得在 cleanup 未完全成功时清空 refs，否则会制造无法诊断的隐藏资源。

同步 facade 仍按 CLI/Task 的单 caller thread 使用，不承诺多个 OS thread 同时调用 enable/disable/call/close；需要处理的 overlap 是前一个 `_submit` timeout 后 loop operation 继续执行、同一 caller 再发下一操作。本次只跟踪 lifecycle operation，不新增通用 tool-call registry。MCP SDK call 继续由 inner read timeout 先于 outer facade timeout 收敛；event-loop 同步 hard-stuck 时的未完成 call 属于既有 incomplete-shutdown residual。

备选方案“所有服务失败即启动失败”破坏可选集成，“所有服务静默降级”则无法表达生产必需依赖，因此采用服务级策略。

### 5. 黄金核心复用 pytest 和本地 fixtures

建立单一 manifest 描述 20 个场景的 ID、输入、fixture、预期判定和标签。进入 Agent 循环的场景复用现有 MockClient；CLI、Tool、RestrictedBackend、guarded URL 和本地 stdio MCP 等边界场景允许直接调用对应入口，以本地 fixture 自动判定并输出机器可读结果及人类可读通过率报告。场景 evidence 只允许 `None`/bool/string/int/finite float/list/`dict[str, value]`；runner 先递归验证类型和 key，再严格编码，将 tuple、非字符串 key、非序列化值或非有限值收敛为单项失败，避免 encoder 静默改写 key或最后写报告时丢失整套结果。standalone offline entry 的模块顶层只导入标准库，必须先建立临时 `HOME`/`USERPROFILE`/`XDG_CONFIG_HOME`，再 local-import manifest/cases 及 CLI/MCP/model 配置相关模块，防止 import-time 默认路径读取真实用户配置，并在 `finally` 恢复原环境。基础 CI 只运行离线 fixture；其中 5 项标记为真实模型兼容，可通过显式命令和模型配置选择性运行，但结果不阻断基础 CI。真实模式与对应离线场景使用同一 fixture 和 judge，只替换 client，不放宽容差；真实模型偏差可以使该次非门禁运行失败。

其余 360 项保留为候选目录，不生成虚假的已验证状态。优先选择覆盖网络拒绝、确认拒绝、完成门控、MCP 降级/失败及代表性成功任务的场景。实现不新增评测框架依赖。

### 6. 测试环境和文档都是验收边界

CLI/MCP 测试必须显式隔离 HOME 或配置根目录，任何测试都不得读取真实 `~/.forgeagent/mcp.yaml`。模型客户端契约、文本协议、威胁模型、黄金任务说明、README 和里程碑状态与实现同时更新，并由测试或文档一致性检查覆盖关键声明。

### 7. 文件路径包含判定使用 canonical commonpath

WebFetch 生成的直接子文件 artifact 与 FileRead、FileWrite、FileList 均通过主进程现有 `_validate_path()` 先 realpath root/target，再用 `os.path.commonpath()` 判断包含关系；restricted audit hook 独立实施同一不变量。该规则必须正确处理 `allowed_root="/"`、不同驱动器、非法 NUL 路径和预置同名 artifact symlink 指向 root 外的情况。当前 artifact filename 没有中间目录；通用后代/祖先 component 解析由 File 工具用例覆盖。安全失败消息不得包含模型提供的绝对路径或宿主 canonical root；不新增共享策略模块。

FileWrite 使用 canonical target，因此替换模型最初提供的 symlink alias 不能改变写入位置；但宿主并发写者仍可在检查和打开之间替换 canonical target 本身或其祖先路径组件。完整消除需要跨平台 descriptor-relative 文件 API 重写，本 change 不采用 POSIX-only `openat/O_NOFOLLOW` 或 Linux-only `openat2`。该竞态作为 trusted 同进程代码、MCP 进程或宿主其他进程可触发的残余威胁记录，不把 File 工具描述为抵抗恶意宿主并发写者的 OS 级边界。

## Risks / Trade-offs

- [禁用环境代理会改变已有隐式联网行为] → 在发布说明和威胁模型中明确这是安全收紧；显式代理仅作为后续契约记录。
- [严格两阶段完成增加一次模型请求] → 仅在发生工具调用或解析错误时增加反馈轮，保持纯文本完成路径不变。
- [可选 MCP 降级可能掩盖配置错误] → 输出包含服务名和原因的诊断信息，并在必需场景使用 `required: true`。
- [关闭超时过短可能遗留子进程，过长会拖慢 CLI] → 以现有进程清理测试为基线确定小而有证据的上限，并验证无泄漏。
- [固定工具失败消息减少底层诊断] → 为 SSRF、请求、artifact 保存和各文件工具保留可区分的固定类别；不把平台异常文本送入模型反馈或普通 CLI 输出。
- [commonpath 修正会改变 FileRead/FileList 失败文本] → 这是有意的安全收紧；成功结果和允许范围不变，专项测试锁定新的固定消息。
- [realpath 与 pathname open 之间仍有 symlink target/ancestor-component swap 竞态] → 明确分档和攻击前提；本 change 不用重复检查伪装修复，也不以平台专用 fd API扩大实现范围。
- [WebFetch artifact 名称可预测，静态 symlink 可把写入引向 root 外] → 写入前复用 `_validate_path()` 并使用 canonical target；保留与 FileWrite 相同的恶意宿主并发 target/ancestor-component swap 残余，不新增平台专用 API。
- [event-loop thread 完全卡死时可能暂留 MCP 子进程或文件描述符] → deadline 优先保证 CLI 可返回；保留引用、允许有界重试并输出无敏感信息的 incomplete-shutdown 诊断，不声称 Python 能安全强杀线程。
- [generation-safe slot 会改变 MCPManager 内部 holder/session 形状] → 只在 manager 内部使用 `(generation, object)`，不扩大 YAML 或工具 API；call/enable/disable/close 专项测试共同锁定读取和清理语义。
- [可取消 lifecycle waiter 可能在 loop 忙时连 intent 一起丢失] → reconcile 使用必达的 loop-owned operation，facade timeout 后以 loop callback 幂等 ensure；operation 集由 shutdown 精确取消/等待，disable await 继续用 shield 保护 holder cleanup。
- [并发 ready deadline 可能让慢服务更早显示 unavailable] → timeout 仍是同一 per-server 配置，只把计时起点固定到实际并发启动时刻；迟到 publish 仍受 generation/desired/closing 检查。
- [startup rollback 自身遭遇控制异常时可能进入 partial-start] → worker 在 publication gate 前不能运行 loop；正常 rollback 后恢复可重试状态，极端仍活分支保留 refs/closed warning，禁止清空后制造隐藏线程。
- [20 项核心不能代表全部任务空间] → 报告明确分离“核心已验证”与“候选未验证”，后续按风险增量扩展。
- [单一 change 范围较大] → tasks 按能力分组、每组独立测试，黄金核心作为最终统一验收，不引入跨组抽象。

## Migration Plan

1. 先用失败测试锁定环境代理绕过、确认器类型错误、同轮完成和 MCP 生命周期问题。
2. 按网络、确认/文件路径、完成、MCP 四个边界组实施最小修复，并运行对应单元与 CLI 测试。
3. 建立隔离测试环境和 20 项离线黄金核心，再补 5 项真实模型兼容标签。
4. 同步文档与里程碑，运行静态检查、隔离全量测试、黄金 runner 和可用的环境专项测试。
5. 若发生回退，按能力组撤销行为改动；黄金 fixtures 和文档不得继续声称被回退能力已验证。

## Open Questions

- 显式代理未来契约采用哪个配置路径和最小字段集合；本里程碑只需文档化且不启用运行时转发。
