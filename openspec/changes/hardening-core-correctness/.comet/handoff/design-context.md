# Comet Design Handoff

- Change: hardening-core-correctness
- Phase: design
- Mode: compact
- Context hash: 1e828b304218e0d381a08f610af0c9c356c925391c11f5f8bf6a579df87032ac

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/hardening-core-correctness/proposal.md

- Source: openspec/changes/hardening-core-correctness/proposal.md
- Lines: 1-34
- SHA256: 4bc899cb4128c08af9563800c34ae3afe08966341e7b7e25029a0772abd9602e

```md
## Why

本次 CodeGraph、静态检查和测试评审发现 ForgeAgent 在网络边界、工具确认、任务完成判定和 MCP 生命周期上存在可被触发的正确性或安全风险；同时，现有黄金任务目录不能产生可重复的自动验证证据。现在需要把这些问题收敛为一个可设计、可实施、可验收的加固里程碑，避免安全修复与验证口径继续分离。

## What Changes

- 默认禁用环境代理对 WebFetch 和 `/search` 的影响，确保 SSRF 校验针对实际直连目标；仅记录 ForgeAgent 显式代理配置契约，本里程碑不实现代理功能。
- 为 WebFetch、FileWrite、MCP 统一确认器；TTY 自动询问，非 TTY 默认拒绝，`--interactive` 继续只控制 Survey。
- 采用严格两阶段完成语义：含工具调用、工具失败或解析错误的响应不得完成任务；只有后续无工具、无解析错误的独立响应才可声明完成。
- 增加 MCP 服务级 `required` 配置；可选服务失败时降级，必需服务失败时 CLI 以非零状态启动失败；关闭流程有界、幂等且不覆盖原任务结果。
- 隔离测试 HOME 和 MCP 配置，避免测试读取用户机器上的真实配置。
- 建立 20 个完全离线、可执行、自动判定并生成报告的黄金验证核心，其中 5 个场景支持可选真实模型运行；其余目录项明确标记为候选而非已验证。
- 同步模型客户端、文本协议、威胁模型、黄金任务、README 和里程碑文档，消除实现与文档契约漂移。

## Capabilities

### New Capabilities

- `network-boundary-safety`: 规定 WebFetch 和搜索请求的代理、目标地址、重定向和逐跳 SSRF 边界。
- `tool-approval`: 规定 WebFetch、FileWrite、MCP 的统一确认接口、TTY 行为和非交互拒绝策略。
- `completion-integrity`: 规定工具调用、工具结果、解析错误与 `task_status.completed` 之间的完成状态转换。
- `mcp-resilience`: 规定 MCP 服务的 `required` 启动策略、降级行为和关闭生命周期保证。
- `golden-validation-core`: 规定离线黄金场景 manifest、fixture、自动判定、报告和可选真实模型运行边界。

### Modified Capabilities

无。当前仓库不存在可修改的既有 OpenSpec capability spec；协议和文档同步将在实现与验证任务中完成。

## Impact

- 影响 `src/forgeagent/ssrf_guard.py`、`src/forgeagent/cli.py`、`src/forgeagent/step.py`、`src/forgeagent/mcp_manager.py` 及其调用方。
- 新增或调整 MCP 配置字段、工具确认器接口和任务完成状态判定，属于用户可观察行为契约变化。
- 扩展测试 fixtures、隔离环境、黄金任务 runner 和报告产物；基础 CI 保持完全离线，不依赖供应商 API key、Docker 或外部网络。
- 更新相关 `docs/`、README、里程碑和威胁模型文档；不修改 `resource/agent/`，不引入厂商专用端点或凭证。

```

## openspec/changes/hardening-core-correctness/design.md

- Source: openspec/changes/hardening-core-correctness/design.md
- Lines: 1-87
- SHA256: 02e7e48a083bf09e4a57f0be13f72c630afcc02a260a44a951d6154eb202993c

[TRUNCATED]

