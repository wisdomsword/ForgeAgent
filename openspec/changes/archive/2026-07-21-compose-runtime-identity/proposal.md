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
