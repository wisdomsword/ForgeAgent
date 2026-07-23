# Comet Design Handoff

- Change: skills-runtime
- Phase: design
- Mode: compact
- Context hash: 13d54510aa9a36709311fba38a625508b5d8ec1b778563cacfcdcd5077352043

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/skills-runtime/proposal.md

- Source: openspec/changes/skills-runtime/proposal.md
- Lines: 1-32
- SHA256: b01e0969689024f05b63ab0e918c942d9a4b17f07e809bdd63721b64df1e87f5

```md
## Why

M18 已明确拒收程序性记忆，但 ForgeAgent 还没有把经过验证的做事方法保存、发现并按需加载为 Skill 的运行时闭环。与此同时，现有 REPL 只能在提交裸 `/` 后打印静态菜单，缺少随输入过滤的指令选择和历史回放，降低了内嵌指令的可发现性与重复操作效率。

## What Changes

- 定义并校验 `SKILL.md` 的五段结构：`name`、`trigger`、`steps`、`failure_branches`、`completion_criteria`。
- 从用户级 `~/.forgeagent/skills/` 和项目级 `.forgeagent/skills/` 发现 Skill；可信项目 Skill 同名覆盖用户 Skill。
- 仅把有界的 Skill 名称和触发描述加入初始系统提示词，由模型自主选择后通过只读工具按需加载全文。
- 将 Skill 缺失、无效、不可读以及步骤失败后的停止/降级声明纳入现有反馈环，不新增独立工作流解释器。
- 对项目级 Skill 复用 M15 的首次摘要确认模式；headless 运行仅使用用户 Skill 或已预先批准且内容摘要未变化的项目 Skill。
- REPL 在交互式终端中输入 `/` 后立即显示可选指令，随每个字符动态过滤，并支持键盘选择。
- REPL 支持上下方向键回放当前会话历史；测试注入 reader 和非 TTY 输入保持兼容。
- 更新威胁模型、README、golden 候选和依赖锁定信息。

## Capabilities

### New Capabilities

- `skills-runtime`: 覆盖 Skill 结构校验、两级发现与覆盖、项目信任、渐进加载、模型自主匹配和失败反馈语义。
- `repl-interactive-input`: 覆盖交互式 REPL 的动态斜杠指令补全、选择和当前会话历史回放。

### Modified Capabilities

无。

## Impact

- 主要影响 `src/forgeagent/` 的提示词组装、工具注册、CLI/HTTP 装配和新增 Skills 模块。
- 新增 `prompt_toolkit` 运行时依赖以复用成熟的跨平台终端编辑、补全和历史能力。
- 新增项目 Skill 信任摘要持久化，但不改变 sandbox、工具确认门或 Task 完成语义。
- 增加单元测试、离线 golden 候选、威胁模型与用户文档；不引入额外 LLM 调用或网络服务。

```

## openspec/changes/skills-runtime/design.md

- Source: openspec/changes/skills-runtime/design.md
- Lines: 1-79
- SHA256: 88120a7171d00b747074d7f90c59e9026f4e7a0b5eed628ee08ec4682644968a

```md
## Context

M18 已把 `procedure` 记忆候选固定拒绝为 `procedure_requires_Skill`，但当前 Task 只组装身份、Memory 与 MCP 提示，没有可版本化的程序性知识来源。M17 同时要求系统提示词保持稳定前缀并限制动态上下文；因此 M19 不能把所有 Skill 全文直接注入。现有 REPL 的命令表已经统一驱动裸 `/` 菜单与 `/help`，但输入由可注入的普通 `read_line` 完成，不具备逐字符补全或方向键历史。

本变更跨提示词、工具、CLI/HTTP 装配、项目输入信任和终端依赖，必须保持 M15 项目信任、M16 headless、M17 有界上下文、M18 Memory 分流及既有 sandbox/确认门不变。

## Goals / Non-Goals

**Goals:**

- 以小而严格的 `SKILL.md` 格式建立用户级/项目级 Skill 发现、覆盖、信任与按需读取闭环。
- 只把有界目录注入初始提示词，由模型自主匹配并通过现有文本工具协议读取全文。
- 让无效 Skill、未知读取和步骤失败进入确定性诊断或现有反馈环。
- 用成熟终端库实现动态斜杠候选、键盘选择和当前会话历史，同时保留非 TTY/测试路径。

**Non-Goals:**

- 不自动从 Memory、历史或模型输出创建/修改 Skill。
- 不实现 Skill 市场、包管理、版本解析、独立意图模型或单独的工作流执行器。
- 不让 Skill 绕过 Task 完成语义、工具确认门、路径约束或 sandbox。
- 不持久化 REPL 输入历史，不新增 `/skills` 管理命令。

## Decisions

### 1. `SKILL.md` 使用 YAML front matter 加三个正文段

每个 Skill 位于 `<name>/SKILL.md`。front matter 只含 `name` 与单行 `trigger`；正文必须按顺序包含 `## Steps`、`## Failure branches`、`## Completion criteria` 且均非空。它在语义上正好形成规划要求的五段，同时保持普通 Markdown 可读、可评审。解析复用已安装的 PyYAML，拒绝未知 front matter 键、重复段、名称不一致、控制字符和固定大小上限。

