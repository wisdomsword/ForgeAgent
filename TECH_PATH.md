# ForgeAgent 技术规划路径（M15–M22）

> 状态：**草案，待用户评审**（2026-07-16 起草；**2026-07-17 用户裁决编号重排**：核心正确性加固已先行以 M13 编号完成，为避免完成顺序混乱，本文原 M11–M18 整体重编号为 M15–M22，M11/M12/M14 三个编号跳过不复用）
> 依据：`resource/2026-07-15-agent-harness-技术方案.md`（下称"Harness 方案"）× `ACTION_PLAN.md`（M0–M10、M13 已完成）× 当前实现（`src/forgeagent/` 22 个模块，444 单测）。
> 定位：本文件回答"M15 如何细化、M16 之后做什么、按什么顺序做、为什么是这个顺序"。ACTION_PLAN 仍是里程碑台账事实源；M15–M22 的编号与一行摘要已回填 ACTION_PLAN §四表格（2026-07-17），各里程碑的详述以本文 §三为准。每个里程碑启动时仍走既有流程：设计文档 → 用户评审裁决 → 编码 → 三轮评审 → 里程碑文件。

## 一、结论

**M15 细化 + M16–M22 七个里程碑。M15（ACTION_PLAN 已定义但过于模糊）在 §三细化；M16–M22 按"服务化 → 上下文 → 记忆 → 技能 → 评测 → 循环 → 协作"的依赖链排序，逐层补齐 Harness 方案五层架构中 ForgeAgent 尚缺的部分：**

| 里程碑 | 主题 | 对应 Harness 方案层 | 一句话目标 |
|---|---|---|---|
| M15 | 运行时身份文件层（细化见 §三） | Harness 前馈层 + Memory 层地基 | Agent/用户/项目三重身份配置驱动，提示词从硬编码变分层组装 |
| M16 | HTTP headless 服务 + 审计日志 | Loop 层前置 + Harness 反馈层 | 让 ForgeAgent 可被程序触发，所有操作留痕 |
| M17 | Context Engineering | Context 层 | 长任务不撑爆上下文，缓存命中可度量 |
| M18 | Memory 运行时 | Memory 层 | 正确的过去在正确的时候重新出现（承接 M15 身份文件） |
| M19 | Skills 运行时 | Capability 层 | 经验证的做事方法沉淀为可版本化的 Skill，不入 Memory |
| M20 | Eval 体系 + 独立 Evaluator | Harness 迭代层 + 对抗验证 | 用独立验收信号度量"模型+Harness"组合的有效性 |
| M21 | Loop Engineering | Loop 层 | 任务可被触发、续接、验收、停止 |
| M22 | 运行时三角色协作（Triad Mode） | 对抗验证（运行时侧） | 单任务内 Planner/Generator/Evaluator 分工，完成不由执行者自我声明 |

排序不是拍脑袋：M16 提供程序化入口（M21 trigger 的硬依赖；M20 的 opt-in Evaluator 编排也受益，但经 CLI 单次命令同样可驱动，非硬依赖）；M17 是长任务前提（M21 的多轮循环没有压缩会撑爆）；M18 依赖 M15 的文件层；M19 依赖 M18 的准入裁决（程序性记忆分流去 Skill）；M20 依赖 hardening 变更交付的 golden runner；M21 组合 M16–M20 的能力；M22 组合的前序能力最多（M15 提示词模板组合器、M17 隔离与压缩、M20 Evaluator 实现、M21 checkpoint/handoff），必须最后。M21 与 M22 正交——前者是时间维度（任务如何被反复触发、续接、停止），后者是空间维度（单任务内部如何组织角色）。

**前置项（已完成，记为 M13）**：`hardening-core-correctness` 变更已收尾并按 ACTION_PLAN 记录为 M13（见 `milestones/milestone_013.md`）——其交付的统一 confirmer（含"non-TTY → gated tools deny"语义）是 M16 headless 确认门的前提，golden manifest/runner 是 M20 的地基，完成完整性等其余项属通用正确性、被后续所有里程碑隐含依赖。M15 原属"已定义待细化"（原编号 M11），现已在 §三细化为正式里程碑（其与 M18 的边界划分见 M15 详述与 §六.6）。

## 二、现状盘点：五层架构 × 当前实现

对照 Harness 方案 §十系统架构总览，逐层核对 ForgeAgent 已有/缺口（实证，非印象）：