```md
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

### 1. 默认网络路径显式直连

WebFetch 与 `/search` 使用禁用代理的 opener/handler，忽略 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 及大小写变体。现有 SSRF 地址分类、DNS 解析和重定向逐跳复核继续作为事实源；连接实现不得绕开这些检查。

ForgeAgent 专用显式代理契约只在文档中定义为未来能力，运行时本里程碑不接受代理转发。选择这一方案，是因为在没有可验证的“代理解析最终目标”机制前，启用代理会再次分离校验地址与连接地址。备选方案“信任系统代理”和“校验代理地址”均无法满足当前威胁模型。

### 2. 扩展现有 confirmer，而非新增审批子系统

保留当前 callable confirmer 注入方式，使其能够格式化 `MCPArgs`、`WebFetchArgs` 和 `FileWriteArgs`。CLI 是否提供交互 confirmer 由终端能力决定，而不再依赖是否配置 MCP：stdin/stdout 为 TTY 时自动询问；非 TTY 时返回拒绝且不读取输入。`--interactive` 只保留 Survey 语义。

备选方案是引入新的审批对象、策略引擎或 CI 预批准参数；当前没有足够需求支撑这些配置面，因此不采用。

### 3. 完成状态采用严格两阶段门控

每轮先解析响应。只要存在工具调用或解析错误，该轮就必须生成反馈并进入下一轮，忽略同轮 `completed: true`。工具成功与失败都遵循同一门控；只有后续响应同时满足“无工具调用、无解析错误、明确声明完成”时才结束任务。

该规则比“仅工具失败时阻止完成”更容易推理，也避免模型在尚未看到工具输出时提前确认结果。代价是工具任务至少增加一次模型往返，这是可信完成所需成本。

### 4. MCP 失败策略由服务级 `required` 决定

MCP 配置在每个服务上增加布尔字段 `required`，默认 `false`。可选服务连接失败时记录可诊断信息并从可用工具集合移除；任一必需服务连接失败时，CLI 启动失败并返回非零状态，同时清理已启动服务。

`MCPManager.close()` 使用固定上限包围每个关闭步骤，允许重复调用，收集或记录关闭错误但不替换已有任务结果或启动错误。具体超时常量在深度设计阶段依据现有进程退出路径确定，并通过确定性测试锁定。

备选方案“所有服务失败即启动失败”破坏可选集成，“所有服务静默降级”则无法表达生产必需依赖，因此采用服务级策略。

### 5. 黄金核心复用 pytest、MockClient 和本地 fixtures

建立单一 manifest 描述 20 个场景的 ID、输入、fixture、预期判定和标签。runner 复用现有 MockClient 与任务入口执行场景，自动判定并输出机器可读结果及人类可读通过率报告。基础 CI 只运行离线 fixture；其中 5 项标记为真实模型兼容，可通过显式命令和模型配置选择性运行，但结果不阻断基础 CI。

其余 360 项保留为候选目录，不生成虚假的已验证状态。优先选择覆盖网络拒绝、确认拒绝、完成门控、MCP 降级/失败及代表性成功任务的场景。实现不新增评测框架依赖。

### 6. 测试环境和文档都是验收边界

CLI/MCP 测试必须显式隔离 HOME 或配置根目录，任何测试都不得读取真实 `~/.forgeagent/mcp.yaml`。模型客户端契约、文本协议、威胁模型、黄金任务说明、README 和里程碑状态与实现同时更新，并由测试或文档一致性检查覆盖关键声明。

## Risks / Trade-offs

- [禁用环境代理会改变已有隐式联网行为] → 在发布说明和威胁模型中明确这是安全收紧；显式代理仅作为后续契约记录。
- [严格两阶段完成增加一次模型请求] → 仅在发生工具调用或解析错误时增加反馈轮，保持纯文本完成路径不变。
- [可选 MCP 降级可能掩盖配置错误] → 输出包含服务名和原因的诊断信息，并在必需场景使用 `required: true`。
- [关闭超时过短可能遗留子进程，过长会拖慢 CLI] → 以现有进程清理测试为基线确定小而有证据的上限，并验证无泄漏。
- [20 项核心不能代表全部任务空间] → 报告明确分离“核心已验证”与“候选未验证”，后续按风险增量扩展。
- [单一 change 范围较大] → tasks 按能力分组、每组独立测试，黄金核心作为最终统一验收，不引入跨组抽象。

## Migration Plan

1. 先用失败测试锁定环境代理绕过、确认器类型错误、同轮完成和 MCP 生命周期问题。
2. 按网络、确认/完成、MCP 三个边界组实施最小修复，并运行对应单元与 CLI 测试。
3. 建立隔离测试环境和 20 项离线黄金核心，再补 5 项真实模型兼容标签。
4. 同步文档与里程碑，运行静态检查、隔离全量测试、黄金 runner 和可用的环境专项测试。
5. 若发生回退，按能力组撤销行为改动；黄金 fixtures 和文档不得继续声称被回退能力已验证。

```

