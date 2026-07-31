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