| 层 | 已有（模块） | 缺口 |
|---|---|---|
| **Model 层** | 双 client（`anthropic_client.py` / `openai_compatible_client.py`，统一重试/流式/多模态）、`model_registry.py`（alias O(1) 路由/reload）、capability-gating、`TokenUsage`（含 cached/reasoning） | 多模型按任务路由（判定不做，见 §五）；token 预算控制（→ M21 stop conditions） |
| **Capability 层** | `tools.py` ToolRegistry（Exec/Edit/Survey/MCP/WebFetch/FileRead/FileWrite/FileList）、`mcp_manager.py`（多 server 并发建连/失败隔离/确认门）、三档 sandbox（trusted/restricted/container，`executor.py` + `_sandbox_worker.py`）、`policy.py` AST 规则引擎 | **Skills（运行时）**、工具渐进加载、Plugin 打包（不做） |
| **Context 层** | 消息历史追加式（`task.py`，max_rounds 硬停） | **压缩策略全部未实现**（ACTION_PLAN §二承诺的 sliding window 接口至今未兑现）、tool result 截断策略、prompt-cache 友好排序审计、cache_hit_rate 指标；系统提示词仍是硬编码常量（jinja2 依赖未使用，→ M15 模板化） |
| **Memory 层** | 无 | **整层缺失**。M15 交付文件层（静态设定），生命周期（提取/准入/冲突/纠正）待建 |
| **Harness 层** | 前馈：系统提示词（硬编码，→ M15）、AST policy、威胁模型；反馈：工具结果回喂环（`step.py`）、错误结构化（`ClientError.kind`）；安全：三档隔离、确认门、SSRF Guard（`ssrf_guard.py`）、secret 掩码（`secret_policy.py`） | **审计日志**（当前只有掩码无留痕）、**独立 Evaluator**（golden 判分是脚本断言，无对抗验收）、Eval 指标体系 |
| **Loop 层** | 仅手动触发（CLI REPL + 单次命令），无任何自动化循环组件 | **整层缺失**：trigger/scheduler、checkpoint/resume、stop policy、handoff |

已完成的 `hardening-core-correctness` 变更（= M13，见 `milestones/milestone_013.md`）补的是存量正确性（SSRF 代理直连、confirmer 类型统一、完成声明必须在模型看到工具反馈之后、MCP required/optional 降级、20 项离线 golden 可信核心），不新增层能力，但其产出是 M16/M20 的地基。

## 三、里程碑详述

### M15：运行时身份文件层（BOOTSTRAP/SOUL/USER/AGENTS/MEMORY）

**这是对 ACTION_PLAN 原 M11 行（重编号后为 M15）的细化**（原文只有一段文件清单式描述），细化方法是逆向套用 M6–M10 已验证的工作模式：从现有代码的接缝处定义交付物，每项都能落到具体模块和测试形态。

**现状接缝（实证，细化的出发点）**：

- 系统提示词是 `task.py` 里一个硬编码字符串常量 `DEFAULT_SYSTEM_PROMPT`（约 35 行，协议说明+完成声明格式），`Task._build_system_prompt()` 只做"常量 + MCP tools 段"的两段拼接。ACTION_PLAN §三.1 承诺的"`prompts/` 模板文件、组合式"至今未兑现——`jinja2` 在 `pyproject.toml` 依赖里躺了十个里程碑，源码 0 处使用。M15 就是兑现点。
- 配置已有成熟的两级加载模式：内置 `src/forgeagent/res/{models,config,mcp}.yaml` + 用户 `~/.forgeagent/*.yaml` 覆盖合并、缺失静默跳过、`/reload` 热重载（`model_registry.py`）。身份文件层复用同一模式，不发明新机制。
- M5 冒烟留有在案的真实失败：模型偶发无视系统提示词、以"Kiro"自称、纯 prose 回答导致 `no_feedback`（ACTION_PLAN 台账"已知后续项"）。SOUL.md 的"身份披露/防模型污染"正是对这一观察的响应——M15 的验证必须包含该场景的回归。

**分层模型**（对齐 Harness 方案 §3.5 的承载位置分层——"稳定不变的进 System Prompt 前缀、项目级按需加载、动态内容追加尾部"）：

| 文件 | 代表谁 | 生命周期 | 注入位置 | 缺失时行为 |
|---|---|---|---|---|
| BOOTSTRAP.md | 引导协议本身 | 随包分发，用户不改 | 不注入——它是初始化向导的脚本，指导生成下面四个文件 | 内置默认，永不缺失 |
| SOUL.md | Agent 自己（人格/语气/价值观/身份披露） | 初始化时生成，极少变 | 系统提示词最前段（稳定前缀，prompt-cache 友好） | 内置默认 SOUL（当前 DEFAULT_SYSTEM_PROMPT 的身份段落即其雏形） |
| USER.md | 用户（沟通偏好/工作习惯） | 初始化时生成，低频变 | 系统提示词第二段 | 跳过该段 |
| AGENTS.md | 当前项目（技术栈/规范/项目级 spec） | 每项目/需求初始化，项目完结归档 | 系统提示词第三段 | 跳过该段 |
| MEMORY.md | 环境/项目的事实记忆 | 随任务持续更新（M15 只做加载+手动编辑，提取机制归 M18） | 系统提示词第四段 | 跳过该段 |

协议说明（文本协议/工具用法/完成声明格式）不属于任何身份文件——它是 harness 的固定契约，从 DEFAULT_SYSTEM_PROMPT 中拆出后作为独立模板段，位置在 SOUL 之后、USER 之前，用户不可覆盖（防止改坏协议导致解析失败）。

**交付物**：