备选一是五个纯标题，元数据读取更笨重；备选二是自由 Markdown 加启发式提取，无法可靠验证。严格结构最适合可执行协议边界。

### 2. 新增有界 `SkillRegistry`，不新增执行引擎

Registry 按名称排序扫描用户级后项目级目录，验证并在内存中保存经过 secret masking 的 `SkillDefinition`。固定上限控制单文件、Skill 数量、trigger 长度和目录总字节；越界条目稳定跳过并输出不含正文的诊断。可信项目定义在合并时覆盖同名用户定义。

Registry 提供两项能力：`catalog_prompt()` 只渲染 `name — trigger`；`read(name)` 返回完整五段文档。Skill 步骤仍由模型通过已有 ToolRegistry 执行，避免建设第二套状态机。

### 3. 项目 Skill 信任复用 M15 的摘要确认算法，但使用独立摘要记录

加载器分别计算原始内容摘要和掩码后有效摘要，以规范项目路径标识项目。CLI 首次或内容变化时展示有界名称/trigger 摘要；确认后原子记录到用户目录下独立的 Skill trust 文件。HTTP 没有确认通道，但可复用此前 CLI 对同一摘要的批准。未批准项目定义全部忽略，用户级定义不受影响。

为避免复制 M15 的路径、摘要匹配和原子持久化细节，identity 模块暴露一个小型通用内容信任 helper，既有 identity 流程经该 helper 保持原行为，Skills 使用独立记录路径。该抽象只有两个实际消费者且直接减少安全逻辑重复，符合 Ponytail 门禁。

### 4. `Skill` 只读工具是全文进入模型上下文的唯一入口

新增 `SkillArgs(name, section="full")` 和 `SkillTool(name="Skill")`。Task 在创建默认 ToolRegistry 时注入会话 SkillRegistry；初始系统提示词在身份/Memory 基础之后、MCP 动态说明之前追加稳定目录。模型根据 trigger 自主调用 `Skill`，完整文档作为普通工具反馈进入下一轮；若 M17 有界反馈截断整篇结果，continuation 明确提示按 `steps`、`failure_branches` 或 `completion_criteria` 单段重读。未知名称或段名返回确定性错误；工具本身无文件路径参数、无写操作也不需要确认。

失败分支不由宿主解释：现有工具失败内容与已加载文档都在会话中，模型按声明停止或降级；最终完成仍只由现有两阶段完成规则决定。这满足轻量目标并避免声明一种实际上不可验证的工作流 VM。

### 5. CLI/HTTP 都加载快照，`/reload` 原子替换

CLI 在身份/Memory 之后解析 Skills，复用同一确认请求形状、reader 和诊断输出，但使用明确指向项目 Skills 的独立确认文案；`/reload` 先构建候选 Registry，全部完成后再替换当前快照。HTTP 服务启动时构建一个不可变 Registry 并传给每个新 Task，不存储每请求的执行状态。`--no-identity` 同时禁用项目 Skill 信任输入，但不禁用用户级 Skill；这与“项目输入不可信、用户配置可信”的边界一致。

### 6. 交互输入使用 `prompt_toolkit`，保留原 reader 契约

当调用者没有显式传 `read_line` 且输入输出均为 TTY 时，REPL 创建一个 `PromptSession`，使用内存 History 和从 `_SLASH_COMMAND_USAGE` 动态生成的前缀 Completer；`complete_while_typing=True` 使 `/` 及后续每个字符实时刷新候选，默认键绑定负责候选选择和无候选时的上下历史。候选说明与 `/help` 共用原命令表。

