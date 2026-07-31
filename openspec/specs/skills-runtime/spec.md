# skills-runtime Specification

## Purpose
Provide a verifiable, masked, on-demand local Skill registry with trusted project overrides, legacy compatibility, and governed exit-contract enforcement.
## Requirements
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