Full source: openspec/changes/hardening-core-correctness/design.md

## openspec/changes/hardening-core-correctness/tasks.md

- Source: openspec/changes/hardening-core-correctness/tasks.md
- Lines: 1-53
- SHA256: f0b7dd6ae379c7b508de486922897fa18f481abb0b5139db35f668a7b941a017

```md
## 1. 回归基线与测试隔离

- [ ] 1.1 将环境代理绕过、通用 confirmer 类型错误、同轮工具完成和 MCP 关闭卡住的复现固化为失败回归测试
- [ ] 1.2 为 CLI/MCP 测试提供隔离 HOME 或配置根目录 fixture，证明真实 `~/.forgeagent/mcp.yaml` 不影响测试结果
- [ ] 1.3 审核本地监听权限和进程计数相关测试，改为能力探测或稳定断言，并保留对真实资源泄漏的检测
- [ ] 1.4 记录当前静态检查、隔离全量测试、Docker/网络可用性和已知环境限制，作为实施前基线

## 2. 网络边界安全

- [ ] 2.1 增加大小写环境代理变量下 WebFetch 和 `/search` 必须直连的测试，并覆盖代理指向回环目标的绕过场景
- [ ] 2.2 让受保护的 URL opener 显式禁用环境代理，同时复用现有目标解析、地址分类和逐跳重定向校验
- [ ] 2.3 补齐私网、回环、链路本地、NAT64 和公网页面重定向到私网的回归覆盖
- [ ] 2.4 文档化 ForgeAgent 专用显式代理的未来契约与“本里程碑不实现代理转发”的边界

## 3. 工具确认与完成完整性

- [ ] 3.1 为 MCP、WebFetch、FileWrite 参数分别增加 confirmer 格式化与批准/拒绝测试
- [ ] 3.2 扩展现有 confirmer 使其类型安全地支持三类工具参数，不引入新的审批框架
- [ ] 3.3 按 TTY 能力为 REPL 和单次 run 自动注入 confirmer，验证非 TTY 默认拒绝且 `--interactive` 仍只控制 Survey
- [ ] 3.4 增加工具成功、工具失败、解析错误与 `completed: true` 组合的 Step 状态转换测试
- [ ] 3.5 实施严格两阶段完成门控，只有后续无工具、无解析错误的独立响应可完成任务

## 4. MCP 韧性与生命周期

- [ ] 4.1 在 MCP 服务配置模型中增加默认 `false` 的 `required` 字段及兼容性解析测试
- [ ] 4.2 实施可选服务连接失败降级，验证失败服务工具被排除且诊断包含服务名和原因
- [ ] 4.3 实施必需服务连接失败的启动中止、资源清理和 CLI 非零退出测试
- [ ] 4.4 为正常关闭、无响应子进程、部分关闭失败和重复 close 建立确定性测试并确定有证据的超时上限
- [ ] 4.5 使 `MCPManager.close()` 有界且幂等，并保证关闭错误不覆盖任务结果或原始启动错误

## 5. 黄金验证核心

- [ ] 5.1 从 380 项候选中确定覆盖核心成功路径和本次风险边界的 20 个场景，并建立单一 manifest
- [ ] 5.2 为 20 个场景提供完全离线的 MockClient 响应、本地输入和自动判定期望
- [ ] 5.3 实现可重复 runner，输出逐场景机器可读结果、失败原因、人类可读汇总和通过率，并以失败状态控制退出码
- [ ] 5.4 标记其中 5 个真实模型兼容场景，提供显式 opt-in 运行入口和独立报告，确保基础 CI 不访问外部模型
- [ ] 5.5 将黄金核心接入项目验证命令，验证无网络、无 Docker、无凭证、隔离 HOME 环境下可完整执行

## 6. 契约与里程碑文档

- [ ] 6.1 更新模型客户端契约，准确描述当前 complete/streaming 和多模态支持边界
- [ ] 6.2 更新文本协议规范，纳入 WebFetch、FileRead/FileWrite 及严格两阶段完成语义
- [ ] 6.3 更新威胁模型和 CLI 文档，说明默认直连、环境代理禁用、TTY 确认和 MCP `required` 行为
- [ ] 6.4 更新黄金任务说明和 README，将 20 项标为可执行可信核心、其余 360 项标为候选，并说明 5 项真实模型运行不是 CI 门禁
- [ ] 6.5 按 `MILESTONE_GUIDE.md` 更新 ACTION_PLAN、相关历史状态说明、新加固里程碑文件和 `milestones/latest`，保留实证测试结果

## 7. 综合验证与审查

- [ ] 7.1 运行 Ruff 静态检查并修复本 change 引入的问题
- [ ] 7.2 在隔离 HOME 下运行完整 pytest，确保环境能力不足只产生有理由的 skip，不依赖人工 deselect
- [ ] 7.3 运行 SSRF/代理、CLI 确认、Step 完成和 MCP 生命周期专项测试，记录命令、结果与任何环境限制
- [ ] 7.4 运行 20 项离线黄金核心并核对逐项结果、报告、通过率和退出码；有凭证时仅补充非门禁的 5 项真实模型报告
- [ ] 7.5 对照 `spec.md`、本 change specs 和 CodeGraph 调用路径执行代码审查，确认没有扩大范围、遗漏调用方或产生文档漂移

```