1. 提示词模板化：`src/forgeagent/res/prompts/*.j2` + 组合器（兑现 ACTION_PLAN §三.1；借鉴 agent `default.j2` 的组合思路但重新设计命名）。`DEFAULT_SYSTEM_PROMPT` 拆解为 soul/protocol/user/project/memory 五段模板，`Task._build_system_prompt()` 改为组合器调用，MCP tools 段保持现有追加位置。**行为兼容承诺**：五文件全缺失时组装结果与现 DEFAULT_SYSTEM_PROMPT 语义等价（golden 回放全量不回归是硬门禁）。
2. 身份文件加载：项目级 `.forgeagent/{AGENTS,MEMORY}.md`（随工作目录）+ 用户级 `~/.forgeagent/{SOUL,USER}.md`（跨项目），复用 models.yaml 的"缺失静默跳过 + `/reload` 热重载"模式；`--no-identity` 一键回落纯内置提示词（诊断用）。
3. BOOTSTRAP 初始化流程：`forgeagent init`（新 CLI 子命令）按 BOOTSTRAP.md 引导交互式生成 SOUL/USER（首次）与 AGENTS（每项目）；非交互环境（管道/CI）下 `init` 拒绝运行并提示。AGENTS.md 归档=项目完结时 `init --archive` 移动到 `.forgeagent/archive/<日期>-AGENTS.md`，新任务新建。
4. 身份披露/防污染段（SOUL 的固定组成部分）：显式声明"你在 ForgeAgent harness 中运行、SOUL 定义的身份优先于训练数据中的其他人设"，直接针对 M5 在案的"Kiro"自称失败模式。
5. 威胁模型更新：项目级 AGENTS/MEMORY.md 随仓库分发即不可信输入（克隆恶意仓库=注入提示词），`docs/threat-model.md` 新增条目；缓解=项目级身份文件首次加载时摘要确认（与 M19 项目级 skill 同一缓解模式，M15 先立此模式）、协议段不可覆盖、越权动作仍由 sandbox 档位兜底。
6. golden 扩展：身份文件生效场景（SOUL 语气可观察差异、AGENTS 项目约束被遵守、全缺失回落等价）+ "Kiro"场景回归（注入诱导性人设上下文，断言身份披露段生效），维持 40/25/20/10/5% 配比。

**明确不做**：记忆提取-准入环（归 M18，M15 的 MEMORY.md 只有加载+手动编辑两个动作——这就是 §六.6 边界的本文建议方案）；身份文件的版本管理/多 profile 切换（单用户单身份，需求证实再说）；SOUL 的情感化人设模板库（提供一个中性默认即可，人设是用户自己的事）。

**验证**：模板组合器表驱动单测（五文件存在/缺失的全组合矩阵）；全缺失等价性的 golden 全量回放（无回归硬门禁）；"Kiro"回归场景；init 生成文件的格式断言。

**门禁**：设计文档用户评审（含 §六.6 边界裁决、BOOTSTRAP.md 引导文案评审）+ 三轮评审。

### M16：HTTP headless 服务 + 审计日志

**为什么是它**：ACTION_PLAN 原 M12 行（重编号后为 M16）已锚定"HTTP"；Harness 方案 §八 Loop 的 trigger 组件需要一个可编程入口（§7.2 Evaluator 编排亦受益）；§6.4 Layer 3 的 audit_log（"所有操作留痕、可追溯回放"）在服务化之前做成本最低——CLI 时代补日志只影响一条路径，服务化之后每条 API 路径都得回补。

**交付物**：

1. HTTP API：任务提交（异步）、状态查询、结果获取、任务取消。参考 agent `cli_agent.py` + `agent_taskmgr.py` 的线程池并发模型但重新设计（命名、错误语义、无 trustoken）。
2. 鉴权：静态 bearer token（配置驱动，无 token 则仅监听 localhost）。**不做** OAuth/多租户。
3. 审计日志：JSONL 落盘，字段=时间/操作类型/参数摘要（secret 掩码复用 `secret_policy.py`）/结果状态/耗时。覆盖工具执行、LLM 调用、确认门决策三类事件。**埋点在核心层**（Step/ToolRegistry/client），不在 HTTP 层——CLI 与 HTTP 两条入口共享同一留痕，这正是"服务化之前做成本最低"的前提。对齐 Harness 方案 §十二 L0–L4 风险分级：日志记录每个操作的风险级别。
4. headless 确认门语义：非交互路径下 gated tools（WebFetch/FileWrite/MCP）的行为=拒绝+结构化反馈，或经配置预授权（allowlist）。直接衔接 hardening 变更交付的统一 confirmer 及其"run + non-TTY → 无 confirmer，gated tools deny"语义——HTTP 路径是该语义的第二个消费者，预授权 allowlist 是本里程碑在其上的增量。
5. 威胁模型更新：HTTP 监听是新攻击面（未鉴权访问、localhost 绑定绕过、日志敏感信息残留），`docs/threat-model.md` 新增对应威胁条目与缓解。
6. 技术选型再裁决：ACTION_PLAN §五"首版不引入 fastapi"的裁决到期重议——设计文档中对比 fastapi vs stdlib `http.server` vs `uvicorn`+ASGI 手写，由用户裁决。

