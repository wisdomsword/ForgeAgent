## Why

现有 HTTP 入口只能依赖启动时静态 allowlist 批准外部动作，无法让经认证的控制面把一次审批精确绑定到某个任务、动作范围和参数摘要，也无法通过 HTTP 撤销未使用审批或显式恢复 `unknown` receipt。M44 在继续保持 loopback-only 的前提下补齐这条最小、可验证且不自动重放的控制链。

## What Changes

- 新增宿主拥有的短期 `allow-once` 审批记录，绑定精确 MCP scope、canonical request digest、有效期和唯一任务。
- 新增经现有 Bearer 认证保护的审批签发、查询、撤销接口；任务提交显式认领审批后才可消费。
- 让 HTTP headless confirmer 在静态 allowlist 之外仅消费与当前 `task_id + scope + digest` 完全匹配的有效审批。
- 新增按任务列出未决 receipt 和显式 reconcile 的 HTTP 接口；确认、放弃或允许新尝试都只更新 receipt，不执行原动作。
- 增加真实 loopback verifier，覆盖审批签发、任务绑定、一次性消费、receipt 生成和未知状态恢复。
- 保持监听地址为 loopback，不增加 TLS、反向代理、用户体系、Gateway、公开网络入口或自动重放。

## Capabilities

### New Capabilities

- `http-action-approvals`: 定义短期一次性远程动作审批的签发、任务认领、精确消费、过期和撤销契约。

### Modified Capabilities

- `http-task-service`: 增加审批引用、审批管理和按任务 receipt reconcile 的严格认证 HTTP 契约，同时保持 loopback-only 与安全公开投影。
- `external-action-receipts`: 允许经 HTTP 认证的宿主调用者显式列出和恢复未决 receipt，且禁止任何恢复操作自动 dispatch。

## Impact

- 主要影响 `headless.py`、`http_server.py`、`http_task_service.py`、HTTP CLI 组装、外部动作 receipt 接入及相应测试/文档。
- 新增一个项目内审批状态模块和一个真实 loopback verifier；不新增第三方依赖，不修改 MCP 协议，不开放非 loopback 监听。
- M44 分支还会补入已被现有源码引用但未纳入 Git 的 `attention.py` 及其契约测试，使干净检出恢复可验证基线；该修复不扩展审批能力。