## openspec/changes/hardening-core-correctness/specs/completion-integrity/spec.md

- Source: openspec/changes/hardening-core-correctness/specs/completion-integrity/spec.md
- Lines: 1-30
- SHA256: 8cba8b659e3c3af0774ab4c74b6f298f0a6752ad9b24e71ed3566135d53c1944

```md
## ADDED Requirements

### Requirement: Tool-bearing responses cannot complete a task
ForgeAgent MUST ignore a completion declaration in any response that also contains one or more tool calls and SHALL feed the tool results into a later round.

#### Scenario: Successful tool and completion declaration share a response
- **WHEN** a model response declares `completed: true` and invokes a tool that succeeds
- **THEN** ForgeAgent records the tool result, continues to another model round and does not mark the task complete from that response

#### Scenario: Failed tool and completion declaration share a response
- **WHEN** a model response declares `completed: true` and invokes a tool that fails
- **THEN** ForgeAgent records the failure, continues to another model round and does not mark the task complete

### Requirement: Parse errors prevent same-round completion
ForgeAgent MUST NOT complete a task from a response that contains protocol parse errors, even when that response also declares completion.

#### Scenario: Completion declaration accompanies a parse error
- **WHEN** a model response contains a parse error and `completed: true`
- **THEN** ForgeAgent feeds the parse error back for correction and keeps the task incomplete

### Requirement: Completion requires a standalone final response
ForgeAgent SHALL mark a task complete only from a response that explicitly declares completion and contains neither tool calls nor protocol parse errors.

#### Scenario: Standalone completion after tool feedback
- **WHEN** a tool-bearing response has been processed and a later response contains no tools, no parse errors and declares `completed: true`
- **THEN** ForgeAgent marks the task complete using the later response

#### Scenario: Standalone response does not declare completion
- **WHEN** a response contains no tools and no parse errors but does not declare completion
- **THEN** ForgeAgent does not fabricate a completed status

```

## openspec/changes/hardening-core-correctness/specs/golden-validation-core/spec.md

- Source: openspec/changes/hardening-core-correctness/specs/golden-validation-core/spec.md
- Lines: 1-56
- SHA256: c6de5321d8e3e6387b0645c6c2d18c516d4961df1fa10f304e156a3616d93968

