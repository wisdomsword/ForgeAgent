---
change: bind-http-remote-action-approvals
milestone: M44
status: pass
verified_at: 2026-08-01
base_ref: 6b5b2476c1369f37f1c01c89c55d83fb0f1ab47a
---

# M44 HTTP 远程动作审批绑定验证报告

## 结论

M44 通过完整验证，可以进入规格同步与归档。实现保持 HTTP listener 为 loopback-only，新增的是既有 Bearer 控制面内的短期 `allow_once` MCP 动作权限和显式 receipt 恢复，不开放公网入口、不引入 Gateway、不承诺远端业务 exactly-once。

| 维度 | 结果 |
| --- | --- |
| 完整性 | 10/10 build tasks 完成；规格同步、归档、M44 里程碑和已授权分支 push 由后续生命周期阶段执行 |
| 正确性 | 6/6 requirements、21/21 scenarios 有实现与测试或真实 verifier 证据 |
| 一致性 | OpenSpec design、Superpowers Design Doc、实现和公开文档一致，无未记录偏差 |
| 安全性 | loopback + Bearer 保持不变；权限精确绑定 scope/digest/task/TTL；无自动重放；公开投影无 goal、raw arguments、secret、路径、evidence 正文或 raw exception |

## 需求与证据映射

### HTTP action approvals

- `HttpActionApprovalStore` 使用严格不可变模型、有界容量、1-3600 秒 TTL 和单锁状态迁移；`bind_many` 全有或全无，`consume` 精确匹配 task/scope/digest 且只成功一次：`src/forgeagent/http_action_approvals.py`。
- `HeadlessConfirmer` 先检查既有静态 allowlist，仅在未命中时消费任务绑定审批；审批 ID 不进入模型 options：`src/forgeagent/headless.py`、`src/forgeagent/http_task_service.py`。
- 签发、查询、撤销与 task `approval_ids` 路由沿用同一认证、body 上限、origin-form 和固定错误边界：`src/forgeagent/http_server.py`。
- 竞态、过期、复用、错 task/scope/digest、容量和安全投影由 `tests/test_http_action_approvals.py`、`tests/test_headless.py`、`tests/test_http_server.py` 覆盖。

### Receipt recovery

- 外部动作继续在 dispatch 前持久化 receipt；HTTP 只提供 revision-guarded `confirmed|abandoned|retry_approved` 状态决策，不调用 MCP、不恢复任务、不创建替代动作：`src/forgeagent/external_actions.py`、`src/forgeagent/http_task_service.py`。
- retained task 建立常规恢复权限；进程重启后，仅 exact route task ID 匹配的 durable open receipt 建立窄化恢复权限。未知 task 且无匹配 receipt 仍为 404，已关闭 receipt 不重新暴露。
- `tests/test_http_server.py::test_http_receipt_recovery_survives_process_local_task_and_approval_loss` 证明审批和任务记录丢失后仍可恢复 durable unknown receipt，且不会重建审批。

### Public projection and audit

- 审批、receipt、capability 和 HTTP audit 只输出固定类型、安全标签、摘要与计数；历史 receipt label 也经过统一公开投影：`src/forgeagent/external_actions.py`、`src/forgeagent/tools.py`。
- HTTP 请求解析明确拒绝 client-owned task ID、approval authority 字段和直接 server/tool 动作字段；错误响应不包含原始异常或私有记录。
- 相关泄漏断言覆盖 secret、goal、raw arguments、绝对路径、evidence 正文和 exception 文本。

## 两轮评审

### 第一轮

发现并修复：

1. 新建 Loop/Collaboration runner 的普通路径未与 resume 路径一样注入共享 receipt store。
2. `get/bind/revoke` 触发 expiry 后在拒绝路径丢失固定审计事件。
3. 历史 receipt label 可能把绝对路径带入 HTTP 与工具 audit。
4. prepared receipt 的非法确认已有模型不变量保护，补入显式回归测试而未增加重复分支。

### 第二轮

发现并修复：

1. 初版 receipt route 依赖 process-local retained task，进程重启后 durable unknown receipt 无法恢复。改为 exact task-owned open receipt 的最小恢复权限，不建立全局查询面。
2. HTTP task parser 缺少对直接 `request_digest` 和 `server/tool` authority 字段的显式拒绝案例。
3. 对 6 项 requirement、21 项 scenario 逐项复核，没有发现 scope/digest 放宽、重复 dispatch、跨任务恢复或公开数据泄漏。

## 验证过程修复

首次全量测试暴露 4 个与 M44 无关但会破坏分支基线的失败：M33/M34 规划证据未进入基准提交、已撤销 `publish-v0-1-0` 仍处于 active、HTTP attention 投影实现缺失、handoff 新固定审计字段未同步旧白名单。已按现有契约补齐最小基线并独立提交；未复制主工作区其他脏改动。修复后相关 174 项测试通过，全量测试转绿。

## 门禁证据

- `uv run pytest -q` -> `2695 passed, 10 skipped in 170.63s`。
- `uv run ruff check .` -> `All checks passed!`。
- `uv run ruff format --check .` -> `144 files already formatted`。
- `openspec validate --all --strict --no-interactive` -> `29 passed, 0 failed`。
- `uv build` -> 本地 sdist 与 wheel 构建成功；未上传、未创建 tag、未执行发布自动化。
- `git diff --check` -> 通过。
- `uv run python scripts/m44_http_action_approval_smoke.py` ->
  `{"approval_status":"consumed","dispatch_count":1,"receipt_phase":"confirmed","reconcile_dispatch_delta":0,"unknown_resolution":"confirmed"}`。

## 剩余边界

- 未开放非 loopback listener；外部可达控制面仍需独立威胁模型和真实部署 verifier。
- 未消费审批是进程内能力，重启后必须重新签发；durable receipt 独立保留未知动作恢复能力。
- `confirmed` evidence 记录控制者/provider 的判断，不能证明远端业务结果或 exactly-once delivery。
- 本里程碑不执行 PyPI、tag 或发布自动化；普通开发分支 push 已由用户单独授权。
