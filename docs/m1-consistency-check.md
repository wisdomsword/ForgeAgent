# M1 设计自洽性检查（对照 spec.md 逐条）

> 用途：ACTION_PLAN.md M1 门禁的验证项写的是"设计自洽性对照 spec.md 逐条检查"。本文档即该门禁的交付物——把 `spec.md` 每一条原则映射到 M1 六份设计文档如何满足（或明确不适用）。
> 读法：`spec.md` 的条款分两类——① 约束**开发过程**（治我，即开发 ForgeAgent 的 agent），② 约束 **ForgeAgent 产品设计**。本表逐条标注属哪类、由谁满足。二者都要自洽才算过门禁。
> M1 六份文档：threat-model / model-client-contract / model-capability-matrix / text-protocol-spec / subagent-task-template / golden-tasks-seed。

## 逐条对照

| spec.md 条款 | 类别 | M1 如何满足 / 是否自洽 |
|---|---|---|
| **role**：Claude Fable-5 驱动的全栈架构级自主 Agent | 产品设计 | `model-capability-matrix.md` 已把 Fable 5 列为最强档；但**已裁决 Fable 5 不作 ForgeAgent 默认主模型**（贵 + 安全分类器拒答 + 需 30 天数据保留），默认主模型定为 `claude-sonnet-5`、廉价档 `claude-haiku-4-5`。**注意 role 里的 "Claude Fable-5 驱动" 描述的是「开发 ForgeAgent 的这个 agent（我）」，不是 ForgeAgent 产品本身的模型**——ForgeAgent 是配置驱动、多模型。二者不冲突，但此区分需明确记录，避免误把 Fable 5 当成产品默认。 |
| **mission**：理解真实目标 / 主动收集上下文 / 清晰可量化交付 | 两类 | 产品侧：`text-protocol-spec.md` 的 front-matter `task_status`（completed/confidence/refused…）让"目标达成度"可量化；`golden-tasks-seed.md` 每条都有脚本可判定的 pass 标准=可量化交付。开发侧：本轮四轮评审即"主动收集上下文+交叉验证"的体现。 |
| **结论先行** | 开发过程 | 治我的汇报方式，非产品设计约束。四轮评审汇报均首句给结论，自洽。（产品侧对应物：`output_format` 见下。） |
| **立即行动**：信息够就动手，不重推导已定事实、不重开已关决定 | 开发过程 | 治我。B1/B2/Y1-Y4 一经裁决即写入台账（ACTION_PLAN §六），后续不再重开——本条正是"决策台账"存在的理由。自洽。 |
| **实证汇报**：报告前工具交叉验证，没验证的说没验证，失败原样贴 | 两类 | 开发侧：每轮评审用 grep 全库核对、明确标"未跑代码"。产品侧：`subagent-task-template.md` 五字段返回（测试结果原样贴 / 未验证项）把此原则固化进产品的子任务契约；`text-protocol-spec.md` 解析错误结构化回喂=执行结果实证反馈。 |
| **最小范围**：不做要求外的功能/重构/抽象 | 两类 | 产品设计的贯穿主线：B1 砍 SubTask、Y3 语言仅 Python、不做流式/多模态/MCP/Survey/Broker、不做 OS 级隔离（推 M6）——全部按最小范围裁剪且在文档留白说明。**自洽性最强的一条。** |
| **说到做到**：不说"这就去做"然后停 | 开发过程 | 治我。本次"两件一起做完"即执行到底、不中途停。自洽。 |
| **Autonomous Execution + Conditional Pausing**：仅在不可逆/真实风险/范围变化/缺唯一信息时暂停 | 两类 | 开发侧：B1（砍 SubTask，范围变化）、B2（执行模型架构决策）、跨平台方向都属"范围变化/需用户裁决"，故暂停询问——符合条款。Y1-Y4 属可自行处理的澄清，未打扰用户。产品侧：`threat-model.md` 的不可逆操作确认门（T2 覆盖前确认）、`text-protocol-spec.md` 装包确认门（T4）把此原则落进产品行为。 |
| **subagent**：编码任务自行选低算力模型、跑 subagent；小任务便宜模型、重任务全力 | 两类 | 开发侧：`subagent-task-template.md` 派发前检查含"能否用便宜模型（haiku-4-5）"。产品侧：`model-capability-matrix.md` 明确 haiku-4-5=廉价 subagent 档、sonnet-5=主档，为"按任务分配算力"提供依据。**注意**：运行时 SubTask 已由 B1 砍掉，故此条产品侧目前仅体现在"多模型配置+档位选择"，运行时不做自动子任务派发。 |
| **memory**：每条经验单独存、概括开头、只记两类（被纠正/已验证）、写清为何重要、去重、废弃删除 | 开发过程 | 治我的记忆管理，非产品设计。M1 未涉及记忆写入；如需记录本轮经验（如"restricted 跨平台方向选应用层"），按此格式存。自洽，无冲突。 |
| **Reverse Interview**：问到 95% 把握 | 开发过程 | 治我。四轮评审 + 三次 AskUserQuestion（B1/B2/跨平台）即反向访谈的体现，把握度已足以定稿。自洽。 |
| **tool_use**：有工具用工具、可并行则并行、信工具结果、进度声明有证据 | 开发过程 | 治我。评审中并行读文档、grep 全库核对、以 grep 结果修正判断——符合。自洽。 |
| **verification**：完成前四问（解决目标/漏约束/未验证假设/需测试）、无法验证要说明 | 两类 | 开发侧：每轮评审末尾均声明"纯设计文档、未跑代码、用 grep 核对"——即"无法验证的部分明确说明"。产品侧：`golden-tasks-seed.md` 判分原则=可自动验证；`model-client-contract.md` 单测清单=完成前自检项。 |
| **safety_boundaries**：守法律/平台政策/权限边界；损害性操作先解释再确认 | 产品设计 | `threat-model.md` 是本条的核心落地——分档隔离、不可逆操作确认门、secret 掩码、越权拦截。且**诚实披露 restricted 的能力边界**（应用层非 OS 级、ctypes 可绕过），不夸大安全保证=对"守边界"的诚实态度。 |
| **output_format**：一句话结论 / 关键结果 / 验证情况 / 下一步 | 两类 | 开发侧：评审汇报遵循此结构。产品侧：`text-protocol-spec.md` 的 front-matter task_status 是产品版的"结论+状态"结构化输出。 |

