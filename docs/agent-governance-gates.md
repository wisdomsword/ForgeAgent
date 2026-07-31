# Agent 治理门禁

> 本文是 ForgeAgent 开发期 Prompt/Skill、Memory 和 Rewrite/依赖评审的 canonical 入口。它不是运行时 schema，不会自动修改既有 Skill、Memory 或 Prompt，也不授予发布权限。

## 1. Prompt / Skill Exit Contract

每条新增或实质修改的长期 Prompt/Skill 指令都必须填写五类退出条件，并附带模型版本、`minimum_regression_set` 和 `retire_stale_scaffolding` 记录。每一行都要有可观察的 `condition` 和负责观察它的 `verifier`；“全部正确”“永不失败”等 `unbounded` 绝对表述不能作为唯一验收条件。

| exit class | condition | verifier |
| --- | --- | --- |
| `success` | 任务产物和成功提交/完成证据满足什么有界条件 | 哪个测试、检查或宿主状态观察它 |
| `failure` | 哪个可识别失败导致停止，以及公开原因 | 哪个错误、verdict 或失败测试观察它 |
| `blocked` | 哪个权限、资源、外部依赖或未知副作用阻止继续 | 哪个状态、审计或人工检查观察它 |
| `needs-input` | 缺少哪项用户输入、确认或决策 | 哪个输入字段或确认事件观察它 |
| `timeout-or-budget` | 哪个 wall-clock、token、round 或外部 deadline 到达 | 哪个 budget/stop reason 观察它 |

最小验收：五行齐全，条件可在当前项目测试或宿主状态中观察，且失败、阻塞、需输入不被混写为成功。边界反例：只有“继续直到完成”而没有 verifier 的指令不得进入实现；已有旧 Skill 不因本门禁自动迁移，只有新增或实质修改时补齐。

模型升级时必须保留可运行的最小回归集，并删除或记录不再需要的过时 scaffolding；未提供模型版本、回归样本或清理说明的 Prompt/Skill 变更只能停留在探索阶段。

## 2. Memory Governance Review

写入或修改长期 project Memory 前，设计/问题卡必须回答四个核心问题：谁可写、什么是真相、何时失效、崩溃后从哪份恢复；同时补充为什么记、谁可见以及如何删除/更正。

| field | 必答内容 |
| --- | --- |
| `why_remember` | 为什么值得跨任务保留，避免把一次性上下文写成长记忆 |
| `who_can_write` | 哪个用户、宿主或受控流程可以写入、替换或批准该记忆 |
| `truth_source` | 什么来源是权威真相（用户、工具、文件或系统状态），如何处理模型推测 |
| `expires_or_revalidate` | 何时失效、多久复核或发生什么变化时必须重新确认 |
| `visibility_and_recovery` | 谁可见，以及进程崩溃/重启后哪一份受信副本恢复 |
| `delete_or_correct` | 用户如何删除、更正或替换错误内容 |

Session-only Memory 可以用当前会话边界回答可见性与恢复，但仍必须写出谁可写、来源和更正行为。若已到 expiry 或 revalidation 条件，内容不得继续被静默当作权威事实；应进入复核、删除或更正路径。既有 `.forgeagent/MEMORY.md` 不在本 change 中迁移或补写元数据。

## 3. Rewrite / Dependency Gate

大规模重写、执行后端替换、语言层替换或跨模块运行时依赖引入，必须先填写六项指标。每项都要有 `baseline`、`threshold`、`evidence`、`migration` 和 `rollback trigger`；缺任何一项只能作为探索，不能进入已批准的实施。

| metric | baseline | threshold | evidence | migration | rollback trigger |
| --- | --- | --- | --- | --- | --- |
| `performance` | 当前延迟、吞吐或 token 成本 | 可接受的改善/上限 | 基准脚本与原始结果 | 分阶段切换方法 | 回退到旧路径的条件 |
| `reliability` | 当前失败率、恢复率或数据完整性 | 允许的失败/恢复边界 | 回归、故障或恢复测试 | 双跑/灰度策略 | 何种故障立即回退 |
| `maintenance cost` | 当前代码、依赖和运维负担 | 可接受的复杂度变化 | 代码规模、维护工时或依赖清单 | 培训/文档/所有权安排 | 无法维护时的退出条件 |
| `compatibility` | 旧 API、协议、数据和平台矩阵 | 保持/放宽的兼容范围 | 兼容回归与平台证据 | 迁移/兼容期 | 旧客户端或数据失败时如何退回 |
| `team capability` | 当前团队掌握的语言、工具和排障能力 | 明确的能力缺口关闭条件 | 试作、演练或负责人确认 | 交接与培训步骤 | 能力不足时暂停/回退 |
| `migration/rollback risk` | 数据、状态、发布和回滚复杂度 | 可接受的风险上限 | 演练、备份和恢复证据 | 可逆迁移步骤 | 触发回滚和保留旧路径的条件 |

Rewrite 不得只以模型质量、技术新颖性或未测量的架构偏好作为理由；本门禁不设跨模块的统一数值阈值，阈值必须与具体基线和证据绑定。

## 4. Verifier 与分发边界

- 文档契约测试必须在离线环境运行，只读取项目内文件，不访问网络、不读取凭据、不执行发布命令。
- 本门禁不改变 `SkillDefinition`、`MemoryCandidate`、Prompt 模板或任何运行时持久化行为。
- 包索引发布、正式 tag、面向分发的远程 push 和发布自动化已从当前路线图移除；不保留 active 发布 change，也不提供恢复路径。经用户明确授权的普通开发分支 push 只用于版本控制交接，不构成分发或发布授权。
- 运行时 Skill 自动拒绝已由 `runtime-skill-exit-contract` change 落地：仅显式 `format_version: 2` 进入五类退出契约校验；旧 Skill 保持 legacy 兼容，项目有效摘要继续绑定退出条件。
