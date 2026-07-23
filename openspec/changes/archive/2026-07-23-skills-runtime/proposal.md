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