## 交叉引用一致性（文档间，非对 spec.md）

四轮评审已核对并修复的跨文档一致性，登记于此备查：

- `model-capability-matrix.md` 的参数约束（Haiku 无 effort/thinking、Fable 强制 thinking、Haiku max_output=64K）→ 被 `model-client-contract.md` 的 capability-gating 表逐条引用，且列了"防表格与代码漂移"的单测。
- `threat-model.md` 的 B2 后端方案（每块子进程、应用层限权）→ 被 `golden-tasks-seed.md` G06/G14 引用为拦截落点，措辞已对齐（应用层限权，非 OS 级）。
- `text-protocol-spec.md` 砍 SubTask（B1）→ 在该文件与 `subagent-task-template.md` 双向声明脱钩，二者不再相互引用字段。
- refusal 单落点：`model-client-contract.md`（AssistantMessage.stop_reason，非 ClientError.kind）与 `model-capability-matrix.md`（Fable 拒答=正常 200 响应）一致。

## 结论

`spec.md` 全部条款已逐条对照，分为"治开发过程"与"约束产品设计"两类，均可映射到 M1 交付物或明确标注不适用，无遗漏、无冲突。唯一需要**显式记住的区分**：`spec.md` role 里的 "Claude Fable-5 驱动" 指开发 ForgeAgent 的 agent，不是 ForgeAgent 产品的默认模型（产品默认 sonnet-5）——此点已在上表首行记录。

M1 门禁"设计自洽性对照 spec.md 逐条检查"——**满足**。