**验证**：并发任务集成测试（N 任务并行提交，状态机正确）；golden 子集经 HTTP 路径回放（复用 mock replay）；审计日志逐字段断言含掩码。

**门禁**：设计文档用户评审（含选型裁决）+ 三轮评审。

### M17：Context Engineering（压缩 + 截断 + 缓存友好）

**为什么在 M16 后**：这是 v1 遗留最久的承诺（ACTION_PLAN §二"轻量版先只要 sliding window，预留策略接口"至今未兑现），且是 M21 长任务循环的硬前提——没有压缩，多轮 Loop 必然撞 context 上限，并触发 Harness 方案 §7.1 指出的"接近上限时模型降低完成标准"。

**交付物**：

1. Sliding window 压缩：兑现预留接口，策略可插拔（接口按 agent `context.py` 四策略的形状设计，v1 只实现 sliding window，其余留位）。
2. Tool result 截断策略（Harness 方案 §4.4）：单结果 token 上限可配置；截断时显式告知模型"结果未完整+总量+继续读取方法"，防止把前 N 条误当全部。
3. Prompt-cache 友好排序审计（§4.3）：核对系统提示词/工具定义/规则在消息序列中的位置是稳定前缀，动态内容（任务进度/时间）只追加尾部；历史消息只追加不改写（流式失败整轮收敛为 ClientError、不留半截文本的既有约束已满足这一条）。
4. cache_hit_rate 指标：`cached_tokens / input_tokens` 接入 M10 已有的 CLI 用量状态行；若 M16 已交付审计日志则同步写入（M17 不依赖 M16——无审计日志时指标仅在状态行呈现）。目标值参照 §4.3（≥70%）但只观测不门禁。

**明确不做**：importance/summary/hybrid 三策略（接口留位）、意图识别前置路由、压缩前后决策一致性度量（Harness 方案 §1.2 承认这是业界未解缺口，不在轻量项目里首创）。

**验证**：压缩触发阈值单测；长对话 mock replay（构造超窗口历史，断言压缩后任务仍完成）；截断标注的协议文本断言。

### M18：Memory 运行时（生命周期）

**为什么在 M15 后、与 M17 仅软依赖**：M15 交付的是静态文件层（SOUL/USER/AGENTS/MEMORY.md 的模板组装、加载与初始化，见 §三 M15），本里程碑给 MEMORY.md 建动态生命周期，这是硬依赖（边界：M15 的 MEMORY.md 只有加载+手动编辑，本里程碑加提取-准入-冲突，见 §六.6）。与 M17 之间只有软依赖——压缩机制会先把"什么值得留"的判断问题暴露清楚，先做 M17 能让准入规则设计得更有依据，但不构成技术阻塞（§四依赖图中两者可并行即源于此）。

**交付物**（对齐 Harness 方案 §五，做减法）：

1. 提取-准入环：从任务结果和用户纠正中提取候选记忆 → 去重/冲突检查 → 准入后写入 MEMORY.md（§5.5 注入时序的第 4 步）。提取的触发时机（自动收尾 vs 显式 `/remember`）是 §六.3 的开放问题，设计文档时裁决——本条只承诺"提取-准入环存在"，不预设触发方式。
2. 准入规则的核心裁决（§5.3）：**程序性记忆不入 Memory**——"做事方法"类候选被拒绝并提示"可沉淀为 Skill"（为 M19 铺路）。陈述性事实（用户偏好、项目约定、已确认决策）才可入。
3. 作用域两级：会话级（REPL 会话内跨 task 有效，不落盘；单 task 内的上下文本就有对话历史承载，不属记忆范畴）/ 项目级（MEMORY.md 落盘）。**砍掉**用户级以上作用域（§5.4 五级中只取两级——单机 CLI 无团队场景）。
4. 用户可控：查看（`/memory` 内嵌指令）、纠正（编辑文件即纠正——文件就是事实源）、临时停用（`--no-memory`）。
5. 冲突替换：新旧矛盾时新条目替换旧条目并在日志留痕（不做置信度算法，用"后写入者胜+可回看审计日志"的朴素语义）。
6. 威胁模型更新：记忆是跨任务持久注入面（低可信任务产出可经 MEMORY.md 影响后续所有任务，即记忆投毒），`docs/threat-model.md` 新增对应威胁条目与缓解（准入门 + 用户可见可纠正 + 停用开关）。

**明确不做**：向量检索/RAG、时间衰减与降权算法、置信度模型、团队/组织作用域；注入方式也做减法——不做 §5.5 的"按 query 激活候选 memory cards"式选择性召回，MEMORY.md 经 M15 的加载机制整体注入（文件本身被准入门控制在小体量，整体注入即够用；召回机制留给"记忆量证实超出整体注入承受力"之后）。这些是 Harness 方案为产品级系统设计的，ForgeAgent 的量级用文件+朴素规则先跑通闭环。

