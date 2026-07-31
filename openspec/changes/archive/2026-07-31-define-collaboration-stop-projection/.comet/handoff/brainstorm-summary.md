# Brainstorm Summary

- Change: define-collaboration-stop-projection
- Date: 2026-07-31

## 确认的技术方案

用户已授权在两轮自评后由 agent 选择推荐方案。采用一个静态、确定性的 stop projection helper，把 Task/Loop 的稳定原因映射为 Collaboration 的 status、stop reason 和可选 attention；保留具体资源原因。内部角色 task data 使用验证后的原始 goal，HandoffPacket、report 和 audit 使用独立的公开脱敏投影。

## 关键取舍与风险

- 不把资源原因压缩为 `resource_exhausted`，避免丢失 `wall_clock`、`token_budget` 等诊断。
- 不在 CollaborationRunner 中嵌套 LoopRunner，只定义兼容投影词表并处理当前角色 TaskOutcome。
- attention 只作为附加字段；旧 status/reason 和旧 snapshot 继续可读。
- 未知原因 fail closed 为固定失败，不允许任意公开枚举。

## 测试策略

TDD 覆盖完整映射矩阵、Runner 透传、snapshot/report 不变量、HTTP 兼容、合法绝对路径在内部 goal 中保留、公开 handoff/report/audit 无路径、secret、raw goal 或异常正文。

## Spec Patch

无。当前 delta spec 已包含资源耗尽、等待输入、阻塞、失败和目标双视图的验收场景。
