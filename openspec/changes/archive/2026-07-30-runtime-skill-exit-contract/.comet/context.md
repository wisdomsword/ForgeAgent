# Comet Design Handoff

- Change: runtime-skill-exit-contract
- Phase: design
- Mode: compact
- Context hash: 02fcee5e4e7bfa1189573c3947262e7339d2313a33b08399dfad72404291b27d

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/runtime-skill-exit-contract/proposal.md

- Source: openspec/changes/runtime-skill-exit-contract/proposal.md
- Lines: 1-30
- SHA256: 43c9192b1e10405efbf5cda10b22bf18ff1bc7b7e0f7fd97b43b2eff7e33f6ff

```md
## Why

现有运行时 Skill 只校验五段文档结构，无法判断长期指令是否声明成功、失败、阻塞、需输入和超时/预算五类可观察退出条件。治理门禁已经要求这些字段，但运行时尚未执行同一契约，导致不完整的新增 Skill 仍可能进入模型可见目录。

本变更把退出条件纳入一个显式、可兼容的 Skill 文档版本：旧版 Skill 继续按既有规则读取；声明新版格式的 Skill 若缺少完整退出契约则 fail-closed 隔离，并提供有界诊断。

## What Changes

- 为 `SKILL.md` 增加显式 `format_version: 2` 运行时格式，要求五类退出条件分别声明可观察 `condition` 与负责 `verifier`。
- 在 Skill 解析结果中保留结构化退出条件，并在完整读取、项目可信摘要和内容摘要中稳定呈现，避免信任摘要遗漏治理字段。
- 新版 Skill 缺少字段、字段类型错误、空值、超限或使用无界绝对断言时跳过加载；旧版文档保持兼容。
- 为用户级、项目级、只读 Skill 工具和 `/reload` 路径补充契约测试与有界诊断测试。
- 明确本 change 不迁移既有 Skill 文件、不引入远程 Skills 供应链、不改变 PyPI 发布状态。

## Capabilities

### New Capabilities

- `runtime-skill-exit-contract`: 运行时 Skill 退出契约的版本化解析、验证、fail-closed 加载和结构化读取。

### Modified Capabilities

- `skills-runtime`: 修改 Skill 文档结构、发现、完整读取和可信摘要要求，使新版 Skill 的退出契约成为运行时可验证部分。

## Impact

- 代码：`src/forgeagent/skills.py` 及 Skill 相关工具装配和测试。
- 文档/spec：新增运行时退出契约 delta spec，并更新 `skills-runtime` 需求场景。
- 兼容性：默认保留现有无版本 Skill 的读取行为；只有明确声明 `format_version: 2` 的文档进入新校验路径。
- 依赖与发布：不新增依赖，不上传包、不创建 tag、不 push，也不推进 `publish-v0-1-0`。

```

## openspec/changes/runtime-skill-exit-contract/design.md

- Source: openspec/changes/runtime-skill-exit-contract/design.md
- Lines: 1-43
- SHA256: 4b3acf59d5c55678eee13cfdad93c1fd2690fdbc767d5f75c8360ab738fa270b

```md
## Context

`src/forgeagent/skills.py` 当前把 front matter 限定为 `name` 与 `trigger`，正文限定为三段，并将解析后的五段内容放入不可变 `SkillDefinition`。项目级 Skill 的信任摘要和 effective-input digest 都由该定义渲染而来。M32 已把长期 Prompt/Skill 的五类退出声明纳入开发期治理，但运行时仍无法区分 governed Skill 与旧格式 Skill。

本 change 需要在不迁移历史文件、不引入新依赖、不改变项目级信任边界的前提下，把新契约接入发现、读取和摘要流程。

## Goals / Non-Goals

**Goals:**

- 引入显式 `format_version: 2`，对新格式执行 fail-closed 的五类退出条件校验。
- 保持无版本历史 Skill 的读取兼容，并让调用方可识别 legacy 与 governed 定义。
- 让完整渲染、按段读取、项目 effective digest 和敏感值掩码覆盖退出条件。
- 用单元测试覆盖成功、缺失字段、类型/边界、无界断言、旧格式和信任摘要变化。

**Non-Goals:**

- 不自动改写或迁移现有 `SKILL.md`。
- 不建立远程 Skill 分发、签名、撤销或供应链平台。
- 不改变 Skill 执行权限、sandbox、Task 完成判定或 PyPI 发布状态。

## Decisions

1. **显式版本而非隐式强制。** `format_version` 缺失视为 version 1，`2` 才启用退出契约；这样不会在本 change 中让用户目录里的既有 Skill 集体消失。其他版本 fail-closed。
2. **结构化 front matter。** version 2 的 front matter 只允许 `name`、`trigger`、`format_version`、`exit_conditions` 五个固定键；`exit_conditions` 是五个固定映射，每项只允许 `condition` 和 `verifier`。正文三段保持原样，避免重复解析协议。
3. **有界文本规则。** `condition` 和 `verifier` 必须是非空字符串，单项不超过 512 UTF-8 字节；只含无界绝对断言的 condition（例如 `100% complete`、`always succeeds`、`全部完成`）拒绝。规则保持确定性、无网络和无额外模型调用。
4. **定义与渲染。** `SkillDefinition` 增加 `format_version` 和只读 `exit_conditions` 映射。`_render_full_skill` 在 version 2 文档中追加 `## Exit Conditions`，按固定顺序输出五类及其字段；legacy 文档输出保持字节级兼容。`read(..., "exit_conditions")` 对 legacy 返回 `None`，对 governed 返回结构化文本。
5. **信任摘要绑定。** project Skill 的 effective-input digest 继续对完整渲染结果取摘要，因此任何退出条件变化都会触发已有确认；raw digest 仍绑定原始字节，保持双摘要语义。
6. **错误面。** 所有版本 2 校验失败都转为 `ValueError("invalid exit contract")`，沿用现有 `_discover` 的单条 bounded diagnostic 和“跳过坏文档、继续发现”语义。

