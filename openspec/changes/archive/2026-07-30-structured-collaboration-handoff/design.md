# 结构化协作交接设计

## Context

Duo/Triad 的持久 state 已经是恢复事实源：goal、plan/plan_digest、last_evaluation、phase、attempt、revision、usage 和 stop reason 均经过严格验证。当前 `_role_task_data()` 只拼接部分字段，且不同角色收到的上下文边界依赖调用方；这使交接语义难以审计，也没有统一表示副作用未决、能力/审批和返回责任。

## Goals / Non-Goals

### Goals

- 定义单一 `HandoffPacket`，由持久 state、当前角色和宿主能力确定性生成。
- 覆盖目标/范围、已验证事实、假设、未决副作用、能力/审批、checkpoint、停止条件和返回责任。
- 对传入 role task 的内容做严格结构化、固定上限和 secret/path masking；包可从 resume state 重建。
- 记录稳定 handoff digest，支持事实和风险追溯，不泄露正文或凭据。

### Non-Goals

- 不把模型自由摘要写入持久 state，不信任模型自报事实、权限或副作用状态。
- 不转移线程/会话控制权，不新增 scheduler、lease、消息总线、远程 Agent 或自动恢复。
- 不改变现有 SubmitCandidate/SubmitEvaluation、receipt 决策、停止原因或报告字段。

## Decisions

### 1. Packet 是投影，不是新事实源

`HandoffPacket` 使用严格 Pydantic 模型，字段均为有界 tuple/enum/安全文本。事实来自 `plan`、`last_evaluation`、`phase`、attempt/revision 和 receipt store 查询；假设字段默认显式空 tuple，不能由模型自由填充。范围由目标和冻结计划的稳定计数/摘要构成，避免把完整目标重复写入审计。

### 2. 能力和审批采用宿主声明

Planner 只产生 planning 交接；Generator 交接只声明当前 registry 的工具名集合（不含参数/凭据）和 `confirmation_available`；Evaluator 交接声明只读工具/冻结检查 ID（不含命令）。返回责任固定为下一角色或 `caller`，不允许模型修改。

### 3. 副作用采用安全收据投影

若宿主提供 receipt store，packet 只包含当前 collaboration/loop/task 关联的 open receipt 数量及每条的 public server/tool label、phase、dispatch certainty；没有 store 时为显式空值。packet 不提供 retry/resolve 决策，也不让角色把 receipt 当作已完成事实。

### 4. 传递、恢复和审计

每个 role task data 根部带 `handoff` 对象和 `handoff_digest`。旧 `loop_context` 继续作为不可信附加字段，仅 Generator 可见。resume 读取 state 后重新生成相同 packet；`collaboration.handoff` 审计只记录角色、phase、attempt、revision、digest 前缀、事实/风险计数和返回责任，不记录正文。

## Risks / Trade-offs

- 每个角色会增加少量 JSON 上下文；通过计数、短标签和有界 evidence 控制，不把完整目标/文件内容复制到每次 handoff。
- 收据只投影 open 状态，不能证明外部动作已解决；这是刻意的 fail-closed 设计，决策仍归用户或上层策略。
- 当前模型不表达资源租约，因为项目尚无租约所有权；将其写成 `none` 比伪造租约更安全。

## Migration Plan

1. 先增加模型、packet builder、digest 和失败边界测试。
2. 将三个 role 的 task data 切换到 packet；保留既有字段和 loop_context 兼容。
3. 接入 receipt/能力投影和 handoff audit。
4. 更新 runtime-collaboration、威胁模型和里程碑证据，执行全量门禁。

## Open Questions

- 若未来需要真正的 Agent 控制权转移，必须另立 change 定义 worker 生命周期、租约、重启和冲突恢复；本 change 不预留隐式转移语义。