非 TTY 使用内置 `input`；显式 reader 始终原样使用。没有历史文件，避免新增敏感任务文本持久化面。备选的 stdlib `readline` 不能持续显示候选，自研 raw-mode 编辑器则增加跨平台与信号处理风险，因此均不采用。

## Risks / Trade-offs

- [模型可能误匹配或不加载适用 Skill] → trigger 保持单行具体描述，golden 覆盖有/无目录差异；不为此增加第二次 LLM 判定。
- [项目 Skill 通过提示词诱导危险动作] → 摘要确认、内容变化重确认、secret masking，加上现有确认门与 sandbox 最终兜底；威胁模型明确确认不是权限提升。
- [目录过大挤占上下文] → 固定文件/条目/目录上限，初始提示只含元数据，并以字节断言验证全文不在初始消息。
- [严格格式拒绝部分手写 Markdown] → 诊断指出固定原因，规范提供最小模板；不引入宽松启发式兼容层。
- [`prompt_toolkit` 增加依赖] → 它直接覆盖动态菜单、跨平台编辑和历史，总代码与维护风险低于自研终端层；非交互路径仍不依赖终端状态。
- [Skill trust helper 触及既有 identity] → 先用现有 identity 测试锁住 schema、摘要变化与原子写入，再做最小提取，完整回归验证。

## Migration Plan

1. 增加依赖、Skill schema/registry/trust 与单元测试；没有 Skill 目录时行为与当前版本等价。
2. 接入提示词、只读工具、Task、CLI 与 HTTP，并补 mock replay/golden 候选。
3. 接入交互 reader，保留注入 reader 测试路径。
4. 更新 README、威胁模型、ACTION_PLAN 与里程碑记录；运行完整离线验证。

回滚可删除 Skills 装配和 `prompt_toolkit` 依赖；用户 Skill 文件及独立 trust 记录是惰性数据，不影响旧版本运行。

## Open Questions

无。当前范围和默认值已由两轮需求、安全与一致性自审收敛；新增配置、持久历史或 Skill 管理命令均延后到有实证需求时再设计。

```

## openspec/changes/skills-runtime/tasks.md

- Source: openspec/changes/skills-runtime/tasks.md
- Lines: 1-26
- SHA256: 43fa9b4a76327a17eb47d0873903e17ab3b788adc63b452cc3661674f39bf7ee

```md
## 1. Skill 核心与信任边界

- [ ] 1.1 先写失败测试覆盖 SKILL.md 五段校验、大小/数量上限、确定性诊断和用户/项目覆盖，再实现 `SkillDefinition` 与 `SkillRegistry`
- [ ] 1.2 先锁住既有 identity trust 行为，再提取通用内容摘要信任 helper，并覆盖项目 Skill 首次确认、摘要变化、headless 预批准和原子记录

## 2. 渐进加载与执行反馈

- [ ] 2.1 先写协议与工具测试，再实现 `SkillArgs`、只读 `Skill` 工具和 ToolRegistry 装配
- [ ] 2.2 将有界 Skill 目录接入 Task 系统提示词，验证全文不在初始上下文、按需读取后进入下一轮且不改变完成/确认/sandbox 语义
- [ ] 2.3 将 Skills 快照接入 CLI、`/reload` 和 HTTP Task 创建路径，覆盖会话替换、请求隔离与无确认降级

## 3. REPL 交互输入

- [ ] 3.1 添加并锁定 `prompt_toolkit` 依赖，实现由 `_SLASH_COMMAND_USAGE` 驱动的逐字符前缀候选和键盘选择
- [ ] 3.2 实现当前会话上下键历史，覆盖 TTY 增强路径、非 TTY fallback 及显式 `read_line` 兼容

## 4. Golden 与文档

- [ ] 4.1 增加离线 golden Skill 注入候选和渐进加载上下文体积断言，保持既有 20 项 verified core 不变
- [ ] 4.2 更新 README、SKILL.md 示例、文本协议、威胁模型与 ACTION_PLAN M19 状态

## 5. 评审与验证

- [ ] 5.1 运行受影响测试、完整 pytest、ruff、golden 20/20、OpenSpec strict、package build 与 diff check
- [ ] 5.2 完成两轮 whole-change 自审，立即修复发现的问题并重跑相关与完整验证
- [ ] 5.3 产出 M19 验证报告和里程碑文件，执行 Comet verify/archive 并提交主线可合并历史

