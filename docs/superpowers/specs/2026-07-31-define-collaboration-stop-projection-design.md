---
comet_change: define-collaboration-stop-projection
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-31-define-collaboration-stop-projection
status: final
---

# Collaboration Stop Projection 技术设计

## 1. 目标与边界

本 change 稳定 Collaboration 对 Task/Loop 终止原因的公开表达，并显式分离内部执行目标和公开 handoff 目标。它不新增调度器、通用状态机、HTTP endpoint、依赖或发布动作，也不修改 M39 后续的 Duo 验收计划。

兼容原则：

- 已有 `completed`、`rejection_limit`、`needs_confirmation`、`cancelled` 和失败原因保持可读。
- CollaborationState/Report 只附加可选 attention；旧 JSON 缺字段继续加载。
- Single mode 仍返回原 `TaskOutcome`。
- M27 的 collaboration mode/source 迁移规则不变。

## 2. 原因投影

在 `collaboration.py` 增加一个私有纯函数，输入稳定 reason 和可选已有 attention，输出固定 `(status, stop_reason, attention)`。映射分组如下：

| 来源 | Collaboration status | stop reason | attention |
| --- | --- | --- | --- |
| `completed` | `completed` | `completed` | 无 |
| `rejection_limit` / `needs_confirmation` | `stopped` | 原原因 | 无或既有兼容投影 |
| `needs_info` / `needs_input` | `stopped` | `needs_input` | `needs_input` |
| `blocked` | `stopped` | `blocked` | `blocked` |
| `external_action_pending` | `stopped` | `external_action_pending` | `blocked` |
| `max_rounds` / `wall_clock` / `token_budget` / `token_usage_unavailable` / `consecutive_failures` | `stopped` | 原原因 | 无 |
| `cancelled` | `cancelled` | `cancelled` | 无 |
| auth/invalid-request、checkpoint/state/protocol 失败 | `failed` | 固定失败原因 | 无 |
| 未知 reason | `failed` | `role_failed` | 无 |

当前 CollaborationRunner 的角色边界只消费 TaskOutcome，因此 `_task_failure()` 应用 Task 映射。Loop reason 表同时作为纯函数的已知输入测试，保证外层适配或报告投影不会再发明另一套分类；Runner 不复制 Loop 的预算逻辑。

## 3. 数据模型不变量

`CollaborationState` 和 `CollaborationReport` 增加 `attention: Attention | None = None`。`_STOP_REASONS` 扩展固定 stopped 词表。模型验证规则：

- `needs_input` 必须携带 `attention.state=needs_input`。
- `blocked` 和 `external_action_pending` 必须携带 `attention.state=blocked`。
- 其他终态不得持久化 needs_input/blocked attention，避免状态漂移。
- 旧 snapshot 没有 attention 时，只要不是上述新增原因就保持兼容。

`CollaborationReport.from_state()` 复制安全 attention，不从 goal、evidence 或异常正文派生。

## 4. 执行目标与公开目标

数据流明确为两条：

```text
CollaborationState.goal (validated raw execution intent)
  ├─ _planner_task_data / _role_task_data -> internal role goal, preserves legal path
  └─ _public_handoff_goal -> HandoffPacket.goal, masks path/secret/control chars
                                  └─ handoff digest + bounded audit metadata only
```

`HandoffPacket.goal` 保持字段名和 schema，不做破坏式重命名；构造点显式调用公开投影 helper。角色 task data 仍可能同时包含内部 `goal` 和公开 `handoff.goal`，这是有意的双视图：模型执行使用前者，跨边界摘要使用后者。`collaboration.handoff` 审计继续只记录 role、phase、attempt、revision、digest prefix、计数和 return owner。

## 5. Runner 处理顺序

角色完成后的顺序保持：加载并校验持久状态、累计使用量/attempt、处理取消、验证 required Submit、再处理 Task 非完成原因。`_task_failure()` 对 `needs_info`、blocked、预算耗尽和客户端错误使用投影 helper；结构化提交缺失仍优先得到 `invalid_role_submission`，避免把协议违规误分类成资源停止。

取消继续在安全边界优先，状态保存失败继续转为 `state_failure`。异常捕获不输出 message；既有固定类型日志约束不变。

## 6. TDD 与验证

先增加失败测试：

- 纯映射矩阵覆盖正常打回、五类资源停止、needs input、blocked、external action、取消、不可恢复与未知原因。
- Generator/Evaluator Task 返回 `needs_info`、blocked、max_rounds 时，Runner 报告对应 stopped 原因且不继续创建角色。
- CollaborationState/Report JSON 旧数据兼容和 attention 不变量。
- `/data/input.csv` 在 `_role_task_data` 的 raw goal 中保留，`HandoffPacket.goal` 和 audit 中不可见。
- goal 同时包含 secret、控制字符、绝对路径时，report/audit 不出现 raw goal、路径、secret 或原始异常。
- Loop/HTTP focused tests确认稳定 reason 无二次归类。

然后运行 focused pytest、全量 pytest、Ruff check、Ruff format check、`uv build` 和 OpenSpec strict。任何失败先按 systematic debugging 定位，不通过弱化安全不变量修复。

## 7. 回滚与非目标

实现不做磁盘迁移。回滚可删除新增字段和映射；旧 snapshot 无需改写。Loop handoff 结构化、Duo goal 拆解、Memory/远程审批/重写门禁均不属于本 change。PyPI、tag、push 和发布自动化保持禁用。