**验证**：准入规则表驱动单测（程序性候选必须被拒）；mock replay 断言第二个任务能利用第一个任务写入的记忆；golden 集扩展（记忆命中/不命中场景——离线判定为主，必要时归 opt-in 层，进设计文档裁决）。

### M19：Skills 运行时

**为什么在 M18 后**：M18 的准入裁决把程序性知识分流到这里；先有"Memory 拒收"，Skill 才有明确的内容来源和存在理由（§5.3 设计决策："经过验证的工作方法保存为 Skill——可版本化、可评审、可测试、可回滚、按需加载"）。

**交付物**：

1. SKILL.md 结构规范（对齐 §3.3）：name/trigger/steps/failure_branches/completion_criteria 五段，纯 markdown，放 `~/.forgeagent/skills/` 与项目 `.forgeagent/skills/` 两级目录（项目级优先）。
2. 渐进加载（§4.4）：系统提示词只注入 skill 名称+一行描述；模型判断适用后经工具读取全文。不把所有 skill 全文塞进上下文。
3. 匹配机制：v1 由模型自主判断（描述注入+按需读取），**不做**独立意图识别器。
4. Skill 的失败分支语义：steps 执行中命中 failure_branch 时按其声明停止/降级，进反馈环。
5. 威胁模型更新：项目级 `.forgeagent/skills/` 随仓库分发，等同不可信输入（克隆恶意仓库即被注入做事指令），`docs/threat-model.md` 新增对应威胁条目与缓解（复用 M15 为项目级身份文件确立的"首次加载摘要确认"模式，越权动作仍由 sandbox 档位兜底）。

**明确不做**：Plugin 打包分发、skill 市场、自动从历史归纳 skill（§5.3 指出自动学工作流缺稳定奖励信号，是积累偏见的路径）。

**验证**：golden 集新增 skill 注入场景（同一任务有/无 skill 的行为差异断言）；渐进加载的上下文体积断言（全文不在初始提示词中）。

### M20：Eval 体系 + 独立 Evaluator

**为什么在此**：hardening 变更交付的 golden manifest/runner/机器报告是本里程碑的地基；M17–M19 新增了三层能力，需要度量手段回答"Harness 改动是改进还是回退"（§6.4 Layer 5 迭代层：'评估对象是模型+Harness 组合，不是单独模型'）。

**交付物**：

1. 分层指标（对齐 §十一，取可落地子集）：first_pass_correctness（首轮完成率）、correction_rounds（修正轮数）、cache_hit_rate（M17 已产出）、golden 通过率趋势。全部从 golden runner 的机器报告和审计日志聚合，**不建独立评测服务**。
2. 独立 Evaluator（§七三角色架构的降级实现，**定位：opt-in 真实模型层，不进离线可信核心**）：离线核心的 20 项保持 hardening 变更确立的脚本确定性判定（无 key 可跑，这是 CI 门禁）；Evaluator agent 只用于 opt-in 真实模型验收——独立会话，不共享 Generator（被测 ForgeAgent 实例）的实现上下文，通过检查产物（文件内容/执行输出/状态断言）判定 pass/fail，fail 时附实际行为 vs 期望行为。**关键降级**：Harness 方案用 Playwright 操作 web 应用，ForgeAgent 的产物是文件与数据，Evaluator 相应地"执行/检查产物"而非操作浏览器——原则不变（通过外部可观察行为验证，不读实现），手段适配。
3. 完成标准防退化（§7.4）：golden manifest 禁止删条目或降标准——manifest 变更 diff 进入里程碑评审清单。
4. 真实模型评测保持 opt-in：延续 ACTION_PLAN §六.5 裁决，基础 CI 无 key 可跑——Evaluator（交付物 2）正因此被划入 opt-in 层，离线核心的判定不引入任何 LLM 依赖。

**明确不做**：Planner 角色（评测侧判定，golden 任务的规格由人写，不需要展开一句话需求；运行时侧的 Planner 属 M22 阶段二，是另一维度——见 M22 节与 §五）、Memory 层召回精确率标注集（无向量检索则无此指标）、Loop 稳定性指标（M21 后按需）。

**验证**：指标聚合脚本的表驱动单测（离线，进 CI）；Evaluator 对已知 fail 注入（故意做错的产物）的检出率 100%（opt-in，随真实模型层跑）。

### M21：Loop Engineering

**为什么在 M16–M20 后**：Loop 组合前序能力——trigger 走 M16 HTTP、长任务靠 M17 压缩、跨轮状态靠 M18 记忆与 durable artifacts、验证信号靠 M20 的指标聚合（CI 侧）与 Evaluator（opt-in 真实运行侧）、停止预算靠 M10 用量追踪。§八明确"Loop 依赖 Harness 提供的约束和验证机制"。（M22 在其后，见 M22 节的依赖说明。）

**交付物**（对齐 §8.2 必要组件，逐项落地或声明砍掉）：

