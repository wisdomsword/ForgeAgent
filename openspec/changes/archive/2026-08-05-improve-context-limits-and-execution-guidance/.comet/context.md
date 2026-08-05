# Comet Design Handoff

- Change: improve-context-limits-and-execution-guidance
- Phase: design
- Mode: compact
- Context hash: dfd25530e391b5e506424620256c331f8ce9437269ad224cc14db18ee2018796

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/improve-context-limits-and-execution-guidance/proposal.md

- Source: openspec/changes/improve-context-limits-and-execution-guidance/proposal.md
- Lines: 1-29
- SHA256: e889ba97a0dec808e3f7a8af9b05f21fdbb5575670a260751a281b1c7dadc42b

```md
## Why

当前真实配置把单轮反馈和单工具结果分别限制为 120/40 近似 token，远低于模型自适应预算，但启动时不可见；同时固定协议过度强调“直接工具优先”，使模型把递归判重等聚合任务误降级为单层 `FileList`，再用截断片段向用户汇报未完成结果。

## What Changes

- 统一计算并公开当前模型的配置值、自适应值和实际生效的 round/tool feedback 上限。
- 交互式启动、`/model` 和 `/reload` 显示生效上限；任一显式值低于当前模型自适应值时输出安全、有界告警。
- 精确删除用户级配置中的 `round_feedback_max_tokens: 120` 与 `tool_result_max_tokens: 40`，保留含 API key 的其余文件字节和权限不变。
- 收紧固定执行协议：缺少必要信息时使用 Survey；直接工具只有能完成完整目标时才优先；递归扫描、聚合、转换或大量输出使用 Exec；大结果写入用户要求的文件并只回报摘要和路径。
- 保留现有统一 feedback limiter、诚实截断和安全投影，不增加 FileList cursor、分页或任意工具结果归档。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-context-management`: 自适应与显式反馈上限具有可复用的解析结果，并以当前模型自适应值判定低值配置。
- `repl-startup-information`: 启动、模型切换和重载公开实际反馈上限及低值告警。
- `runtime-identity`: 固定协议按完整任务适配工具，使用 Survey 保持澄清上下文，并对聚合/大输出任务使用 Exec 和文件交付。

## Impact

- 主要影响 `src/forgeagent/context.py`、`src/forgeagent/_cli_repl.py`、`src/forgeagent/cli.py`、包内 prompt 资源及对应 context/CLI/identity/mock replay 测试。
- 用户级 `~/.forgeagent/config.yaml` 只做已授权的两行精确删除；不读取、输出或重写 API key。
- 不新增依赖，不取消安全限额，不改变 HTTP 请求 schema、FileList 功能面或任意工具输出保留策略。

```

## openspec/changes/improve-context-limits-and-execution-guidance/design.md

- Source: openspec/changes/improve-context-limits-and-execution-guidance/design.md
- Lines: 1-79
- SHA256: 68be534866165acd495e877bf8efaccc0d0bdd1df8c3ce0f0d5eb60906cd85ca

```md
## Context

现有 `SlidingWindowContextPolicy` 已根据模型 input budget 计算反馈默认值，也允许配置显式覆盖，但解析结果只存在于策略内部。真实用户配置将 round/tool 上限设为 120/40 时，REPL 启动没有任何可见提示，用户只能从频繁截断反推原因。

固定协议同时把“直接工具匹配”描述得过宽。`FileList` 能列一个目录，并不能完成递归判重、聚合统计或大结果交付；模型仍可能因为名称看似匹配而在一次浅层调用后结束。

## Goals / Non-Goals

**Goals**

- 用一个纯解析结果统一表达配置值、自适应值和实际生效的 round/tool feedback 上限。
- 在交互启动、成功 `/model` 和 `/reload` 后显示生效上限，并对显式低值告警。
- 精确删除已授权用户配置中的 120/40 两行，不读取或重写 API key。
- 让固定协议按“能否完成整个目标”选工具，并明确 Survey、Exec 与大结果文件交付规则。
- 用 mock replay 和真实模型的受控临时目录 smoke 验证行为，不把 mock 输出冒充真实智能证据。

**Non-Goals**

- 不移除或放宽统一 feedback limiter。
- 不给 FileList 增加递归、cursor 或分页能力。
- 不自动归档任意工具的完整输出。
- 不改变 HTTP 请求 schema、非交互启动输出或 provider 参数。
- 不承诺模型在所有开放任务上确定性遵循提示词。

## Decisions

### 1. 抽取只读的反馈限额解析结果

在 `context.py` 提供一个不可变解析结果，包含 input budget、round/tool 的 adaptive、configured（可空）与 effective 值。`SlidingWindowContextPolicy` 消费同一解析函数，不再自行重复计算；CLI 也只读取该结果，不复制公式。