```md
## ADDED Requirements

### Requirement: Golden core contains exactly twenty offline scenarios
ForgeAgent SHALL maintain a trusted core manifest containing exactly G01, G03, G05, G06, G08, G11, G13, G14, G15, G17, G27, G43, G58, G59, G324, G329, G330, G332, G333 and G355. Every scenario SHALL execute with MockClient and local fixtures without network access, Docker, vendor credentials or user configuration.

#### Scenario: Base CI runs the golden core
- **WHEN** the golden core command runs in an isolated environment with no network or model credentials
- **THEN** all 20 scenarios execute and each produces an automatic pass or fail result

#### Scenario: Manifest selection is validated
- **WHEN** the golden runner performs preflight validation
- **THEN** it rejects duplicate, missing, additional or substituted scenario IDs before executing the suite

#### Scenario: Core IDs remain defined in the candidate catalog
- **WHEN** automated documentation consistency tests inspect the trusted-core manifest and `docs/golden-tasks-seed.md`
- **THEN** every manifest ID has a corresponding task definition in the candidate catalog

### Requirement: Golden scenarios are machine judged and reported
The golden runner MUST validate declared expectations for each scenario and SHALL emit both machine-readable results and a human-readable summary containing counts and pass rate.

#### Scenario: All expectations pass
- **WHEN** every scenario satisfies its declared outcome
- **THEN** the runner reports 20 passed, 0 failed and a 100 percent pass rate with a successful process exit

#### Scenario: One expectation fails
- **WHEN** any scenario violates its declared outcome
- **THEN** the runner identifies the scenario and failed expectation, reports a reduced pass rate and exits non-zero

### Requirement: Five core scenarios support opt-in real-model execution
Exactly G01, G03, G08, G11 and G43 SHALL be tagged as compatible with an explicitly configured real model, and real-model execution MUST remain opt-in and outside the base CI gate.

#### Scenario: No real-model option is supplied
- **WHEN** the base golden command runs without a real-model selection
- **THEN** all scenarios use MockClient and no external model request is made

#### Scenario: Real-model execution is requested
- **WHEN** a user supplies the explicit real-model command and valid model configuration
- **THEN** the runner executes only the 5 compatible scenarios and produces a separate pass-rate report

#### Scenario: Real-model preflight lacks configuration or credentials
- **WHEN** a user explicitly requests real-model execution but the selected model cannot be resolved or authenticated
- **THEN** the runner exits with status 2 before executing scenarios and does not generate a pass-rate report

### Requirement: Candidate catalog is not presented as validated
ForgeAgent documentation SHALL distinguish the 20 executable trusted-core scenarios from the remaining candidate task catalog and MUST NOT describe candidates as validated without executable evidence.

#### Scenario: User reads golden task documentation
- **WHEN** documentation lists the wider task catalog
- **THEN** it labels 20 scenarios as executable trusted core and the other 360 entries as candidates

### Requirement: Public protocol documentation matches runtime behavior
The milestone SHALL update model-client, text-protocol, threat-model, README and milestone documentation so claims about streaming, multimodal input, WebFetch/File tools, proxy behavior and golden validation match the verified implementation.

#### Scenario: Documentation is reviewed after implementation
- **WHEN** the change is ready for verification
- **THEN** affected documents no longer contradict supported runtime contracts or claim unexecuted validation

```

## openspec/changes/hardening-core-correctness/specs/mcp-resilience/spec.md

- Source: openspec/changes/hardening-core-correctness/specs/mcp-resilience/spec.md
- Lines: 1-60
- SHA256: 67af21c5c9e31929baecc3d219700b7d588635dbfe42b1754799d059f2f1d5a3

