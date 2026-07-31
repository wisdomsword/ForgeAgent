## 目标

在现有 `Termination.NEEDS_INFO`、Loop checkpoint 和 HTTP `TaskRecord.public_view()` 之上增加最小注意力协议，解决“需要输入/被阻塞”被误读为失败的问题，同时保持旧字段和发布暂停不变。

## 方案

1. 在 `step.py`/`task.py` 中保留旧 `needs_info` 终态，新增内部 attention projection helper，统一生成 `state`、`reason`、`owner`、`required_action`、`recovery` 五个有界字段。
2. 在 Loop 中增加 `needs_input`、`blocked` stop reason，允许 `status=stopped`，并把 attention metadata 持久化到 checkpoint/report；现有 `external_action_pending` 继续表示外部动作未决，不改名、不自动映射为 blocked。
3. 在 HTTP TaskRecord 中按普通 Task、Loop、Duo/Triad 结果投影 `attention` 对象：queued/running 为 `running`，`needs_info` 为 `needs_input`，`external_action_pending` 与明确阻塞为 `blocked`，成功/可消费结果为 `ready`。
4. 所有公开文本复用已有掩码和长度限制；状态转换复用 AuditEvent，失败沿用 audit_degraded。

## 取舍与边界

- 不将注意力状态改造成新的终态枚举；终态仍由 `status`/`reason` 表示，避免破坏 M28 RC 合同。
- 不实现服务器端等待队列、自动恢复、通知、调度器或新的确认机制；调用方负责提供输入或解除阻塞后显式重新提交/恢复。
- 不新增依赖，不改变外部副作用收据协议；未决收据仍优先报告 `external_action_pending`。

## 验证

- 先写状态映射和边界失败测试，再实现；覆盖旧 `needs_info`、新 Loop stop reason、HTTP queued/running/needs-input/blocked/ready 投影、掩码/截断和审计降级。
- 运行专项测试、完整 pytest、Ruff、格式检查、build 与 OpenSpec strict 验证；发布相关任务不执行。