显式值仍按现有配置语义成为 effective 值。告警条件是 `configured is not None and configured < adaptive`，分别判断 round 与 tool；不凭主观阈值引入第二套“过低”标准。

### 2. 交互边界公开紧凑、无敏感信息的状态

启动摘要增加 `feedback round <effective> / tool <effective>`。存在显式配置时可同时显示 configured 与 adaptive 来源；任一显式值低于 adaptive 时另输出一行固定格式告警，只含字段名和数值。

成功 `/model` 和 `/reload` 后重新基于当前模型能力及当前配置解析并显示。非 TTY、`run`、HTTP 不新增 banner 输出。

### 3. 精确修改用户配置

只删除完整匹配的 `round_feedback_max_tokens: 120` 与 `tool_result_max_tokens: 40` 行，并在修改前后验证：两行修改前各存在一次、修改后均不存在、其余文件摘要在忽略这两行后相同、权限不变。检查过程只输出目标字段和摘要，不输出配置正文或 API key。

若目标行不再精确匹配，则停止外部修改并报告冲突，不能用 YAML 全量重写。

### 4. 按完整目标而非工具名称选择执行路径

固定协议按以下顺序说明：

1. 缺少继续执行所必需的信息时使用 `Survey`，并在收到答案后的同一 Task 继续。
2. 单个内置工具能够完整完成目标时直接调用它。
3. 递归遍历、跨文件聚合、内容哈希、转换或大量结果整理使用 Python/Exec。
4. 用户要求文件交付或结果较大时，执行代码将完整结果写到获准路径，最终回复只给数量、摘要和文件位置。

这只是路由提示；sandbox、确认和实际工具权限仍由宿主强制执行。

### 5. 分层验证真实行为

单元测试锁定限额公式、告警、命令刷新和 prompt 字节；mock replay 验证模型收到连续澄清上下文并产生预期工具调用。最后在项目内受控临时目录制造少量重复文件，通过真实配置模型运行 REPL 多轮 smoke，检查执行证据、报告文件和无截断摘要。真实 smoke 的模型输出作为特定环境证据，不提升为普遍保证。

## Risks / Trade-offs

- **启动摘要变长。** 使用单个紧凑字段和最多一条告警，且仅交互式显示。
- **显式低值可能是用户有意设置。** 只告警不覆盖；本次 120/40 删除来自用户明确授权。
- **提示词不能保证模型执行。** 用确定性契约测试加真实 smoke，并保留运行时终态与执行证据，不通过隐藏自动执行改变语义。
- **集中解析可能影响 HTTP Task。** 策略使用相同 effective 值，HTTP schema 与输出不变，运行回归测试。

## Migration Plan

1. 用失败测试定义解析结果、低值告警和命令刷新。
2. 抽取解析函数并让 context policy 与 CLI 共同消费。
3. 修改固定协议并增加 identity/mock replay 回归。
4. 精确删除用户配置两行并执行隐私安全校验。
5. 运行完整测试及受控真实模型 smoke。

回滚代码不会恢复用户配置的 120/40；如确需回滚，用户可显式重新配置。adaptive 默认本身是既有行为。

## Open Questions

无。告警判定、展示时机和配置修改范围均已明确。

```

## openspec/changes/improve-context-limits-and-execution-guidance/tasks.md

- Source: openspec/changes/improve-context-limits-and-execution-guidance/tasks.md
- Lines: 1-25
- SHA256: d343d0cd0f4ce9b390a6f935825653510bb7971b5f6e576bba62678a624e9b8f

```md
## 1. 共享限额解析

- [ ] 1.1 增加先失败的 context 测试，覆盖 adaptive、configured、effective、低值和模型切换计算
- [ ] 1.2 实现一个不可变的反馈限额解析结果，并由 SlidingWindowContextPolicy 消费

## 2. 交互可观察性

- [ ] 2.1 增加先失败的启动、`/model`、`/reload`、低值告警与非交互静默测试
- [ ] 2.2 在规定的交互边界显示紧凑的实际反馈限额和当前模型低值告警

## 3. 执行指引

- [ ] 3.1 增加先失败的固定协议与 mock replay 测试，覆盖 Survey 澄清、完整目标工具选择、Exec 递归聚合和文件交付
- [ ] 3.2 更新固定协议，不改变工具 schema、sandbox 检查或直接 prose 完成语义

## 4. 用户配置

- [ ] 4.1 在不读取或输出敏感值的前提下，验证已授权的 120/40 两行仍各精确存在一次
- [ ] 4.2 只删除这两行，并验证其余字节与文件权限不变

## 5. 验证