1. Trigger：手动 CLI、HTTP API（M16）、本地 cron 示例文档。**不内置** scheduler 守护进程——被 cron/systemd/launchd 触发即可，符合轻量定位。
2. Checkpoint/resume：任务状态（进度文件：已完成条目/未解问题/下轮交接信息）+ 代码块落盘（既有）+ git 历史，中断后可续接（对齐 §6.3.2 Anthropic handoff protocol：进度文件 + Git 历史做交接）。
3. Stop conditions：max_rounds（既有，Step 轮次上限）+ token 预算上限（新增，基于 TokenUsage 累计）+ 墙钟超时（新增，任务级；现有超时仅在执行器的单代码块粒度）+ 连续失败次数上限（新增），任一命中即停止并留下可诊断报告（§8.4 步骤 6 的语义）。
4. 失败反馈环收敛：限定轮数内修正，仍失败则停止——绝不无限重试。
5. Loop 示例：一个端到端参考实现（如"定时检查项目依赖更新并产出报告"，§8.4 的简化版，只到报告不到 PR）。

**明确不做**：worktree 自动隔离（用户手动指定工作目录即可）、多 Agent teams 协作、Ralph Loop（hook 拦截提前结束）——§8.5 提醒 Loop 不自动产生正确目标，轻量工具不该营造全自动错觉。

**验证**：checkpoint 中断-恢复端到端测试（kill 后 resume，断言不重做已完成条目）；每种 stop condition 的触发断言；token 预算的边界单测。

### M22：运行时三角色协作（Triad Mode）

**定位与 M20 的区分**：这是 Harness 方案 §七对抗验证架构（Planner/Generator/Evaluator）在**运行时执行环路**的落地——用户执行任何一个任务时，任务内部按角色分工协作。与 M20 是同一思想的两个维度：M20 用 Evaluator 度量"ForgeAgent 好不好"（评测侧，golden 规格由人写、Planner 不做的判定仍然成立）；M22 用三角色回答"这个任务怎么做对"（运行时侧，规格在任务开始时不存在，Planner 有真实职责）。

**为什么最后**：M22 组合的前序能力最多——M15 的提示词模板组合器（三角色的差异化系统提示词=三套模板组合，机制 M15 已建，角色模板内容是 M22 增量）、M17 上下文隔离与压缩、M20 的 Evaluator 实现（验收逻辑与报告格式两侧共享）、M21 的进度文件/checkpoint（角色交接与 Triad 清单的落盘载体）。Generator 无需新建：被测执行环路本身就是 Generator，其"逐块执行/自检反馈/版本化落盘"自 M3 起已具备。

**为什么成立（针对本项目的实证依据，非泛泛引用）**：

- "自我评估不可靠"在本项目有在案发作：完成语义是模型自己发 `completed: true`，hardening 变更修掉了其中的流程性缺陷（完成声明未检查同轮工具反馈），但修完之后完成判定**仍是 Generator 的自我评估**——只是时机对了，评估者没变。运行时 Evaluator 补上结构性的另一半：完成由独立会话验收，不由执行者自我声明。
- Evaluator 的验证手段在 code-as-action 范式里是天然的：验收=写 Python 检查产物（文件断言/重算对账/执行输出核查），验证本身也是 code-as-action，复用现有 Task/Step/executor 全套，无需 Playwright 类新机制——这是相对原架构的实现成本优势。
- 三角色独立上下文即 Harness 方案 §4.1 的"隔离"动作：规格文档是唯一跨角色契约，长任务上下文压力被结构性分摊。

**分两阶段交付（用户裁决，2026-07-16）**：

**阶段一：Generator + Evaluator 二角色（Duo）**
1. 现有执行环路（=Generator）跑完后，独立 Evaluator 会话验收：不共享 Generator 实现上下文，只拿到任务目标+产物访问权；验收方式=写代码检查产物；不通过则带证据（实际 vs 期望 + 定位信息）打回 Generator，限定打回轮数（可配置，默认 2），超限停止并输出逐项验收报告。
2. Evaluator 可配独立模型（如 haiku 验收 sonnet 的产出，靠既有多模型支持零成本实现）与独立 sandbox 档位（验收代码默认 restricted，即使 Generator 跑 trusted）。Evaluator 会话不挂载 gated tools 之外的写路径——验收是读+算，产物修改只能发生在 Generator 侧。
3. 完成语义变更：Duo/Triad 模式下 `completed` 以 Evaluator 判定为准，Generator 的自我声明降级为"提交验收"信号。单角色模式的完成语义完全不变（hardening 后的现状），`TaskStatus`/`TaskOutcome` 对外形状保持兼容，新增字段只做加法。