## Risks / Trade-offs

- [兼容性] 旧格式不会自动获得治理保证 → 通过 `format_version` 明示 legacy 状态，并在开发期 change/文档中要求新建或实质修改的 Skill 使用 version 2。
- [规则误报] 某些合法自然语言可能包含绝对词 → 只拒绝纯绝对断言，不限制含可观察条件的正常句子，并用回归测试锁定边界。
- [摘要长度] 退出条件加入完整渲染可能增加 trust summary 输入 → effective digest 不受摘要展示截断影响；既有 32 KiB 文档上限继续生效。

## Migration Plan

无需数据迁移。新建或实质修改的 Skill 使用 `format_version: 2` 和五类退出条件；未迁移的历史文档继续按 version 1 读取。若 version 2 文档被拒绝，诊断会指出 Skill 名称和 `invalid exit contract`，用户修正文件后通过 `/reload` 获取新快照。

## Open Questions

无。运行时执行退出条件本身仍由现有模型/Task 流程负责，本 change 只负责声明完整性和可信读取。

```

## openspec/changes/runtime-skill-exit-contract/tasks.md

- Source: openspec/changes/runtime-skill-exit-contract/tasks.md
- Lines: 1-17
- SHA256: 9df0250012e1edecf5fe656ab565249cbfa928888dd2454cafb715798c2c3a00

```md
## 1. 运行时契约模型

- [ ] 1.1 为 `SkillDefinition` 增加显式 `format_version` 和不可变的五类 `exit_conditions` 数据，同时保持 legacy 文档的渲染与读取逐字节兼容。
- [ ] 1.2 增加确定性的 version 2 front matter 解析、固定键校验、有界 condition/verifier 校验和 fail-closed 诊断；不引入新依赖。
- [ ] 1.3 在 governed Skill 的完整读取中渲染退出条件，并通过只读 Skill 工具暴露 `exit_conditions` 段；保持 legacy 段读取行为不变。

## 2. 信任边界与回归测试

- [ ] 2.1 按测试先行增加 fixture 和测试，覆盖有效 version 2、legacy 兼容、不支持版本、缺失/错误/超限字段、无界绝对断言拒绝和敏感值掩码。
- [ ] 2.2 增加测试证明项目 Skill 仅修改退出 condition/verifier 时 effective digest 发生变化，同时 raw/effective 双摘要确认语义保持不变。
- [ ] 2.3 增加完整读取、分段读取、有界诊断、`/reload` 快照替换和既有 SkillTool 行为测试。

## 3. 文档与验证

- [ ] 3.1 在实现验证后更新 canonical `skills-runtime` Purpose 和 requirements，说明版本化退出契约与 legacy 兼容策略。
- [ ] 3.2 编写 Superpowers 实施计划与带精确命令/结果的验证报告，并更新借鉴清单，将运行时强制校验标记为已交付。
- [ ] 3.3 运行聚焦测试、全量 pytest、ruff check/format、`git diff --check`、`openspec validate --all --strict --no-interactive` 和本地 `uv build`；不得执行 PyPI 上传、tag 或 push。

```

## openspec/changes/runtime-skill-exit-contract/specs/runtime-skill-exit-contract/spec.md

- Source: openspec/changes/runtime-skill-exit-contract/specs/runtime-skill-exit-contract/spec.md
- Lines: 1-38
- SHA256: dc636bd132efdd9e9cb0b4669b34bc516599ced709b69e7e941cac61690214e5

```md
## ADDED Requirements

### Requirement: Versioned Skills declare bounded exit contracts
Runtime Skill documents declaring `format_version: 2` SHALL include exactly five exit classes: `success`, `failure`, `blocked`, `needs_input`, and `timeout_or_budget`. Each class MUST contain non-empty string fields `condition` and `verifier`, each bounded to 512 UTF-8 bytes. The runtime MUST reject an absolute, unbounded claim when it is the only condition text, including claims that rely solely on words such as "always", "never", "all", "100%", or "完美".