- [ ] 5.1 运行 context、CLI、identity、prompt、Task 与 HTTP 专项测试
- [ ] 5.2 运行 lint、类型检查、完整测试、OpenSpec 严格校验和真实模型受控重复文件扫描 REPL smoke
- [ ] 5.3 审查 diff 中是否存在公式漂移、secret 泄漏、非交互输出回归、prompt 越界或无关改动

```

## openspec/changes/improve-context-limits-and-execution-guidance/specs/repl-startup-information/spec.md

- Source: openspec/changes/improve-context-limits-and-execution-guidance/specs/repl-startup-information/spec.md
- Lines: 1-37
- SHA256: 88400a908e1feda960b7c5efc8653381c8dfb0b98e6917bb89ed5827573c8d68

```md
## MODIFIED Requirements

### Requirement: 启动摘要反映实际能力

ForgeAgent SHALL render one compact startup summary after successful interactive initialization containing the selected model, the actual sandbox tier, the resolved project root, the effective round/tool feedback limits, and an MCP availability summary when at least one MCP server is enabled. The feedback values MUST come from the shared current-model limit resolution. When an explicit round or tool value is lower than its current-model adaptive value, ForgeAgent SHALL emit one compact bounded warning containing only the affected field names and numeric configured/adaptive values. A successful `/model` or `/reload` SHALL recompute and display the same limit status. Non-interactive entry points MUST NOT gain startup output. The MCP summary denominator SHALL be the number of servers with `enabled: true` in the startup snapshot; disabled servers SHALL be excluded. The numerator SHALL be the servers that completed startup and are available. A required-server failure SHALL abort before a partial summary is rendered.

#### Scenario: One optional server fails
- **WHEN** two servers are enabled, one available and one optional unavailable
- **THEN** the summary reports `MCP 1/2`, keeps the REPL usable, and emits one compact optional-degradation line

#### Scenario: Disabled server is present
- **WHEN** a configured server is disabled and another enabled server is available
- **THEN** the disabled server is excluded from the startup denominator and does not create an optional-degradation warning

#### Scenario: No MCP server is enabled
- **WHEN** every configured MCP entry is disabled or no MCP configuration exists
- **THEN** the startup summary omits MCP counts and the REPL starts normally

#### Scenario: Adaptive feedback limits are active
- **WHEN** neither feedback limit is explicitly configured
- **THEN** the interactive startup summary displays the effective adaptive round and tool values without a low-value warning

#### Scenario: Explicit low limits are active
- **WHEN** one or both explicit limits are lower than the current model adaptive values
- **THEN** the startup summary displays the actual effective values and one bounded warning identifies each low configured/adaptive pair

#### Scenario: Model command refreshes limits
- **WHEN** an interactive user successfully changes models with `/model`
- **THEN** ForgeAgent recomputes and displays effective/adaptive feedback limits and warnings for the newly selected model

#### Scenario: Reload command refreshes limits
- **WHEN** an interactive user successfully runs `/reload`
- **THEN** ForgeAgent recomputes and displays effective/adaptive feedback limits and warnings from the reloaded configuration and current model

#### Scenario: Non-interactive output remains quiet
- **WHEN** ForgeAgent runs through piped REPL input, `run`, or HTTP
- **THEN** no feedback-limit startup summary or low-value banner is added to stdout or stderr

```

## openspec/changes/improve-context-limits-and-execution-guidance/specs/runtime-context-management/spec.md

- Source: openspec/changes/improve-context-limits-and-execution-guidance/specs/runtime-context-management/spec.md
- Lines: 1-25
- SHA256: 0c3d18b224c8629ec7d97bf869989835e2856d82780e538ae6e2cb8fbb6ad116

```md
## ADDED Requirements

### Requirement: 反馈限额解析结果统一且可观察

ForgeAgent MUST 通过同一个运行时解析结果计算并公开当前模型的 input budget、round/tool adaptive 值、可选 configured 值和 effective 值。Sliding-window policy 与 REPL 展示 MUST 消费同一解析结果，不得复制或偏离计算公式。显式配置值低于对应 adaptive 值时，系统 SHALL 标记该字段为低值配置，但 MUST NOT 在未获授权时自动覆盖用户配置。

#### Scenario: 没有显式反馈限额
- **WHEN** context 配置未设置 round 或 tool feedback 上限
- **THEN** configured 值为空，effective 值分别使用当前模型 input budget 对应的 adaptive 值

#### Scenario: 显式值高于自适应值
- **WHEN** 某一显式反馈限额等于或高于当前模型 adaptive 值
- **THEN** effective 值使用显式配置，且该字段不产生低值告警

#### Scenario: 显式值低于自适应值
- **WHEN** 某一显式反馈限额低于当前模型 adaptive 值
- **THEN** effective 值仍使用显式配置，同时解析结果标记该字段并供交互 REPL 输出有界告警