```

## openspec/changes/skills-runtime/specs/repl-interactive-input/spec.md

- Source: openspec/changes/skills-runtime/specs/repl-interactive-input/spec.md
- Lines: 1-42
- SHA256: e7f44ecbfdd57c74ec390a592a856b90162d700b8dbc1b6e4b847aadbc454dd6

```md
## ADDED Requirements

### Requirement: 交互式 REPL 动态展示斜杠指令
系统必须（SHALL）在真实交互式终端的 REPL 中，于用户输入 `/` 后立即展示可用斜杠指令，并在每输入或删除一个字符后按当前命令前缀更新候选。候选名称和说明必须（MUST）来自与 `/help` 相同的命令表。

#### Scenario: 裸斜杠显示全部指令
- **WHEN** 用户在空提示符输入 `/` 且尚未提交
- **THEN** 输入界面显示全部可用斜杠指令候选及其简要用途

#### Scenario: 前缀逐字符过滤
- **WHEN** 用户依次输入 `/m`、`/mo`、`/mod`
- **THEN** 候选集合在每次编辑后立即缩小为匹配当前前缀的指令

### Requirement: 用户可从候选中选择指令
系统必须（SHALL）允许用户用终端键盘在当前候选中移动并接受一个指令，接受后命令文本进入同一输入行，用户可继续补充参数或提交。

#### Scenario: 选择命令后继续输入参数
- **WHEN** 用户从 `/model` 候选中选择该命令
- **THEN** 输入行包含 `/model`，且用户仍可输入模型参数后提交

### Requirement: 上下方向键回放当前会话历史
系统必须（SHALL）记录当前 REPL 会话已提交的输入，并在没有活动候选选择时用上、下方向键向后或向前回放。历史默认不得（MUST NOT）跨进程持久化，以避免把任务文本或敏感参数写入额外文件。

#### Scenario: 回放上一条输入
- **WHEN** 用户已提交至少一条输入并在新提示符按上方向键
- **THEN** 输入行恢复上一条已提交文本供编辑或再次提交

#### Scenario: 下方向键返回较新输入
- **WHEN** 用户已向上回放历史后按下方向键
- **THEN** 输入行移动到较新的历史项或回到空输入

### Requirement: 非交互与测试输入保持兼容
系统必须（SHALL）只在默认 reader 且 stdin/stdout 均为交互式终端时启用增强输入。显式注入的 `read_line` 和非 TTY 输入必须（MUST）保持原有 EOF、KeyboardInterrupt、空行、确认与 Survey 行为。

#### Scenario: 注入 reader 不创建终端会话
- **WHEN** 测试或嵌入方显式传入 `read_line`
- **THEN** REPL 只调用该 reader，且不访问增强终端输入对象

#### Scenario: 非 TTY 使用普通输入
- **WHEN** REPL 默认启动但 stdin 或输出不是 TTY
- **THEN** 系统使用普通输入路径并保持现有退出语义


```

## openspec/changes/skills-runtime/specs/skills-runtime/spec.md

- Source: openspec/changes/skills-runtime/specs/skills-runtime/spec.md
- Lines: 1-71
- SHA256: 1e2f78c0d8e5cfe65d853ed5564b3dcb4ea548c7b00b0974144adbbfee3e1cb8

```md
## ADDED Requirements

### Requirement: Skill 文档具有可验证的固定结构
系统必须（SHALL）只接受位于独立目录 `SKILL.md` 中、包含非空 `name`、`trigger`、`steps`、`failure_branches` 与 `completion_criteria` 五段内容的 Skill。`name` 必须（MUST）是与目录名一致的 kebab-case 标识符；无效、超限或不可读文档不得进入模型可见目录。

#### Scenario: 有效 Skill 被发现
- **WHEN** 用户级目录包含结构完整且名称匹配的 `review-code/SKILL.md`
- **THEN** 系统将 `review-code` 加入可用 Skill 目录

#### Scenario: 无效 Skill 被隔离
- **WHEN** `SKILL.md` 缺少失败分支或名称与目录不一致
- **THEN** 系统跳过该 Skill、输出有界诊断且继续加载其他有效 Skill

### Requirement: 两级发现遵循可信项目覆盖语义
系统必须（SHALL）从 `~/.forgeagent/skills/` 与项目 `.forgeagent/skills/` 发现 Skill。用户级 Skill 默认可信；项目级 Skill 必须（MUST）通过基于规范项目路径和有效内容摘要的首次确认，且只有摘要未变化时批准才可复用。可信项目 Skill 必须（SHALL）覆盖同名用户 Skill，未获信任的项目 Skill 不得隐藏同名用户 Skill。