#### Scenario: Version 2 Skill with complete exits is accepted
- **WHEN** a Skill front matter declares `format_version: 2` and all five exit classes contain bounded condition and verifier strings
- **THEN** the Skill enters the immutable registry and its structured exits are available to the read-only Skill tool

#### Scenario: Version 2 Skill missing one exit is isolated
- **WHEN** a version 2 Skill omits `blocked` or gives it an empty field
- **THEN** the runtime skips that Skill, emits one bounded `invalid exit contract` diagnostic, and continues discovering other Skills

#### Scenario: Version 2 Skill uses an unbounded absolute condition
- **WHEN** a version 2 Skill uses only an absolute claim such as `100% complete` as an exit condition
- **THEN** the runtime skips that Skill with an `invalid exit contract` diagnostic

### Requirement: Legacy Skill compatibility is explicit and bounded
Runtime Skills without `format_version` SHALL continue to use the existing five-section parser and SHALL be represented as legacy definitions. Legacy definitions MUST NOT be treated as satisfying the version 2 exit contract, and the runtime SHALL expose their version so callers can distinguish compatibility from governed declarations.

#### Scenario: Existing legacy Skill remains readable
- **WHEN** a pre-existing Skill has only `name`, `trigger`, `Steps`, `Failure Branches`, and `Completion Criteria`
- **THEN** the Skill remains discoverable with `format_version` equal to 1 and its existing full/section reads are unchanged

#### Scenario: Unsupported format version is isolated
- **WHEN** a Skill declares a format version other than 1 or 2
- **THEN** the runtime skips it with a bounded `invalid format version` diagnostic

### Requirement: Trust and reads include the governed contract
The runtime SHALL include a version 2 Skill's five exit classes in deterministic full rendering and project trust effective-input digests. The read-only Skill tool SHALL allow the `exit_conditions` section and SHALL return a deterministic structured rendering without exposing unmasked secret values.

#### Scenario: Project approval covers exit conditions
- **WHEN** a trusted project Skill changes only one exit condition or verifier
- **THEN** its effective-input digest changes and the project Skill requires re-confirmation before overriding a user Skill

#### Scenario: Exit conditions are read by section
- **WHEN** the model requests `exit_conditions` for a governed Skill
- **THEN** the tool returns the five named classes and their condition/verifier pairs, with secrets masked

```

## openspec/changes/runtime-skill-exit-contract/specs/skills-runtime/spec.md

- Source: openspec/changes/runtime-skill-exit-contract/specs/skills-runtime/spec.md
- Lines: 1-23
- SHA256: d86acf9b26c40eb991290081f8a1c21904646810834b7f028962d15d999b2e02

```md
## MODIFIED Requirements

### Requirement: Skill 文档具有可验证的固定结构
系统必须（SHALL）只接受位于独立目录 `SKILL.md` 中、包含非空 `name`、`trigger`、`steps`、`failure_branches` 与 `completion_criteria` 五段内容的 Skill。`name` 必须（MUST）是与目录名一致的 kebab-case 标识符；无效、超限或不可读文档不得进入模型可见目录。文档若声明 `format_version: 2`，还必须包含 `success`、`failure`、`blocked`、`needs_input`、`timeout_or_budget` 五类退出条件；每类都必须有有界 `condition` 与 `verifier`，否则按 fail-closed 规则隔离。未声明版本的既有文档按 legacy version 1 兼容读取，不得被误标为满足 version 2 治理契约。

#### Scenario: 有效 Skill 被发现
- **WHEN** 用户级目录包含结构完整且名称匹配的 `review-code/SKILL.md`
- **THEN** 系统将 `review-code` 加入可用 Skill 目录

#### Scenario: 无效 Skill 被隔离
- **WHEN** `SKILL.md` 缺少失败分支或名称与目录不一致
- **THEN** 系统跳过该 Skill、输出有界诊断且继续加载其他有效 Skill

#### Scenario: governed Skill 缺少退出契约被隔离
- **WHEN** `SKILL.md` 声明 `format_version: 2` 但缺少五类退出条件之一
- **THEN** 系统跳过该 Skill、输出 `invalid exit contract` 有界诊断且继续加载其他有效 Skill

### Requirement: 模型通过只读工具按需加载 Skill
系统必须（SHALL）提供只读 `Skill` 工具，接收一个目录中存在的 Skill 名称并把经过掩码的完整五段文档作为工具反馈返回；工具还必须（MUST）允许按 `steps`、`failure_branches` 或 `completion_criteria` 单段重读，以便在 M17 有界反馈截断整篇内容后继续。对于声明 `format_version: 2` 的 Skill，工具还必须允许按 `exit_conditions` 单段重读，并返回五类退出条件的结构化文本；模型自主依据触发描述决定是否调用，不得（MUST NOT）增加独立意图识别器或额外 LLM 请求。

#### Scenario: governed Skill 的退出契约可按需读取
- **WHEN** 模型针对当前任务调用 `Skill` 并请求 `exit_conditions`
- **THEN** 下一轮反馈包含五类退出条件及其 condition/verifier，且敏感值已掩码

```