#### Scenario: 模型切换改变 input budget
- **WHEN** REPL 切换到具有不同 context window 或最大输出预留的模型
- **THEN** adaptive 值、低值判断和未显式配置字段的 effective 值均基于新模型重新计算

#### Scenario: HTTP 策略保持兼容
- **WHEN** HTTP Task 使用统一解析结果构造 context policy
- **THEN** 实际 limiter 语义与相同配置下既有行为一致，HTTP 请求和结果 schema 不新增字段

```

## openspec/changes/improve-context-limits-and-execution-guidance/specs/runtime-identity/spec.md

- Source: openspec/changes/improve-context-limits-and-execution-guidance/specs/runtime-identity/spec.md
- Lines: 1-32
- SHA256: 326dbb9755ee4c09ec22c4e3db538ace9a82ccc312c3cecbb6315e5318a9e0ef

```md
## MODIFIED Requirements

### Requirement: 分层运行时身份组合
系统 SHALL 按稳定的语义顺序组合固定 ForgeAgent harness 披露、中性默认或已批准 SOUL、不可覆盖协议、用户偏好、项目约束和手工记忆，并 SHALL 在组合完成后保留现有 MCP 工具描述。固定协议 MUST 向模型公开默认注册表中每个内置工具的协议名称、精确参数和适用场景。模型缺少继续执行所必需的信息时 SHALL 使用 Survey；单个直接工具能够完成整个目标时 SHALL 优先使用该工具；递归遍历、跨文件聚合、内容哈希、转换或大量输出任务 SHALL 使用 Python/Exec。用户要求文件交付或结果过大时，协议 SHALL 指示执行代码把完整结果写入获准路径，并仅回复摘要、数量和位置。固定协议 MUST 说明 `utils` 是执行代码中已注入且无需导入的对象，并 MUST 使用与 Runtime public API 一致的 `utils.set_state(key, value)` 和 `utils.get_state(key)` 调用签名；仅提交 Memory 候选的请求 MUST NOT 要求通过 Exec 记录同一偏好。身份文件内容 MUST 仅作为数据插入，不能选择模板、删除协议或改变协议顺序。协议不可覆盖保证仅限结构层面：系统保证身份文件内容不能修改、删除或移动固定协议字节的位置（Patch 6）；此保证不等于模型语义层的完整 prompt-injection 防护，模型仍可能响应身份文件中的指令性语义。组合所需包资源（system.j2、default_soul.md、protocol.md）缺失时，系统 MUST 报安装损坏，MUST NOT 静默回落为不含协议说明的提示词（Patch 5）。

#### Scenario: 全部可选身份层可用
- **WHEN** 用户 SOUL、USER 与已确认的项目 AGENTS、MEMORY 均存在
- **THEN** 系统按 harness 披露与 SOUL、固定协议、用户、项目、记忆的顺序向模型提供全部内容，并保留 MCP 工具描述

#### Scenario: 身份文件试图覆盖协议
- **WHEN** 任一身份文件包含要求忽略、替换或删除 ForgeAgent 协议的文本
- **THEN** 系统仍提供完整的程序控制协议段，且身份文件不能修改其内容或位置

#### Scenario: 无自定义身份时公开全部内置工具
- **WHEN** Task 使用包内默认身份与默认工具注册表运行
- **THEN** 固定协议说明 Exec、Edit、Survey、WebFetch、FileRead、FileWrite 和 FileList 的协议名称与精确参数，并按完整目标而不是工具名称表面匹配选择直接工具或 Exec

#### Scenario: 缺少执行所需信息
- **WHEN** 执行型目标缺少范围、目标路径或其他继续执行所必需的信息
- **THEN** 固定协议指示模型调用 Survey，并在工具反馈返回后继续原 Task，而不是以 prose 结束后等待无上下文的新任务

#### Scenario: 递归聚合任务不使用单层 FileList 收尾
- **WHEN** 用户要求递归查找重复文件、计算内容哈希、统计数量并交付大量位置
- **THEN** 固定协议指示模型使用 Python/Exec 完成遍历、聚合和文件写入，不把一次 FileList 的截断片段作为完成结果

#### Scenario: 大结果以文件交付
- **WHEN** 用户要求把大量结果保存为文件或完整结果不适合人类终端阅读
- **THEN** 固定协议指示执行代码写入获准路径，最终回复只包含完成状态、关键数量、简要摘要和文件位置

#### Scenario: 固定协议公开准确运行时 API
- **WHEN** Task 向模型提供默认固定协议
- **THEN** 协议说明 `utils` 已注入且无需 import，使用 `set_state(key, value)` 位置参数签名，并说明纯记忆请求无需 Exec

```