**阶段二：+ Planner 成三角色（Triad）**
4. Planner 前置：把用户任务展开为逐条可验证的功能清单（每条=可观察行为+验收标准，只定 WHAT 不定 HOW），清单**禁删条目、禁降标准**（§7.4，防"接近上下文上限时偷偷降低完成标准"）；清单作为跨角色契约落盘（复用 M21 进度文件形态）。
5. Generator 逐条实现（一次一条），Evaluator 逐条核查 Planner 清单，全部 pass 才算完成。
6. Planner 输出需用户确认后才进 Generator（清单是完成标准的事实源，人必须过目——对齐 Harness 方案 §8.5"Loop 不会自动产生可信的验收标准"）；headless 路径（HTTP/cron 触发）无人可确认时，Triad 的 Planner 确认门语义（拒绝 vs 预授权跳过确认）复用 M16 确立的 headless 确认门模式，细节进设计文档。

**启用规则（用户裁决，2026-07-16）**：
- 内嵌指令显式唤起：`/duo <任务>` 启用二角色，`/triad <任务>` 启用三角色；单次命令对应 `--mode duo|triad`。
- **编程类任务强制 Triad**：用户直接指定的编程类任务（写程序/改代码/建项目等产物为代码的任务）必须走三角色，不允许单角色直通。编程类的识别机制是 §六.8 的开放问题（关键词规则 vs 轻量分类判断 vs 用户标记，进设计文档裁决）；识别为编程类但用户显式要求单角色时的优先级同入 §六.8。**阶段衔接**：该强制规则随阶段二生效；阶段一（仅 Duo 可用）期间，编程类任务先强制 Duo 作为过渡语义，阶段二交付时升为强制 Triad。
- 其余任务默认单角色直通（现状路径零变化）——三角色是 3 倍+调用成本与延迟，简单任务走 Triad 是纯浪费，分级启用是前提而非优化。

**明确不做**：自动复杂度判断作为唯一路由（意图识别 §五已裁决不做；编程类强制是规则触发，不是通用意图路由）、引入 Claude Agent SDK 或任何编排框架（三角色=三个 Task 会话的顺序编排，复用现有抽象）、角色并行执行（v1 严格串行：Planner → 确认 → Generator ⇄ Evaluator）、Evaluator 反馈直达 Planner 改规格（规格确认后冻结，改规格=回到用户）。

**验证**：Duo 打回环 mock replay（Evaluator 拒绝 → Generator 修复 → 通过的完整回放，离线）；"Generator 声明完成但产物错误"必须被 Evaluator 拦截的对抗用例（mock replay 可离线覆盖判定流转，Evaluator 真实判别力的抽查归 opt-in 层）；Triad 清单禁删改的守卫单测；编程类强制路由的表驱动测试；golden 扩展（同一编程任务单角色 vs Triad 的完成质量对比组，涉及真实模型行为差异，归 opt-in 层）。

**门禁**：设计文档用户评审（含 §六.8 识别机制裁决；§六.9 交付粒度裁决）+ 三轮评审。

## 四、依赖关系图

```
hardening-core-correctness（已完成，= M13）──┬─→ M16 HTTP+审计（confirmer 统一是 headless 语义前提）
                                            └─→ M20 Eval（golden runner/manifest 是地基）
M15 身份文件层（§三已细化）──→ M18 Memory 生命周期 ──→ M19 Skills（准入分流铺路）
M15 ──→ M22（提示词模板组合器，角色模板是 M22 增量）
M16 ──→ M21（trigger）        M17 Context ──→ M21（长任务前提）、M22（隔离与压缩）
M20 ──→ M21（验证信号）、M22（Evaluator 实现共享）
M10 用量（已完成）──→ M21（token 预算 stop）
M21 ──→ M22（checkpoint/handoff 是角色交接载体）
```

串行主线：M13（已完成）→ M15 → M16 → M17 → M18 → M19 → M20 → M21 → M22。
其中 M17 与 M18 若资源允许可并行（无硬依赖，仅"值得留什么"的经验软依赖）；M22 阶段一（Duo）不依赖 M21 的 trigger/stop 全套，其验收报告的落盘形态与 M21 进度文件同源——按主线顺序做时 Duo 复用 M21 已定的形态，若 Duo 需求提前变急、经用户确认可在 M20 后先行插做（此时 Duo 先定该形态、M21 反向复用）；其余不建议并行。

## 五、明确不做/降级总清单（保持轻量的边界）

Harness 方案是为 WorkBuddy 这类产品级系统写的；ForgeAgent 是轻量 CLI agent，以下内容**整体不做**，避免 harness 长成第二个项目（ACTION_PLAN §一的原则延续）：

