## Why

M22 归档后复核发现两处实现未满足已归档契约：Planner 只在 `acceptance` 字段阻止 HOW，具体实现方法仍可从 `behavior` 被冻结；协作审计没有 mode routing 事件，角色异常路径也缺少完整 lifecycle outcome。两者分别削弱不可降标计划和可归因审计边界。

## What Changes

- 对 Planner 清单的 `behavior` 与 `acceptance` 同时执行 WHAT-only 校验。
- 在确定模式后记录 `collaboration.route`，不记录 goal。
- 为每个角色记录 start/outcome；outcome 包含稳定 model/tier/status、耗时和归一化 usage，构建或执行异常也必须收口为安全事件。
- 增加回归测试，并同步 M22 归档后状态文档。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`：明确 WHAT-only 校验同时覆盖 `behavior` 与 `acceptance`。
- `audit-logging`：明确 route、role start 与 role outcome 的稳定事件合同及异常收口。

## Impact

影响协作控制器、CLI/HTTP/Loop 模式路由审计和对应测试；不改变公开 CLI/HTTP schema、持久化 schema、依赖或 single/Duo/Triad 完成语义。
