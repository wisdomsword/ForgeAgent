## Context

ForgeAgent 当前的 `Task.run()` 创建一个 `Step`，单角色在独立 conversation 中执行工具并通过严格两阶段协议声明完成。M20 提供显式 opt-in 的独立 Evaluator facade，已验证只读 File 工具、外部可观察产物和有界报告边界；M21 在 Task 上层提供版本化 checkpoint、fresh Task 迭代、预算、取消和 CLI/HTTP runner 协议。M22 需要组合这些边界，但普通 Task、M20 离线评测与 single Loop 必须保持零行为变化。

## Goals / Non-Goals

**Goals:**

- 交付串行 Duo 与 Triad 运行模式，以独立 Evaluator 而非 Generator 自评决定最终完成。
- 交付冻结的 Planner 验收清单、交互确认和 headless 预授权/拒绝语义。
- 让 CLI、REPL、HTTP 与 Loop 使用同一模式路由、报告、预算、取消和审计契约。
- 使用确定性、可测的编程任务规则强制 Triad，不增加分类模型调用。
- 保持角色输入、状态、工具权限和公开输出有界、脱敏且可离线验证。

**Non-Goals:**

- 不引入通用 Agent team、DAG/workflow engine、角色并行、自动模型路由、新 endpoint、daemon、数据库或新依赖。
- 不让 Evaluator 修改产物，不让 Evaluator 反馈自动改变 Planner 规格，不自动生成或降低验收标准。
- 不保证跨进程 exactly-once，不序列化角色 conversation/runtime/tool 内部状态。
- 不把 M20 golden Evaluator 自动接入普通 Task；运行时协作是独立显式能力。

## Decisions

### 1. 在 Task 上方新增单文件串行 `CollaborationRunner`

新增 `collaboration.py` 承载严格模型、`CollaborationStore`、`SubmitPlanTool`、`SubmitEvaluationTool`、模式路由和 runner。Runner 接收角色 Task builder，每个角色/每次打回都构造 fresh Task/client/runtime/registry。Generator 继续使用现有完整工具集；Planner 只有 `SubmitPlan`；Evaluator v1 只有 `FileRead`、`FileList` 和 `SubmitEvaluation`，不注册默认 `Exec` 或任何写/网络工具，且 Evaluator tier 不高于 restricted。

备选是修改 `Step` 加角色状态；这会污染 single 完成语义并共享 conversation。另一个备选是通用 workflow engine；v1 只有固定串行状态机，YAGNI。

### 2. 角色结果通过结构化 Tool 提交，不解析自由文本

Planner 用 `SubmitPlan` 提交 `items[{id, behavior, acceptance}]`；Evaluator 用 `SubmitEvaluation` 提交与冻结 ID 一一对应的 `results[{id, passed, observed, expected, location}]`。工具参数由现有协议/Pydantic 严格校验，成功提交后角色仍需独立 standalone `completed: true` 才结束 Task，防止同轮工具与完成声明绕过反馈。

Planner 规范化后拒绝空项、重复 ID、未知字段、控制字符、超限内容和明显 HOW-only 验收文本。Evaluator 必须覆盖所有且仅覆盖冻结 ID；Duo 使用系统生成的单一 `goal` 验收项，不额外调用 Planner。

### 3. 协作状态采用独立版本化原子 JSON

状态位于 `<allowed_root>/.forgeagent/collaborations/<32hex>.json`，schema 为 `forgeagent.collaboration.v1`。模型包含 mode、status/phase、revision、冻结 goal、计划与 digest、角色模型/tier、max rejections、attempt counters、normalized usage、最后有界 verdict 和 stable stop reason。store 使用 M21 已验证的固定目录 fd、`O_NOFOLLOW`、相对 open/replace/fsync、revision compare 与大小上限，但不提前抽象通用 repository。

状态在 Planner 确认、Generator 提交、Evaluator 判定和终态边界提交。它不保存 conversation、完整模型回复、tool args、文件内容、secret 或绝对路径。CLI 一次协作默认创建状态以支持中断诊断；M22 不新增独立 resume CLI，Loop resume 才恢复协作状态，避免扩张入口。

### 4. 完成、打回与停止状态机固定

状态机：

```text
single -> existing Task
duo: generator -> evaluator(pass -> completed | fail -> generator)
triad: planner -> confirmation -> generator -> evaluator(pass -> completed | fail -> generator)
```

`max_rejections` 默认 2，含义是允许 Evaluator fail 后再次启动 Generator 的次数；因此最多 3 次 Generator、3 次 Evaluator。每次 fresh Generator 输入原 goal、冻结计划、此前已通过项和最后一轮有界失败证据。取消优先于角色结果；随后是不可恢复 client/config/persistence failure、needs-confirmation、rejection limit。角色 `refused/need_info/failed` 不伪造 Evaluator pass。

