# Brainstorm Summary

- Change: attention-state-projection
- Date: 2026-07-30

## 确认的技术方案

- 新增一个小型、不可变、严格校验的 `AttentionState` 模型，字段为 `state`、`reason`、`owner`、`required_action`、`recovery`；所有文本统一有界、去控制字符并做 secret masking。
- 旧 `needs_info` 保持不变；`TaskStatus` 增加可选 attention；Survey/模型显式阻塞通过同一投影进入 `needs_input`/`blocked`。
- Loop 的 `needs_input`、`blocked` 是 `status=stopped` 下的新 `stop_reason`，attention 元数据随 checkpoint/report 持久化；`external_action_pending` 保持独立 stop reason，但其 attention 投影为 blocked。
- HTTP 只增加 additive `attention` 对象；queued/running 为 running，needs_info 为 needs_input，成功/取消/失败结果可消费时为 ready，外部未决或明确阻塞为 blocked；原 status/reason/detail 保留。
- 过渡审计复用 AuditEvent，任务/Loop 在状态进入终态或 attention 状态时写入安全有界事件；失败沿用 audit_degraded。

## 关键取舍与风险

- 不重命名 `needs_info`，不把 attention 变成第二套终态机；避免破坏 M28 HTTP/RC 合同。
- 不新增 scheduler、等待队列、通知、自动恢复或依赖；用户/上层调用方负责补输入或解除阻塞后显式 resume/retry。
- 旧 Loop checkpoint 通过默认字段迁移；新字段不可接受未定义值，避免错误数据被静默解释。
- `external_action_pending` 优先于普通 attention stop，防止收据未决时被误当成普通 blocked 并自动重放。

## 测试策略

- 先为 AttentionState、旧映射、掩码/截断和非法字段写失败测试。
- 覆盖 Task/Step 的 Survey `needs_info`、显式 blocked、完成/取消/失败 ready 投影。
- 覆盖 Loop checkpoint/report/status 不变量、attention stop、resume 不重放和审计字段。
- 覆盖 HTTP queued/running/needs-input/blocked/ready、Duo/Triad、旧字段兼容和安全披露。
- 最终运行专项 pytest、全量 pytest、Ruff、format check、build、OpenSpec strict，并进行两轮一致性复审。

## Spec Patch

无；现有 delta spec 已包含本设计需要的验收场景。
