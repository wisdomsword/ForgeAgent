---
comet_change: structured-collaboration-handoff
role: technical-design
canonical_spec: openspec
status: draft
archived-with: 2026-07-30-structured-collaboration-handoff
status: final
---

# 结构化协作交接技术设计

## 结论

在现有 Duo/Triad 串行编排上增加一个由宿主状态生成的、冻结且有界的
`HandoffPacket`。它在 Planner、Generator、Evaluator 角色边界随任务数据传递，
同时生成稳定摘要哈希和低敏审计事件。控制权仍归
`CollaborationRunner`；本变更不引入调度器、租约服务、网络控制转移或新的存储后端。

## 现状与缺口

现有 `CollaborationState` 已持久化目标、冻结计划、阶段、尝试次数、拒绝次数、
评估结果和停止原因，因此恢复由宿主状态决定。但角色任务数据只分别携带目标、
计划、拒绝信息和不可信的 `loop_context`，没有统一表达：已验证事实、显式假设、
未决副作用收据、能力/审批范围、检查点和结果归属者。不同角色因此可能对“当前
交接状态”产生不同解释。

## 数据模型与边界

`HandoffPacket` 为严格、冻结的 Pydantic 模型，字段只允许以下公共投影：

- `goal` 与有界 `scope`：目标摘要、计划项标识、计划摘要和项数；
- `verified_facts`：来自宿主持久状态和最近评估的有界事实，不接受模型自由摘要；
- `assumptions`：有界、可为空的未验证假设，当前默认显式为空；
- `open_side_effects`：仅公开 server/tool label、阶段和 dispatch certainty；
- `capabilities` 与 `approval`：当前角色可见的工具名/检查名及其只读或需审批属性，
  不包含参数、凭据、原始 schema 或执行权限；
- `checkpoint`：revision、phase、attempt/rejection counters；
- `stop_conditions`：宿主定义的停止条件标签；
- `return_owner`：下一结果的固定归属者；
- `receipt_visibility`：收据存储可用或明确不可用。

所有文本使用既有安全投影和长度上限；绝对路径、密钥样式值、控制字符和超长输入
均被掩码或拒绝。模型不得写回 `CollaborationState`，也不能凭 packet 获得新的工具
调用、审批或副作用权限。

## 数据流

1. Runner 在每次角色调用前，从当前冻结状态、角色注册表、评估检查和可选收据存储
   生成 packet。
2. Runner 将 JSON packet 与稳定 `handoff_digest` 放入现有角色任务数据；原有
   `goal`、`plan`、`rejection` 和 `loop_context` 字段保持兼容。
3. 宿主发出 `collaboration.handoff` 审计事件，只记录角色、phase、attempt、revision、
   digest 前缀、各类计数、收据可见性和 return owner，不记录目标、事实正文、路径或
   receipt ID。
4. 恢复时不反序列化 packet 作为权威状态，而是从 durable state 和当前宿主投影重新
   构建；因此旧 packet 不能覆盖新 revision，也不能触发静默重放。

角色归属固定为：Planner 的结果交给 Generator，Generator 的结果交给 Evaluator，
Evaluator 的结果交给调用方；Duo 模式跳过 Planner 但使用相同的 Generator→Evaluator
packet。Single 模式保持现有任务数据和控制流，不生成协作交接 packet。

## 收据与安全处理

当 `ExternalActionReceiptStore` 可用时，只展示当前 loop/task 的未决收据公共标签；
若存储缺失、查询失败或上下文不完整，packet 明确标为 `unavailable`，而不是伪造“无
未决副作用”。任何 `prepared`、`dispatched`、`unknown` 收据仍由原有恢复协议处理，
交接只提供风险可见性，绝不自动确认、补发、重放或回滚。

## 验证策略

先为严格模型、确定性摘要、secret/path masking、收据可用/不可用、角色边界传递、
拒绝后重建、恢复时重建和审计脱敏编写失败测试，再实现最小代码。最后运行专项与
全量 pytest、Ruff、格式检查、`uv build`、OpenSpec strict，并进行两轮一致性/遗漏自评。

## 明确不做

不实现 Agent 网络、并行调度、跨进程租约、数据库或远程 packet 服务；不把 packet
作为新的公开 API；不引入新依赖、配置项、endpoint、发布动作或 PyPI 操作。