```md
## ADDED Requirements

### Requirement: MCP service criticality is configured per server
ForgeAgent SHALL support a boolean `required` setting on each MCP server configuration, SHALL treat an omitted setting as `false`, and SHALL apply the startup requirement only when that server is enabled.

#### Scenario: Optional server omits required
- **WHEN** an MCP server configuration does not specify `required`
- **THEN** ForgeAgent treats the server as optional

#### Scenario: Required server is declared
- **WHEN** an MCP server configuration sets `required: true`
- **THEN** ForgeAgent treats successful connection to that server as a CLI startup requirement

#### Scenario: Required server is explicitly disabled
- **WHEN** an MCP server configuration sets `required: true` and `enabled: false`
- **THEN** ForgeAgent does not connect the server and does not fail initial CLI startup because of that server

### Requirement: Optional MCP failures degrade predictably
ForgeAgent SHALL continue startup when an optional MCP server fails to connect, SHALL exclude that server's unavailable tools, and SHALL emit diagnostic information naming the failed server and cause.

#### Scenario: Optional server connection fails
- **WHEN** an optional MCP server cannot start or complete its connection handshake
- **THEN** the CLI remains usable with other tools and reports the degraded server

### Requirement: Required MCP failures abort startup
ForgeAgent MUST return a non-zero CLI startup result when a required MCP server fails to connect and MUST clean up MCP resources that were already started.

#### Scenario: Required server connection fails
- **WHEN** a required MCP server cannot start or complete its connection handshake
- **THEN** the CLI reports a startup error, closes already-started MCP resources and exits non-zero before running the task

#### Scenario: User changes a required server during an active REPL
- **WHEN** the REPL has already started and the user explicitly disables or enables a server configured with `required: true`
- **THEN** ForgeAgent updates and reports that server's runtime status without terminating the existing REPL session

### Requirement: MCP shutdown is bounded and idempotent
`MCPManager.close()` MUST finish within configured internal bounds, SHALL tolerate repeated calls, and MUST NOT replace an existing task or startup result with a shutdown failure.

#### Scenario: Child process does not exit promptly
- **WHEN** an MCP child process does not respond during normal shutdown
- **THEN** ForgeAgent cancels pending holders, bounds event-loop and thread cleanup by an absolute deadline, and returns from close without waiting indefinitely

#### Scenario: Internal shutdown operation raises unexpectedly
- **WHEN** an internal holder, event-loop or thread cleanup operation raises an Exception
- **THEN** `close()` records the failure, keeps the manager closed and does not propagate the shutdown exception to replace the caller's result

#### Scenario: Close is called more than once
- **WHEN** `close()` is invoked after resources have already been closed or a previous close partially failed
- **THEN** the call completes without reopening resources or raising an idempotency error

#### Scenario: Shutdown fails after task result exists
- **WHEN** task execution has produced a result and an MCP shutdown step fails
- **THEN** ForgeAgent preserves the task result and reports the shutdown problem separately

### Requirement: Tests do not consume user MCP configuration
ForgeAgent's automated tests MUST isolate the configuration home used by CLI and MCP discovery from the developer's real home directory.

#### Scenario: User home contains MCP configuration
- **WHEN** the machine running tests has `~/.forgeagent/mcp.yaml`
- **THEN** tests use an isolated configuration root and their result is independent of that file

```

## openspec/changes/hardening-core-correctness/specs/network-boundary-safety/spec.md

- Source: openspec/changes/hardening-core-correctness/specs/network-boundary-safety/spec.md
- Lines: 1-45
- SHA256: b93a5595dba83c2be4e9c1dae0fae9e5b03cfac749de3d51fd01663b086293f4

```md
## ADDED Requirements

### Requirement: Web requests ignore environment proxies by default
ForgeAgent SHALL make WebFetch and `/search` requests through an explicitly direct connection path and SHALL NOT consume proxy settings from process environment variables.

#### Scenario: HTTP proxy is present
- **WHEN** `HTTP_PROXY`, `HTTPS_PROXY` or `ALL_PROXY` points to a reachable proxy and no ForgeAgent-specific proxy capability is implemented
- **THEN** WebFetch and `/search` connect directly through the SSRF guard and never send the request to that proxy

#### Scenario: Lowercase proxy variables are present
- **WHEN** lowercase proxy environment variables are configured
- **THEN** they do not alter WebFetch or `/search` routing

### Requirement: Every effective target is SSRF validated
ForgeAgent MUST validate the effective destination of the initial request and every redirect hop using the existing blocked-address rules before opening the corresponding connection.

#### Scenario: Initial target resolves to a blocked address
- **WHEN** a request target resolves to loopback, private, link-local or another address forbidden by the threat model
- **THEN** ForgeAgent rejects the request before transmitting application data

#### Scenario: Redirect reaches a blocked address
- **WHEN** an allowed public URL redirects to a forbidden destination
- **THEN** ForgeAgent rejects the redirect before connecting to the forbidden destination

#### Scenario: NAT64 representation maps to a blocked IPv4 address
- **WHEN** a target resolves to a NAT64 address whose embedded IPv4 address is forbidden
- **THEN** ForgeAgent applies the forbidden-address result and rejects the request

### Requirement: Redirect processing is bounded and scheme restricted
ForgeAgent MUST maintain its own maximum of 10 redirect hops and MUST reject any redirect whose resolved scheme is not HTTP or HTTPS.

#### Scenario: Redirect chain exceeds the hard limit
- **WHEN** a response chain attempts an eleventh redirect
- **THEN** ForgeAgent raises an explicit SSRF guard error identifying that the redirect limit was exceeded before opening the eleventh destination

#### Scenario: HTTP response redirects to a non-HTTP scheme
- **WHEN** an HTTP or HTTPS response redirects to FTP, file or another unsupported scheme
- **THEN** ForgeAgent rejects the redirect before any handler for that scheme can access the destination

### Requirement: Proxy support remains explicit and disabled
ForgeAgent SHALL document that future proxy routing requires a ForgeAgent-owned configuration contract and MUST NOT treat operating-system or environment proxy configuration as that contract.

#### Scenario: User needs proxy routing during this milestone
- **WHEN** a user configures only system or environment proxy settings
- **THEN** ForgeAgent continues to use direct guarded connections and documentation states that explicit proxy forwarding is not implemented

```

