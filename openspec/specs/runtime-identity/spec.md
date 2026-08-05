# runtime-identity Specification

## Purpose
Define composed runtime identity and provenance so providers, models, tools, and audit records remain distinguishable without hard-coded vendor assumptions.
## Requirements
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
- **WHEN** 持久化信任记录缺失、畸形或不可读，或当前批准无法原子写入记录
- **THEN** 系统不得把该记录视为已有确认；当前交互批准可用于本次内存快照，但后续进程仍须重新确认

### Requirement: 身份禁用与热重载
系统 SHALL 提供 `--no-identity` 诊断开关以禁用所有自定义身份文件，同时保留包内默认身份、固定协议和 MCP 工具描述。REPL `/reload` SHALL 使后续任务重新读取身份文件与确认相关状态，单次运行 SHALL 使用启动时读取的当前快照。

#### Scenario: 使用 no-identity
- **WHEN** 用户以 `--no-identity` 启动 REPL 或单次任务
- **THEN** 系统不读取 SOUL、USER、AGENTS 或 MEMORY，并使用兼容的包内默认提示词运行

#### Scenario: REPL 中重载身份文件
- **WHEN** 用户修改身份文件后执行 `/reload`
- **THEN** 下一任务使用重新读取的身份内容，且发生变化的项目内容重新经过确认

### Requirement: ForgeAgent harness 披露与身份防污染
The system SHALL place a program-controlled role segment at the start of the system prompt that identifies the assistant's primary product identity as ForgeAgent and states that it operates through the ForgeAgent code-as-action workflow. The fixed segment SHALL instruct the model to begin identity answers with ForgeAgent and SHALL NOT provide native model/provider identity cues that can replace the product identity. For an explicit identity question that ends as prose, if the model response does not begin with ForgeAgent, the runtime SHALL replace that identity response with a fixed ForgeAgent product disclosure. The approved SOUL (or neutral default SOUL when absent) SHALL define the persona, optional name, voice, and values expressed within that product identity, suppressing unrelated product personas learned from training data or introduced by task content. The fixed disclosure MUST NOT prevent a user from defining a legitimate persona, name, or communication style through an approved SOUL.

#### Scenario: User asks who the assistant is
- **WHEN** the user asks the assistant to identify itself
- **THEN** the system prompt begins with a ForgeAgent role segment that instructs the model to begin its answer with ForgeAgent and contains no native model/provider identity cue
- **AND** a prose response that violates the ForgeAgent prefix is replaced by a ForgeAgent product disclosure before the task outcome is rendered

#### Scenario: Task content induces another product identity
- **WHEN** the user goal or model prior induces the model to identify as an underlying model or another product instead of ForgeAgent
- **THEN** the model context still contains fixed ForgeAgent product identity, SOUL priority, and instructions that unrelated identities cannot replace it
- **AND** if the resulting prose identity answer still omits ForgeAgent, the runtime disclosure boundary restores the product identity

#### Scenario: User SOUL defines an Agent persona
- **WHEN** an approved user SOUL specifies a name, persona, or communication style without attempting to modify the fixed protocol
- **THEN** the model context preserves that SOUL persona within the ForgeAgent product identity and prioritizes it over task text or training priors

### Requirement: 可执行兼容性验证
系统 MUST 以身份组合矩阵、固定协议断言、身份输入生效专项测试、Kiro 回归和现有离线 golden 可信核心全量回放验证该能力。身份加载路径 MUST 作为库内依赖注入参数可替换，使测试与 golden 运行不受开发机上真实身份文件影响，但 MUST NOT 因此新增 CLI 路径配置面。没有自定义身份文件时，现有 20 项 golden 可信核心 MUST 无回归；新增 G381-G400 候选目录 SHALL 维持既有 40/25/20/10/5 类别配比，且候选 MUST NOT 被宣称为已验证。

#### Scenario: 运行身份组合矩阵
- **WHEN** 测试覆盖 SOUL、USER、AGENTS、MEMORY 的存在与缺失组合以及项目确认结果
- **THEN** 每个组合只包含预期段落，固定身份和协议在所有组合中保持存在且顺序稳定

#### Scenario: 身份输入在任务中可观察生效
- **WHEN** 专项 mock replay 提供手写 SOUL 或已确认 AGENTS 内容并运行任务
- **THEN** 记录客户端收到的模型上下文包含对应身份内容，且确定性判定器验证正确来源、顺序与任务可见性而不把 MockClient 的脚本响应冒充真实模型遵循证据

#### Scenario: 运行现有离线 golden
- **WHEN** 在没有自定义身份文件的隔离环境运行完整离线 golden 可信核心
- **THEN** runner 继续报告 20/20 场景通过且退出码为零

