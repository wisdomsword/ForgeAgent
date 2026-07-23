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

每个 Skill 位于 `<name>/SKILL.md`。front matter 只含 `name` 与单行 `trigger`；正文必须按顺序包含 `## Steps`、`## Failure Branches`、`## Completion Criteria` 且均非空。它在语义上正好形成规划要求的五段，同时保持普通 Markdown 可读、可评审。解析复用已安装的 PyYAML，拒绝未知 front matter 键、重复段、名称不一致、控制字符和固定大小上限。

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
