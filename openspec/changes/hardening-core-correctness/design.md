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

保留当前 callable confirmer 注入方式，使其能够格式化 `MCPArgs`、`WebFetchArgs` 和 `FileWriteArgs`。CLI 是否提供交互 confirmer 由终端能力决定，而不再依赖是否配置 MCP：stdin/stdout 为 TTY 时自动询问；非 TTY 时返回拒绝且不读取输入。`--interactive` 只保留 Survey 语义。

2026-07-13 至 2026-07-14 的实施期审查进一步确认，仅保护确认提示不足以覆盖同一数据流：WebFetch 的底层异常和 FileWrite 的成功/失败结果也会进入 Step feedback 与 CLI console；FileRead/FileList 失败文本还会回显宿主路径。用户已确认扩展当前 change。扩展仍不引入统一 sanitizer：WebFetch 的 SSRF、请求/协议和 artifact 保存失败使用固定安全类别消息；FileWrite 成功只返回 canonical `allowed_root` 内的 project-relative 路径，文件工具失败使用固定消息。确认 URL 的 hostname 在已知 secret 匹配前先 percent-decode，并以最长优先、单次非重叠、ASCII DNS 大小写不敏感语义匹配后重新编码；hostname helper 与 path/query 的全局 `mask_secrets()` 按组件各执行一次，不对重建 URL 二次全局脱敏。

备选方案是引入新的审批对象、策略引擎或 CI 预批准参数；当前没有足够需求支撑这些配置面，因此不采用。

### 3. 完成状态采用严格两阶段门控

每轮先解析响应。只要存在工具调用或解析错误，该轮就必须生成反馈并进入下一轮，忽略同轮 `completed: true`。工具成功与失败都遵循同一门控；只有后续响应同时满足“无工具调用、无解析错误、明确声明完成”时才结束任务。

该规则比“仅工具失败时阻止完成”更容易推理，也避免模型在尚未看到工具输出时提前确认结果。代价是工具任务至少增加一次模型往返，这是可信完成所需成本。

### 4. MCP 失败策略由服务级 `required` 决定

MCP 配置在每个服务上增加布尔字段 `required`，默认 `false`。可选服务连接失败时记录可诊断信息并从可用工具集合移除；任一必需服务连接失败时，CLI 启动失败并返回非零状态，同时清理已启动服务。

`MCPManager.close()` 使用单一 absolute deadline 约束 holder wait、cancel 和 thread join，允许重复调用，收集或记录关闭错误但不替换已有任务结果或启动错误。内部 shutdown 与 join 上限已在深度设计中确定，并由确定性测试锁定。主线程把 shutdown future 保存在 manager 上；loop coroutine 独占 Task wait/cancel，只移除已经完成的 holder，并返回 pending server names。future 超时时主线程 cancel 但保留 future，使用提交前的只读 holder-name fallback，不与仍活跃的 loop thread 竞态修改 holders/sessions。loop thread 使用固定名称；warning 记录 thread name/ident、alive 状态和 pending server 名称，不记录 arguments、env 或 server 内容。daemon thread 若被同步代码完全卡死，可能暂时保有 transport、file descriptor 或 MCP child process；Python 没有安全强杀线程的 API且 manager 没有 SDK child handle，CLI 必须优先按 deadline 返回并明确报告 shutdown incomplete。此时保留 shutdown future、holders、sessions、loop、thread 引用，重复 close 只重试 cancel/stop/join，并在线程停止后关闭 loop、清除引用。

备选方案“所有服务失败即启动失败”破坏可选集成，“所有服务静默降级”则无法表达生产必需依赖，因此采用服务级策略。

### 5. 黄金核心复用 pytest、MockClient 和本地 fixtures

建立单一 manifest 描述 20 个场景的 ID、输入、fixture、预期判定和标签。runner 复用现有 MockClient 与任务入口执行场景，自动判定并输出机器可读结果及人类可读通过率报告。基础 CI 只运行离线 fixture；其中 5 项标记为真实模型兼容，可通过显式命令和模型配置选择性运行，但结果不阻断基础 CI。

其余 360 项保留为候选目录，不生成虚假的已验证状态。优先选择覆盖网络拒绝、确认拒绝、完成门控、MCP 降级/失败及代表性成功任务的场景。实现不新增评测框架依赖。

### 6. 测试环境和文档都是验收边界

CLI/MCP 测试必须显式隔离 HOME 或配置根目录，任何测试都不得读取真实 `~/.forgeagent/mcp.yaml`。模型客户端契约、文本协议、威胁模型、黄金任务说明、README 和里程碑状态与实现同时更新，并由测试或文档一致性检查覆盖关键声明。

### 7. 文件路径包含判定使用 canonical commonpath

FileRead、FileWrite、FileList 和 restricted audit hook 均先 realpath root/target，再用 `os.path.commonpath()` 判断包含关系。该规则必须正确处理 `allowed_root="/"`、不同驱动器和非法 NUL 路径。安全失败消息不得包含模型提供的绝对路径或宿主 canonical root；不为两处小型判定新增共享策略模块。

FileWrite 使用 canonical target，因此替换原始 symlink alias 不能改变写入位置；但宿主并发写者仍可在检查和打开之间替换 canonical target 的祖先目录。完整消除需要跨平台 descriptor-relative 文件 API 重写，本 change 不采用 POSIX-only `openat/O_NOFOLLOW` 或 Linux-only `openat2`。该竞态作为 trusted 同进程代码、MCP 进程或宿主其他进程可触发的残余威胁记录，不把 File 工具描述为抵抗恶意宿主并发写者的 OS 级边界。

## Risks / Trade-offs

- [禁用环境代理会改变已有隐式联网行为] → 在发布说明和威胁模型中明确这是安全收紧；显式代理仅作为后续契约记录。
- [严格两阶段完成增加一次模型请求] → 仅在发生工具调用或解析错误时增加反馈轮，保持纯文本完成路径不变。
- [可选 MCP 降级可能掩盖配置错误] → 输出包含服务名和原因的诊断信息，并在必需场景使用 `required: true`。
- [关闭超时过短可能遗留子进程，过长会拖慢 CLI] → 以现有进程清理测试为基线确定小而有证据的上限，并验证无泄漏。
- [固定工具失败消息减少底层诊断] → 为 SSRF、请求、artifact 保存和各文件工具保留可区分的固定类别；不把平台异常文本送入模型反馈或普通 CLI 输出。
- [commonpath 修正会改变 FileRead/FileList 失败文本] → 这是有意的安全收紧；成功结果和允许范围不变，专项测试锁定新的固定消息。
- [realpath 与 pathname open 之间仍有 symlink ancestor-swap 竞态] → 明确分档和攻击前提；本 change 不用重复检查伪装修复，也不以平台专用 fd API扩大实现范围。
- [event-loop thread 完全卡死时可能暂留 MCP 子进程或文件描述符] → deadline 优先保证 CLI 可返回；保留引用、允许有界重试并输出无敏感信息的 incomplete-shutdown 诊断，不声称 Python 能安全强杀线程。
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
- 5 个真实模型兼容场景如何在不改变离线预期的前提下定义容差判定。