#### Scenario: 可信项目 Skill 覆盖用户 Skill
- **WHEN** 两级目录存在同名 Skill 且项目内容摘要已获批准
- **THEN** 模型目录和按需读取均使用项目版本

#### Scenario: 未批准项目 Skill 不生效
- **WHEN** 项目包含新建或已变化的 Skill 且没有可用确认通道
- **THEN** 项目版本不进入模型上下文，同名用户版本仍可用

### Requirement: 初始上下文只包含有界 Skill 目录
系统必须（SHALL）在初始系统提示词中仅注入每个有效 Skill 的名称和单行触发描述，不得（MUST NOT）注入 `steps`、`failure_branches` 或 `completion_criteria` 全文。目录必须（MUST）具有确定性顺序、条目数和字节上限，且敏感值在进入提示词或确认摘要前被掩码。

#### Scenario: 渐进加载不泄漏全文
- **WHEN** 一个 Skill 的步骤包含唯一标记文本
- **THEN** 任务初始系统提示词不含该标记，只含 Skill 名称和触发描述

#### Scenario: 目录超限时确定性收敛
- **WHEN** 已发现 Skill 数量或目录文本超过固定上限
- **THEN** 系统按名称稳定截断、发出有界诊断且初始提示词仍在上限内

### Requirement: 模型通过只读工具按需加载 Skill
系统必须（SHALL）提供只读 `Skill` 工具，接收一个目录中存在的 Skill 名称并把经过掩码的完整五段文档作为工具反馈返回；工具还必须（MUST）允许按 `steps`、`failure_branches` 或 `completion_criteria` 单段重读，以便在 M17 有界反馈截断整篇内容后继续。模型自主依据触发描述决定是否调用，不得（MUST NOT）增加独立意图识别器或额外 LLM 请求。

#### Scenario: 适用 Skill 被按需读取
- **WHEN** 模型针对当前任务调用 `Skill` 并提供有效名称
- **THEN** 下一轮反馈包含该 Skill 的完整步骤、失败分支和完成标准

#### Scenario: 未知 Skill 进入可恢复反馈
- **WHEN** 模型请求不存在或当前不可用的 Skill 名称
- **THEN** 工具返回确定性失败反馈且 Step 可在剩余轮次内修正，不产生宿主异常

#### Scenario: 截断后可按段继续读取
- **WHEN** 完整 Skill 工具结果超过当前单结果反馈上限
- **THEN** 截断标记明确提示模型使用同一 Skill 名称按段重读，且每个声明段都可独立请求

### Requirement: Skill 声明复用现有反馈与完成边界
系统必须（SHALL）把 Skill 的步骤、失败分支和完成标准作为模型执行指令；步骤中的工具失败仍由现有工具结果反馈环报告，模型必须（MUST）按已加载 Skill 声明停止或降级。Skill 完成标准不得（MUST NOT）绕过现有 Task 完成判定、工具确认门或 sandbox 限制。

#### Scenario: 失败分支可供模型修正
- **WHEN** 已加载 Skill 的某一步返回失败工具结果
- **THEN** 后续模型轮次仍能看到该失败结果和 Skill 声明的失败分支

#### Scenario: Skill 不能提升权限
- **WHEN** Skill 指示执行需要确认或被 sandbox 禁止的动作
- **THEN** 现有确认门和 sandbox 策略照常拒绝或请求确认

### Requirement: CLI 与 HTTP 使用隔离的 Skill 快照
系统必须（SHALL）在 CLI 会话和 HTTP 服务装配时创建有界 Skill 快照并传给每个 Task。交互式 CLI 可确认项目 Skill；headless HTTP 只能使用用户 Skill或内容摘要已预先批准的项目 Skill。HTTP 请求之间不得（MUST NOT）共享可变的 Skill 执行状态。

#### Scenario: CLI reload 更新 Skill 快照
- **WHEN** 用户执行 `/reload` 且 Skill 文件发生变化
- **THEN** 系统重新发现、校验并按当前信任状态原子替换会话 Skill 快照

#### Scenario: HTTP 无确认时降级
- **WHEN** HTTP 服务启动于含未批准项目 Skill 的目录
- **THEN** 服务继续启动但不暴露该项目 Skill

```