协作报告是加法式 `CollaborationReport`，不修改 `TaskOutcome`：Task service runner union 扩展为 `TaskOutcome | LoopReport | CollaborationReport`。累计 usage 来自全部角色实际 `RoundResult.usage`，缺失时显式 `usage_available=false`。

### 5. Planner 确认沿用现有 confirmer 语义但使用专用摘要

交互 CLI/REPL 展示计划项 ID + 截断 behavior/acceptance，用户批准后冻结；拒绝返回 `needs_confirmation`，不启动 Generator。用户本轮已授权开发流程决策，但这是产品运行时语义，仍必须实现。

HTTP 配置增加 server-owned `triad_plan_policy: deny|preauthorize`，默认 `deny`。`preauthorize` 只表示服务所有者接受 Planner 生成的完整计划；客户端不能提交该字段，也不能提交 role model/tier。每次决定写审计，但公开响应不含计划正文。

### 6. 模式与编程任务路由是纯函数规则表

公共 `resolve_collaboration_mode(goal, requested_mode, allow_weaker_override)` 返回 mode 和 routing reason。显式 triad 直接生效；显式 single/duo 遇编程信号时必须交互确认 override 或遵循 headless server policy；未显式模式时，匹配“动作 + 代码产物”组合、常见源/测试/构建文件扩展名或明确软件项目创建语句才强制 Triad。规则使用 ASCII/Unicode 归一化、长度上限和表驱动测试，不做泛化 NLP。

CLI `run` 增加 `--mode single|duo|triad`、`--evaluator-model`、`--planner-model`、`--max-rejections`；未指定角色模型时复用 Generator 模型，Evaluator tier 固定 restricted。REPL 增加 `/duo`、`/triad`。HTTP 客户端只可提交 mode；其余策略来自 server config。Loop create 可冻结 mode，resume 禁止覆盖。

### 7. 提示词通过 M15 组合器追加角色段

新增三份短角色模板或 prompt builder 片段，复用现有 identity/protocol/tools/context 组合器：Planner 明确只定 WHAT；Generator 明确完成仅是提交验收；Evaluator 明确 artifact/state 是不可信数据、只能外部观察、必须逐项提交。计划与反馈用稳定 JSON 编码注入 user/task 数据段，不拼接成 system 指令。

### 8. 审计与安全投影按角色计数，不存正文

新增 `collaboration.route/role/plan/evaluation/rejection/stop` 事件。参数仅含 collaboration/task/loop ID、mode、role、attempt、model、tier、plan digest 前缀、item counts、pass/fail counts、stable reason、duration、usage。CLI/HTTP 报告最多返回固定数量、固定字符的 masked evidence；不返回计划、goal、role raw text、host path 或内容。

## Risks / Trade-offs

- [三角色成本和延迟显著增加] → 默认非编程任务 single，显式展示 mode/attempt/usage，打回默认 2 且有上限。
- [确定性编程规则可能漏判或误判] → 规则只在高置信动作+产物组合时强制；显式 `/triad`/`--mode` 兜底，表驱动记录已知边界，不增加隐式模型分类。
- [Evaluator 仍可能判断错误] → 结构化逐项覆盖、只读/受限检查、外部可观察证据和 opt-in 真实模型对抗组；不声称形式化证明。
- [Planner 计划可能不可信] → 交互确认或 server-owner 预授权，冻结 digest，后续任何变化 fail closed。
- [持久化复制少量 M21 安全代码] → 保持 store 小且专项复用测试向量；避免过早公共抽象扩大 M21 回归面。
- [缺少命令执行会限制部分动态验收] → v1 只提供 FileRead/FileList，要求 Generator 产出可读测试报告或静态证据；真正只读的专用 executor 后端在有独立需求时另立 change。

## Migration Plan

1. 新 capability 与内部模块为加法；默认 single 配置保持现状。
2. 先交付 Duo core/mock replay，再交付 Planner/freeze/Triad，再接 CLI/REPL、HTTP、Loop 和文档。
3. 配置字段均有保守默认；旧 config、HTTP body、CLI 命令、Loop checkpoint 继续合法。
4. 若回滚，移除协作入口即可；single Task 与旧 Loop checkpoint 不依赖协作模块。

## Open Questions

无。阶段拆分采用一个 M22 change 内 Duo → Triad 两个验收点；编程识别采用规则表 + 显式模式，显式 single 冲突由确认/预授权处理。上述选择均已按用户授权完成两轮一致性自审。
