# Comet Design Handoff

- Change: compose-runtime-identity
- Phase: design
- Mode: compact
- Context hash: a5ee1f31de1626234f35ad8e186a9e47d899b476be6a902663deb5263a138067

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/compose-runtime-identity/proposal.md

- Source: openspec/changes/compose-runtime-identity/proposal.md
- Lines: 1-33
- SHA256: 95eeecbe926ce7f31fbf3cd84df8ae5b4d774157597014f38f24714cbcc03a40

```md
## Why

ForgeAgent 当前把完整系统提示词硬编码在 `task.py`，无法表达用户、项目和运行时身份，也无法在不修改源码的情况下调整低频身份信息。M15 需要建立可配置但不削弱协议约束的运行时身份层，并缓解真实冒烟中模型受训练人设污染、错误自称为 "Kiro" 的已知问题。

## What Changes

- 将硬编码系统提示词拆为稳定的身份、不可覆盖协议、用户、项目和记忆段，并通过模板组合器生成最终提示词。
- 从用户级 `~/.forgeagent/{SOUL,USER}.md` 与项目级 `.forgeagent/{AGENTS,MEMORY}.md` 加载身份内容；缺失文件按各层契约跳过或回落。
- 提供 `--no-identity` 诊断开关，并让现有 `/reload` 重新读取身份文件。
- 对项目级身份文件建立首次加载摘要确认；确认记录持久化绑定规范项目标识、原始内容摘要与有效模型输入摘要，两个摘要均不变时不重复确认；未经确认、无交互确认通道或用户拒绝时不得注入。
- 固定“运行于 ForgeAgent harness”的披露和防人设污染约束；实际 Agent 身份由已批准 SOUL（或中性默认 SOUL）定义，协议段始终由程序控制且不可被身份文件覆盖。
- 更新威胁模型；将候选 golden 目录扩展为 G01-G400 并精确维持既有类别配比，同时保持 20 项可信核心不变；以专项可执行测试覆盖组合矩阵、全缺失等价性、SOUL/AGENTS 生效、Kiro 回归和可信核心 20/20 无回归。

本 change 不包含 `forgeagent init`、BOOTSTRAP 引导、AGENTS 归档、记忆自动提取/准入、多 profile 或人格模板库；这些分别属于后续 `bootstrap-runtime-identity` change 或 M18。

## Capabilities

### New Capabilities

- `runtime-identity`: 定义运行时身份文件来源、提示词组合顺序、协议不可覆盖、项目文件信任确认、禁用与重载行为。

### Modified Capabilities

- `golden-validation-core`: 将候选目录从 G01-G380 扩展到 G01-G400，保持既有 20 项可执行可信核心不变，并继续区分候选定义与已验证证据。

## Impact

- 生产代码：`src/forgeagent/task.py`、`src/forgeagent/cli.py`，以及新增的身份加载/提示词组合模块和 `src/forgeagent/res/prompts/*.j2` 资源；构建配置需确保模板进入 wheel/sdist。
- 用户接口：新增全局 `--no-identity`；现有 `/reload` 扩展为同时重载身份文件。
- 用户状态：新增版本化的用户级身份信任记录，只保存规范项目标识、原始内容摘要与有效输入摘要，不保存身份正文。
- 安全边界：项目级 `.forgeagent/AGENTS.md` 与 `.forgeagent/MEMORY.md` 被视为不可信仓库输入，需要通过路径边界检查并确认后才可注入。
- 验证与文档：任务、CLI、身份组合器、golden runner 相关测试，以及 `docs/threat-model.md` 和 M15 设计/里程碑文档。
- 依赖：复用项目已存在的 Jinja2，不新增第三方依赖。

```

## openspec/changes/compose-runtime-identity/design.md

- Source: openspec/changes/compose-runtime-identity/design.md
- Lines: 1-92
- SHA256: 8ae206a2e74ba920eb177e3a4cd3854ba2bea7eac8ff0c178329f24af60f925b

[TRUNCATED]

```md
## Context

ForgeAgent 目前在 `task.py` 中以 `DEFAULT_SYSTEM_PROMPT` 常量保存身份、文本协议、工具用法和完成声明，`Task._build_system_prompt()` 只在其末尾追加 MCP 工具描述。用户和项目无法通过受控文件提供身份上下文，协议与可变身份内容也没有结构边界。

本 change 是 M15 的第一个拆分项，负责运行时组合与加载；`forgeagent init`、BOOTSTRAP 引导和 AGENTS 归档由后续 `bootstrap-runtime-identity` change 提供。现有 Jinja2 依赖、CLI confirmer、两级配置路径和 `/reload` 行为可复用，不引入新依赖或第二套配置框架。

## Goals / Non-Goals

**Goals:**

- 将稳定的 ForgeAgent harness 披露、中性默认或用户 SOUL、协议、用户偏好、项目约束和手工记忆分层组合。
- 保持协议段由程序控制，身份文件不能删除、替换或重排协议约束。
- 复用用户级 `~/.forgeagent` 和项目级 `.forgeagent` 路径惯例，并提供明确的禁用与重载语义。
- 在注入项目级不可信内容前取得用户确认，无确认通道时默认不注入。
- 保持没有自定义身份文件时的既有行为与 golden 结果不回归。

**Non-Goals:**

- 不生成、归档或自动编辑身份文件。
- 不实现记忆提取、准入、冲突替换或跨任务自动写入。
- 不实现多身份 profile、人格模板市场或项目级 Skill 加载。
- 不改变文本协议、工具协议、sandbox 或模型客户端契约。

## Decisions

### 1. 分离加载、组合与任务执行

新增小型身份加载组件负责读取并返回有来源标记的 SOUL、USER、AGENTS、MEMORY 内容；提示词组合器负责把已批准的内容渲染为模型上下文；`Task` 仍只负责创建消息和执行 Step。这样可以用纯函数覆盖组合矩阵，也避免让文件系统和确认逻辑渗入执行环路。

替代方案是继续由 `Task._build_system_prompt()` 直接读文件并拼字符串。该方案改动少，但会把路径解析、信任确认、模板渲染和 MCP 追加混在一个方法中，难以独立测试和热重载，因此不采用。

### 2. 使用包内模板承载固定段，身份文件只提供数据

固定“运行于 ForgeAgent harness”的披露、SOUL 优先级规则、不可覆盖协议和段落边界放在 `src/forgeagent/res/prompts/*.j2`，通过包资源加载。实际 Agent 身份由已批准的用户 SOUL 定义，缺失时使用中性默认 SOUL；任务文本或训练先验中的无关人设不能替代它。用户文件内容先应用既有敏感环境值掩码，再只作为模板数据插入，不作为模板源码执行；组合器使用严格、显式的上下文字段，禁止身份文件选择模板或覆盖协议段。摘要确认和最终模型输入必须使用同一份掩码后内容，自动加载身份不能成为绕过现有 prompt secret 边界的新通道。

Jinja2 已是项目依赖，复用它比新增自定义模板语言或继续手工字符串拼接更小。模板应保持简单，不增加宏框架、插件接口或多主题抽象。

### 3. 用户级与项目级来源采用固定语义

- SOUL：读取 `~/.forgeagent/SOUL.md`；缺失时使用包内中性默认身份。
- USER：读取 `~/.forgeagent/USER.md`；缺失时省略。
- AGENTS：读取 `<allowed_root>/.forgeagent/AGENTS.md`；缺失或未确认时省略。
- MEMORY：读取 `<allowed_root>/.forgeagent/MEMORY.md`；缺失或未确认时省略，M15 只读不写。

`allowed_root` 而非进程启动目录是项目身份根，确保身份、File 工具和 executor 对“当前项目”的理解一致。缺失文件是正常状态；其他读取失败应作为可诊断配置错误呈现，不能静默使用部分内容。

加载器构造参数中的用户目录、项目根和信任记录路径可显式注入（对齐 `model_registry.load_registry` 的路径注入先例），默认值才指向 `~/.forgeagent`、`allowed_root/.forgeagent` 和用户级信任记录。所有 home 派生默认值必须在函数调用时解析，不能作为 import 时绑定的默认参数；这样 golden/测试先切换 HOME 再调用时不会读取开发机配置。这是库内依赖注入与测试隔离面，不新增 CLI 路径参数。直接构造 `Task` 不触发 home/project 文件 I/O；CLI 等产品入口负责加载并把已解析快照显式传入，`run_smoke` 保持只使用包内默认身份。现有可信库调用方显式传入 `system_prompt` 的能力继续作为完整覆盖路径保留，不与自动身份文件混合。

### 4. 项目内容通过现有确认通道进入信任边界

AGENTS/MEMORY 随仓库分发，必须在首次注入某个项目内容快照前展示有界、转义且经过既有 secret 掩码的摘要并取得明确确认。项目标识使用 canonical `allowed_root` 的摘要；快照同时包含两类结构化 SHA-256：对 AGENTS/MEMORY 文件名、存在性和原始字节计算的原始内容摘要，以及对应用当前 secret 掩码后实际将注入模型的 UTF-8 内容计算的有效输入摘要。前者保证任何磁盘字节变化都触发重确认，后者保证环境敏感值集合改变模型输入时也触发重确认；结构化编码避免拼接歧义。加载器只接受解析后仍位于 canonical `<allowed_root>/.forgeagent` 内的普通文件，拒绝目录、特殊文件和 symlink 逃逸。

确认机制复用现有 CLI confirmer 的“无通道即拒绝”原则，但使用独立的身份确认请求类型，避免伪装成工具调用。版本化信任记录默认写入用户级 `.forgeagent/identity-trust.json`，以 canonical 项目标识摘要映射到原始内容摘要和有效输入摘要，不保存身份正文；写入使用同目录临时文件加 `os.replace()`。记录缺失、畸形或不可读时按“未确认”处理；当前交互批准后若持久化失败，本次任务可使用已批准的内存快照，但后续进程必须重新确认。

同一项目的原始内容摘要与有效输入摘要均未变化时，后续 REPL 会话、headless 调用和单次 `run` 可复用确认并静默注入；只有“尚无匹配确认且无交互通道”时才默认不注入。任何文件存在性、字节或有效输入变化都形成新快照并触发重确认。确认与注入使用同一份已读取快照，确认后不得重新读取文件，从而关闭确认后换内容的 TOCTOU 窗口。

### 5. 禁用和重载不引入新的全局状态

`--no-identity` 禁止读取全部自定义身份文件，并回落到包内默认身份加固定协议；它不禁用 MCP 工具描述或其他系统契约。REPL 的 `/reload` 使后续任务重新读取身份快照；单次 `run` 每次进程调用自然读取一次。组合结果通过显式依赖传入 Task，不使用模块级可变单例。

### 6. 兼容性以语义和可执行回放为门禁

没有自定义身份文件时，协议能力（文本协议、工具用法、状态机制）与完成声明语义必须不丢失，MCP 工具段仍位于固定契约之后。身份段立场是刻意变更：现有提示词的 “ForgeAgent is just the name of this response format, not a persona to adopt” 替换为“当前运行于 ForgeAgent harness；身份以已批准 SOUL 或中性默认 SOUL 为准”的披露与优先级约束（针对 M5 在案的 Kiro 自称失败），不属于兼容性回归。验证同时使用模板快照/协议断言与现有离线 golden 全量回放，不要求内部字符串逐字节相同，但不允许协议能力或完成语义丢失。

### 7. Golden 目录扩展与可执行证据保持分层

候选目录从 G01-G380 扩展到 G01-G400，新增 20 项按 8/5/4/2/1 分布，继续精确满足 40/25/20/10/5。既有 20 项可信核心及 5 项 real opt-in 集合保持不变，默认 runner 仍报告 20 项；身份组合、SOUL/AGENTS 输入生效和 Kiro 防污染由 M15 专项 pytest/mock replay 提供可执行证据。候选条目不得被描述为已经通过，除非后续明确工程化进入可信核心。

这同时修改现有 `golden-validation-core` 的 catalog universe 契约，避免文档写入 G381-G400 后与当前“精确 G01-G380”主 spec 和一致性测试冲突。

## Risks / Trade-offs

- [项目身份文件可注入恶意指令] → 首次内容确认、内容变化重确认、协议不可覆盖，并继续依赖现有 sandbox/工具确认门限制真实动作。
- [可变 MEMORY 破坏 prompt-cache 稳定前缀] → 在深度设计中裁决其消息位置，并把该选择记录为 M17 缓存排序审计的基线。
- [身份段增加 token 开销] → 缺失段不渲染，不增加检索、元数据包装或冗余重复；测试约束空段不产生无意义内容。
- [模板化导致隐性协议回归] → 对协议关键句、所有身份组合和完整 golden 回放设置门禁。
- [确认状态过宽导致修改后免确认] → 确认身份必须绑定项目、原始内容摘要与有效输入摘要，任一摘要变化都视为新快照。
- [项目身份文件过大造成上下文或内存拒绝服务] → 深度设计裁决每文件/总量上限和“拒绝而非静默截断”语义，并加入边界测试。
- [模板只在源码树可用、构建包缺失] → 构建 wheel/sdist 并从安装产物加载模板，显式验证 `.j2` 被打包。


```

Full source: openspec/changes/compose-runtime-identity/design.md

## openspec/changes/compose-runtime-identity/tasks.md

- Source: openspec/changes/compose-runtime-identity/tasks.md
- Lines: 1-24
- SHA256: 71b5990f1278ae8cfc5287aa0b6a18b39a7160afee056684659bdc1f688877b9

```md
## 1. 身份加载与提示词组合

- [ ] 1.1 建立包内 Jinja2 提示词资源和纯组合器，保留固定 harness 披露、SOUL 优先级、不可覆盖协议、完成声明与 MCP 工具段语义
- [ ] 1.2 实现用户级 SOUL/USER 与 `allowed_root` 项目级 AGENTS/MEMORY 加载，库内路径可注入且 home 默认值在调用时解析，覆盖 canonical 边界、symlink 逃逸、secret 掩码、缺失回落、来源标记、大小上限和读取错误
- [ ] 1.3 将 Task 的系统上下文构建改为显式使用身份快照和组合器，避免模块级可变状态及直接 Task 构造时的隐式文件 I/O，并保留显式 `system_prompt` 可信覆盖契约
- [ ] 1.4 更新构建资源配置并验证从 wheel/sdist 安装后仍能加载全部 `.j2` 模板

## 2. 信任边界与 CLI 接线

- [ ] 2.1 实现版本化、原子写入的项目身份信任记录和确认门，绑定 canonical 项目标识摘要、原始内容摘要与掩码后有效输入摘要，覆盖拒绝、headless、跨进程复用、畸形记录、写入失败、文件/secret 掩码变化及确认后磁盘替换
- [ ] 2.2 为 REPL 和单次运行接入全局 `--no-identity`，验证它只禁用自定义身份而保留固定协议与 MCP 描述
- [ ] 2.3 扩展 `/reload`，使后续任务重新读取身份文件并让变化的项目内容重新进入确认流程

## 3. 回归与验收

- [ ] 3.1 添加 SOUL/USER/AGENTS/MEMORY 存在与缺失、确认结果和禁用模式的表驱动组合矩阵测试
- [ ] 3.2 添加项目根解析、读取失败、headless 默认拒绝、内容变化重确认、确认记录跨进程复用及 CLI/reload 行为测试
- [ ] 3.3 添加固定协议完整性、SOUL 优先级、Kiro 身份污染回归和无自定义身份文件的 20 项离线可信核心回放门禁
- [ ] 3.4 在候选目录新增 G381-G400（8/5/4/2/1），将一致性门更新为 G01-G400 与 20/380 分层；用独立专项 mock replay 机器验证 SOUL/AGENTS 输入可见性，不把候选定义或脚本化响应宣称为真实模型遵循证据

## 4. 文档与里程碑证据

- [ ] 4.1 更新威胁模型和用户文档，明确项目身份文件的路径/大小/TOCTOU 风险、持久化确认边界、golden 候选/可信核心分层及 M15/M18 职责划分
- [ ] 4.2 运行 Ruff、专项与全量 pytest、离线 golden 和三轮评审，记录原始验证证据但不提前宣告整个 M15 完成

```

## openspec/changes/compose-runtime-identity/specs/golden-validation-core/spec.md

- Source: openspec/changes/compose-runtime-identity/specs/golden-validation-core/spec.md
- Lines: 1-17
- SHA256: 6f1d0a9bf7655ea835aabed73978978d77856a6b5b1645a804a8f1243cacdfde

```md
## MODIFIED Requirements

### Requirement: Golden catalog has one exact ID universe
The candidate catalog SHALL contain each and only each ID from `G01` through `G400`, inclusive. The trusted core SHALL remain the exact existing 20-ID set; its complement SHALL contain exactly 380 non-core candidates. Validation MUST reject duplicate, missing, additional or substituted catalog IDs before any claim about core or candidate counts.

The complete `G01` through `G400` unique, continuous and 380-item non-core check SHALL be owned by the documentation-consistency pytest gate, not by the production golden runner preflight. The twenty M15 additions SHALL use IDs G381-G400 and SHALL preserve the catalog-wide 40/25/20/10/5 category distribution by adding exactly 8 file/data, 5 Python execution/sandbox, 4 code modification, 2 network/API and 1 system-query scenario.

#### Scenario: Candidate ID universe is exact
- **WHEN** catalog consistency validation reads the candidate documentation and trusted-core manifest
- **THEN** it accepts only the unique inclusive `G01` through `G400` universe, exactly 20 core IDs and exactly 380 non-core IDs, with the complete catalog retaining the exact approved category distribution

### Requirement: Candidate catalog is not presented as validated
ForgeAgent documentation SHALL distinguish the 20 executable trusted-core scenarios from the remaining candidate task catalog and MUST NOT describe candidates as validated without executable evidence. M15 identity behavior SHALL use dedicated deterministic pytest/mock-replay evidence; merely adding G381-G400 definitions to the candidate catalog SHALL NOT count as execution evidence.

#### Scenario: User reads golden task documentation
- **WHEN** documentation lists the wider task catalog after the M15 extension
- **THEN** it labels exactly 20 scenarios as executable trusted core and exactly 380 other IDs in the `G01` through `G400` universe as non-core candidates

```

## openspec/changes/compose-runtime-identity/specs/runtime-identity/spec.md

- Source: openspec/changes/compose-runtime-identity/specs/runtime-identity/spec.md
- Lines: 1-119
- SHA256: 59280ead999048c4cf6245d33b6711f7de5be4bd766f8c8eeca23f8f681b3164

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: 分层运行时身份组合
系统 SHALL 按稳定的语义顺序组合固定 ForgeAgent harness 披露、中性默认或已批准 SOUL、不可覆盖协议、用户偏好、项目约束和手工记忆，并 SHALL 在组合完成后保留现有 MCP 工具描述。身份文件内容 MUST 仅作为数据插入，不能选择模板、删除协议或改变协议顺序。协议不可覆盖保证仅限结构层面：系统保证身份文件内容不能修改、删除或移动固定协议字节的位置（Patch 6）；此保证不等于模型语义层的完整 prompt-injection 防护，模型仍可能响应身份文件中的指令性语义。组合所需包资源（system.j2、default_soul.md、protocol.md）缺失时，系统 MUST 报安装损坏，MUST NOT 静默回落为不含协议说明的提示词（Patch 5）。

#### Scenario: 全部可选身份层可用
- **WHEN** 用户 SOUL、USER 与已确认的项目 AGENTS、MEMORY 均存在
- **THEN** 系统按 harness 披露与 SOUL、固定协议、用户、项目、记忆的顺序向模型提供全部内容，并保留 MCP 工具描述

#### Scenario: 身份文件试图覆盖协议
- **WHEN** 任一身份文件包含要求忽略、替换或删除 ForgeAgent 协议的文本
- **THEN** 系统仍提供完整的程序控制协议段，且身份文件不能修改其内容或位置

### Requirement: 身份文件来源与缺失行为
系统 SHALL 从调用时解析的 `~/.forgeagent/SOUL.md` 和 `~/.forgeagent/USER.md` 读取用户级身份，从当前 `allowed_root` 下 `.forgeagent/AGENTS.md` 和 `.forgeagent/MEMORY.md` 读取项目级身份。home 派生路径 MUST NOT 在模块 import 时绑定。SOUL 缺失时 SHALL 使用包内中性默认身份，其他文件缺失时 SHALL 省略对应段；M15 期间系统 MUST NOT 自动写入 MEMORY。所有自动加载身份正文 MUST 在进入确认摘要或模型上下文前应用既有敏感环境值掩码。每个自定义身份文件原始字节 MUST NOT 超过 32 KiB（Patch 1）；四个身份段掩码后有效内容合计 MUST NOT 超过 96 KiB。SOUL 或 USER 单文件超限，或其组合使有效合计超限时，系统 MUST 报配置错误并拒绝继续组合；AGENTS 或 MEMORY 超限或使合计超限时，系统 SHALL 剥离相应项目段并输出脱敏诊断后继续任务。系统 MUST NOT 截断任何身份文件（截断身份或约束内容会产生不可预测语义）。

#### Scenario: 所有自定义身份文件缺失
- **WHEN** 四个可加载身份文件均不存在
- **THEN** 系统使用包内默认身份和固定协议运行，既有任务与完成语义保持兼容

#### Scenario: 只有部分身份文件存在
- **WHEN** 任意一组可选身份文件存在且其余文件缺失
- **THEN** 系统只加载存在且获准的内容，缺失段不产生错误或占位文本

#### Scenario: 项目根与进程目录不同
- **WHEN** Task 的 `allowed_root` 与进程当前目录不同
- **THEN** 系统只从 `allowed_root/.forgeagent` 解析项目级 AGENTS 和 MEMORY

#### Scenario: 项目身份路径通过 symlink 逃逸
- **WHEN** 项目 `.forgeagent` 目录或其中的 AGENTS/MEMORY 解析到 canonical 项目身份目录之外，或目标不是普通文件
- **THEN** 系统拒绝该项目身份快照且不读取或注入逃逸目标

#### Scenario: 直接构造 Task
- **WHEN** 库调用方直接构造 Task 且未显式传入身份快照
- **THEN** Task 使用包内默认身份与固定协议，并且不读取用户 home 或项目身份文件

#### Scenario: 可信库调用方显式覆盖系统提示词
- **WHEN** 库调用方直接构造 Task 并显式传入 `system_prompt`
- **THEN** Task 继续使用该显式提示词且不自动混入身份文件，保持现有可信调用契约

#### Scenario: import 后切换 HOME
- **WHEN** 身份模块已导入，调用方随后切换 HOME 并在未传显式用户目录的情况下加载身份
- **THEN** 系统从调用时 HOME 派生路径，不读取 import 时 HOME 下的身份或信任记录

#### Scenario: 身份正文包含已知敏感环境值
- **WHEN** SOUL、USER、AGENTS 或 MEMORY 包含会被既有 secret policy 识别的环境值
- **THEN** 确认摘要、最终模型上下文和诊断均只包含掩码标记而不包含原始敏感值

### Requirement: 项目身份信任确认
系统 MUST 将项目级 AGENTS 和 MEMORY 视为不可信仓库输入，并 MUST 在首次注入某个内容快照前展示有界、控制字符转义且经过既有 secret 掩码的摘要并取得明确用户确认。确认记录 SHALL 以版本化、原子替换的用户级文件持久化，并绑定 canonical 项目标识摘要、对文件名/存在性/原始字节做无歧义编码的原始内容摘要，以及对掩码后实际模型输入计算的有效输入摘要；记录 MUST NOT 保存身份正文。同一项目的两个摘要均未变化时，后续会话、headless 调用与单次运行 SHALL 复用已有确认、不重复询问；文件字节或有效 secret 掩码结果任一变化后 MUST 重新确认。确认与注入 MUST 使用同一份掩码后内存快照，不得在批准后重新读取文件。拒绝或未匹配确认且无确认通道时，系统 SHALL 继续任务但不注入项目级内容。持久化信任记录仅当文件不存在或文件为合法 v1 格式时才可写入；信任记录畸形、版本未知或不可读时，系统 MUST NOT 覆盖原文件，MUST 按未确认处理（Patch 2）；用户确认后可向本次内存快照注入，但后续进程 MUST 重新确认。信任记录写入采用 last-writer-wins 语义，v1 不加文件锁（Patch 3）；若并发写入导致某条目丢失，系统将在下次访问时重新请求确认，绝不产生未经确认的项目身份注入。REPL 拒绝项目身份后，当前会话 SHALL 复用已剥离 AGENTS/MEMORY 的 ApprovedIdentity，不对同会话后续任务重复询问（Patch 4）；`/reload` 或新进程 SHALL 重新触发信任询问。

#### Scenario: 用户批准项目身份快照
- **WHEN** 项目身份内容存在、尚未确认且交互用户批准其摘要
- **THEN** 系统持久化该快照的 canonical 项目标识摘要、原始内容摘要与有效输入摘要，并向当前及确认范围内的后续任务注入已批准内存快照

#### Scenario: 已确认快照在新进程中复用
- **WHEN** 某项目身份快照已获确认，用户随后以新的 REPL 会话或单次运行处理同一项目，且原始内容摘要与有效输入摘要均匹配
- **THEN** 系统不再请求确认并注入该已确认快照

#### Scenario: 已确认快照在 headless 调用中复用
- **WHEN** headless 调用加载的 canonical 项目标识摘要、原始内容摘要与有效输入摘要均匹配持久化确认
- **THEN** 系统无需交互通道即可注入该已确认内存快照

#### Scenario: 用户拒绝项目身份快照
- **WHEN** 用户拒绝项目身份摘要
- **THEN** 系统不注入 AGENTS 或 MEMORY，并使用其余可信身份层继续任务

#### Scenario: headless 环境没有确认通道
- **WHEN** 项目身份内容存在、没有匹配的持久化确认且调用路径没有交互确认通道
- **THEN** 系统默认不注入项目身份内容，且不把缺少确认误报为任务执行失败

#### Scenario: 已确认内容发生变化
- **WHEN** 已确认项目的 AGENTS/MEMORY 原始内容摘要或有效输入摘要任一改变
- **THEN** 系统在注入新内容前再次请求确认

#### Scenario: 确认后磁盘内容发生变化
- **WHEN** 用户批准已读取快照后，磁盘上的 AGENTS 或 MEMORY 在任务消息创建前被替换
- **THEN** 当前任务只注入刚刚获批的内存快照，新磁盘内容必须在下一次加载时作为新快照重新确认

#### Scenario: 信任记录畸形或写入失败

```

Full source: openspec/changes/compose-runtime-identity/specs/runtime-identity/spec.md