## openspec/changes/hardening-core-correctness/specs/tool-approval/spec.md

- Source: openspec/changes/hardening-core-correctness/specs/tool-approval/spec.md
- Lines: 1-57
- SHA256: b3ae815ca48cf8c57b9d7b70fc6bd4db7d57395424cf558128420f1d313ec349

```md
## ADDED Requirements

### Requirement: Restricted tools use one type-safe confirmation interface
ForgeAgent SHALL allow the CLI confirmer to describe and decide MCP, WebFetch and FileWrite requests without assuming that every request has MCP-specific fields.

#### Scenario: Confirming a WebFetch request
- **WHEN** the confirmer receives `WebFetchArgs`
- **THEN** it presents the request using WebFetch fields and does not raise an attribute or type error

#### Scenario: Confirming a FileWrite request
- **WHEN** the confirmer receives `FileWriteArgs`
- **THEN** it presents the target operation using FileWrite fields and does not raise an attribute or type error

#### Scenario: Confirming an MCP request
- **WHEN** the confirmer receives `MCPArgs`
- **THEN** it presents the server, tool and arguments using MCP fields

### Requirement: Terminal capability controls automatic confirmation
ForgeAgent SHALL attach the generic confirmer to restricted WebFetch, FileWrite and MCP operations independently of whether MCP servers are configured.

#### Scenario: Interactive terminal run
- **WHEN** a restricted tool is requested and the command has interactive TTY input and output
- **THEN** ForgeAgent asks the user to approve or reject the operation before execution

#### Scenario: REPL operation
- **WHEN** a restricted tool is requested from the REPL
- **THEN** ForgeAgent asks for confirmation before execution

#### Scenario: Non-interactive input
- **WHEN** WebFetch, FileWrite or an MCP call that still requires human confirmation is requested while stdin or stdout is not a TTY
- **THEN** ForgeAgent rejects the operation deterministically without waiting for input and identifies that no interactive confirmation channel is available

#### Scenario: Non-interactive auto-approved MCP call
- **WHEN** an MCP tool is listed in that server's `autoApprove` configuration and stdin or stdout is not a TTY
- **THEN** ForgeAgent treats the explicit configuration as pre-approval and executes without an interactive prompt

### Requirement: Confirmation prompts minimize sensitive exposure
ForgeAgent MUST redact structured secret-key values and known sensitive environment values from confirmation prompts, MUST NOT display FileWrite content, and MUST minimize disclosure of absolute file paths while retaining enough information for the user to identify the target.

#### Scenario: MCP arguments contain nested sensitive keys
- **WHEN** MCP arguments contain values under keys matching the existing secret-name policy at any nesting level
- **THEN** the confirmer replaces those values with a redaction marker and does not print the original values

#### Scenario: WebFetch URL contains credentials or sensitive query fields
- **WHEN** a WebFetch URL contains user information, known secret values or query keys matching the existing secret-name policy
- **THEN** the confirmer displays a sanitized URL without the sensitive values

#### Scenario: FileWrite uses an absolute path and sensitive content
- **WHEN** FileWrite requests an absolute path and arbitrary content
- **THEN** the confirmer displays a project-relative path when possible or a basename-only external path, displays only content length, and never displays the content

### Requirement: Survey interaction remains separately controlled
ForgeAgent MUST keep `--interactive` scoped to Survey behavior and SHALL NOT require that flag for automatic TTY confirmation of WebFetch, FileWrite or MCP.

#### Scenario: TTY run without interactive flag
- **WHEN** a terminal user runs a task without `--interactive` and the task requests a restricted non-Survey tool
- **THEN** ForgeAgent still asks for tool confirmation while Survey remains disabled

```