| Harness 方案内容 | 判定 | 理由 |
|---|---|---|
| 意图识别前置环节（§4.4） | 不做 | 单一 code-as-action 范式无多路由需求；模型自主判断足够 |
| 多模型按任务路由/Model Router（§十） | 不做 | 用户显式选模型（`/model`）符合 CLI 心智；自动路由增加不可预测性 |
| Memory 置信度/时间衰减/五级作用域（§5.4–5.6） | 降级 | 两级作用域+文件事实源+后写者胜；算法留给需求证实之后 |
| Planner 角色（§7.2） | 评测侧不做；运行时侧进 M22 阶段二 | 评测侧：golden 规格由人写，无"需求展开"环节。运行时侧：任务规格在开始时不存在，Planner 有真实职责——同一角色两个维度判定不同 |
| Playwright 端到端验收（§7.3） | 手段替换 | 产物是文件/数据，Evaluator 检查产物行为，原则（独立+外部可观察）不变 |
| MCP Apps 交互式 UI（§3.2） | 不做 | CLI 无 UI 渲染面 |
| Plugin 打包分发（§3.4） | 不做 | 无分发场景；Skill 目录已是最小组合单位 |
| 团队/组织级记忆与审批（§5.4） | 不做 | 单机单用户 |
| 内置 scheduler 守护进程 | 不做 | 交给 OS 级 cron/launchd；ForgeAgent 提供可被触发的入口 |
| 压缩信息损失度量、Memory 召回标注集（§1.2/§十一） | 不做 | 业界未解或依赖未建设施，不在轻量项目首创 |

## 六、开放问题（进各里程碑设计文档时裁决）

1. **M16 选型**：fastapi（生态成熟，违背"首版不引入"旧裁决——但 M16 已非首版）vs stdlib 手写（零依赖，鉴权/并发全手工）vs `uvicorn`+ASGI 手写（折中）。倾向：设计文档中给三方案对比表，用户裁决。
2. **M16 审计日志的保留策略**：无限增长 vs 按大小轮转。倾向：简单按大小轮转，可配置。
3. **M18 记忆提取的触发时机**：每任务收尾自动 vs 用户显式 `/remember`。倾向：显式为主+收尾提示候选，避免静默写入用户不知情的内容。
4. **M21 token 预算的默认值**：无默认（必须显式配置才启用）vs 保守默认。倾向：Loop 场景强制显式配置，交互场景不设。（若 M22 提前插做，Duo 打回环的轮数上限即其停止预算，独立于本条。）
5. **M9 遗留项的插入时机**：native tool_calls 流式拼装、音频/视频输入等（`docs/m9-streaming-multimodal-commands.md` §九登记在案）。判定：均为需求驱动，不占用 M16–M22 编号，出现真实需求时插单。
6. **M15↔M18 的边界**：ACTION_PLAN 原 M11 行（重编号后为 M15）写 MEMORY.md"需要支持记忆提取和更新"，本文 §三 M15 的细化方案把边界定为——M15 做加载+手动编辑（编辑即更新），提取-准入-冲突等生命周期机制归 M18。该划分随 M15 设计文档一并交用户裁决确认；若用户裁决 M15 就含提取机制，则 M18 相应缩窄为准入规则、作用域与威胁模型部分。
7. **M15 身份文件的注入是否计入稳定前缀**：SOUL/USER 低频变、利于 prompt-cache；但 MEMORY.md 随任务更新，若排在系统提示词内会破坏前缀稳定性（Harness 方案 §4.3）。倾向：SOUL/协议/USER/AGENTS 进系统提示词，MEMORY 段的注入位置（系统提示词尾段 vs 首条 user 消息前的独立段）在 M15 设计文档里对照 cache 语义裁决——该裁决也影响 M17 的排序审计基线。
8. **M22 编程类任务的识别机制**："直接指定编程类任务强制 Triad"（用户裁决）需要识别规则：关键词/产物类型规则表（确定性、可测，但有漏判）vs 轻量模型预判（覆盖广，但引入额外调用且与"不做意图识别"的 §五裁决需划清边界）vs 任务提交时用户标记（零误判，但依赖用户自觉）。连带子问题：识别为编程类但用户显式要求单角色时，强制规则与用户意愿的优先级。倾向：规则表起步+用户标记兜底，优先级冲突时提示确认，进 M22 设计文档裁决。
9. **M22 阶段一/二的交付粒度**：Duo 与 Triad 是一个里程碑内两阶段，还是拆成 M22a/M22b 两个独立门禁的里程碑。倾向：一个里程碑、两阶段各自有验收点，设计文档时按工作量实测裁决。

## 七、与既有约束的一致性声明

- 不硬编码厂商端点/API key（全程延续）；M16 的 bearer token 走配置。
- golden 集两层结构延续 hardening 变更的确立：目录（`docs/golden-tasks-seed.md`，配比 40/25/20/10/5% 在扩展时精确维持）+ 离线可信核心 manifest（脚本确定性判定、无 key 可跑、禁删条目/降标准）。各里程碑扩展 golden 时优先充实可信核心，目录条目按需渐进工程化，不一次性全量。
- 基础测试无 key 可跑；真实模型验证 opt-in（ACTION_PLAN §六.5）。M20 的 Evaluator 属 opt-in 层，不改变这一边界。
- 安全敏感里程碑（M15 项目级身份文件、M16 HTTP 监听面、M18 记忆写入面、M19 skill 加载面）同步更新 `docs/threat-model.md`（延续 M7–M10 惯例，威胁编号续排）。
- 编码型子任务派发低算力 subagent（spec.md 算力分配原则），模板 `docs/subagent-task-template.md`。
- 每里程碑收尾按 `MILESTONE_GUIDE.md` 产出 milestone 文件并更新 `milestones/latest`。
