# 里程碑 M16: HTTP headless 服务 + 审计日志

- 状态: 已完成（真实 loopback bind 与 wheel/sdist 构建受当前沙箱权限、DNS/构建缓存限制，作为明确遗留）
- 起止: 2026-07-21 ~ 2026-07-22
- 对应 ACTION_PLAN 行: M16（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_015](milestone_015.md)
- 最终实现 commit: `f4a3ef7`
- 验证状态 commit: `b67bdf0`
- OpenSpec 归档: `openspec/changes/archive/2026-07-22-http-task-service/`

## 目标与范围

交付本机、单用户、headless 的 HTTP 任务入口：提供鉴权的异步提交、状态/安全结果查询和协作式取消；复用既有 `Task`/`Step`、sandbox、模型和工具确认语义；增加核心层 JSONL 审计、精确 HTTP allowlist、容量/TTL/响应上限和资源关闭约束。M16 不做远程部署、TLS、多租户、数据库、scheduler、WebSocket 或流式 HTTP。

## 方案设计

- 使用标准库 `ThreadingHTTPServer` 和三条固定路由，不新增运行时依赖；只允许 loopback 监听，缺少静态 bearer token 时拒绝启动。
- `TaskService` 使用有界 worker、队列和内存记录表；请求 schema 不允许客户端覆盖 tier、backend、allowed root、container、identity、credential 或 MCP 连接策略。
- 取消使用 `threading.Event` 在轮次和工具边界协作收敛为独立 `cancelled` 终态，不强杀正在进行的 provider/tool 调用。
- 核心层注入 `AuditSink`，记录 HTTP、LLM attempt、工具和 confirmer 事件；JSONL 写入加锁、按字节轮转、保留受限、secret/path/URL 掩码。启动失败 fail-closed，运行时写入失败 fail-open 且标记 degraded。
- HTTP confirmer 只读取规范化精确 allowlist。MCP `autoApprove` 仅保留 CLI/REPL 兼容语义，HTTP 路径显式传递 `allow_auto_approve=False`。
- 设计文档：`docs/superpowers/specs/2026-07-21-http-task-service-design.md`；实施计划：`docs/superpowers/plans/2026-07-21-http-task-service.md`；验证报告：`docs/superpowers/reports/2026-07-21-http-task-service-verify.md`。

## 子任务清单

- [x] Task 1：HTTP 配置、严格请求契约和协作式取消原语
- [x] Task 2：注入式审计 sink、安全序列化、轮转和核心事件埋点
- [x] Task 3：有界 `TaskService`、任务状态/结果投影、TTL 和资源生命周期
- [x] Task 4：headless confirmer、精确 allowlist 与 CLI `autoApprove` 隔离
- [x] Task 5：鉴权的 stdlib HTTP handler、三条路由和错误 envelope
- [x] Task 6：`forgeagent serve` opt-in 装配、配置和启动/关闭策略
- [x] Task 7：HTTP golden 回放、并发/shutdown 验收、README 与威胁模型
- [x] OpenSpec 严格验证、Comet full verify、分支保留和 delta spec 归档
- [ ] 真实 loopback listener 与 wheel/sdist 隔离安装 — 当前 managed sandbox 禁止 `bind(('127.0.0.1', 0))`，且 PyPI DNS 无法取得 `hatchling`；需在具备相应权限/缓存的环境补跑

## 交付物清单

- [x] `src/forgeagent/http_config.py` / `http_server.py` — 服务配置、鉴权、请求解析、路由和有界错误/结果响应
- [x] `src/forgeagent/http_task_service.py` / `headless.py` — 有界任务注册表、取消/资源生命周期和 HTTP 精确 allowlist
- [x] `src/forgeagent/audit.py` / `secret_policy.py` — 核心审计事件、安全序列化、JSONL 写入和轮转
- [x] `src/forgeagent/task.py` / `step.py` / `tools.py` / 两个模型 client — 取消、task correlation、attempt/tool/confirmation 审计和 `allow_auto_approve` 显式传播
- [x] `src/forgeagent/cli.py` — opt-in `serve` 入口及服务端策略装配
- [x] `tests/test_http_config.py` / `test_http_task_service.py` / `test_http_server.py` / `test_headless.py` / `test_audit.py` — 配置、并发、取消、鉴权、结果投影、审计、allowlist 和生命周期覆盖
- [x] `tests/test_mock_replay_e2e.py` 及工具/Task/Step/client 回归 — HTTP G13 等价回放和共享核心契约覆盖
- [x] `docs/http-task-service.md` / `README.md` / `docs/threat-model.md` — 部署、鉴权、审计、取消、结果投影与信任边界说明
- [x] `openspec/specs/http-task-service/spec.md` / `audit-logging/spec.md` / `tool-approval/spec.md` — 归档后主规格

## 三次评审

### 技术方案评审

- [x] 设计自审确认 stdlib server、loopback-only、严格 schema、安全结果投影、容量/TTL、取消竞态、审计失败策略和资源 ownership 与 OpenSpec 一致
- [x] 正式 OpenSpec 验证：22/22 tasks、10/10 requirements、39/39 scenarios 均有实现和测试映射；proposal、OpenSpec design、技术 Design Doc 与实现无矛盾
- [x] `openspec validate http-task-service --strict` 通过，Comet verify guard 进入 archive，归档脚本 7/7 steps succeeded

### 代码评审

- [x] 各实现任务均经独立实现审查与修复回合，覆盖审计 retention、任务提交原子性、HTTP framing/auth、路径配置、shutdown 和结果脱敏
- [x] whole-change 终审发现 Critical：HTTP `HeadlessConfirmer` 未把禁止 `autoApprove` 的策略传递到 `Task -> Step -> ToolContext`，空 HTTP allowlist 仍可能被 MCP `autoApprove` 绕过
- [x] `f4a3ef7` 显式传播 `allow_auto_approve=False`，端到端回归证明 HTTP 空 allowlist 下不查询 `is_auto_approved` 且不调用 MCP 工具；最终复审无 Critical/Important

### 验收评审

- [x] 非 packaging 全量：`PYTHONPATH=src .venv/bin/pytest -q --ignore=tests/test_packaging.py` → `1221 passed, 23 skipped in 50.99s`
- [x] HTTP autoApprove + tools + headless 聚焦回归：`63 passed`；HTTP/mock/headless 聚焦回归：`98 passed, 10 skipped`
- [x] 并发/shutdown/G13 聚焦测试连续 5 次通过；8 路并发任务 id 唯一且各自收敛，G13 direct/HTTP 均为 completed、3 rounds、2 tool outcomes
- [x] 离线 golden runner 退出 0，报告 `20/20 (100%)`
- [x] `.venv/bin/ruff check src tests`、M16 变更文件 format check、`git diff --check` 和 strict OpenSpec validation 均通过
- [x] 审计验收覆盖稳定字段、attempt/idempotence、secret/path masking、异常值、并发 append、轮转/保留、`0600` 和 degraded 语义
- [ ] 实际 listener bind — 当前 managed sandbox 返回 `PermissionError: [Errno 1] Operation not permitted`；完整 framing/auth/dispatch/concurrency 已由 `socket.socketpair()` handler 测试覆盖
- [ ] 真实 wheel/sdist — `tests/test_packaging.py` 为 `2 passed, 1 failed`，失败来自 `uv build` 三次重试后无法通过 DNS 获取 PyPI `hatchling`

## 遗留问题

- [ ] FileWrite canonical path 校验与 pathname open 之间仍有 hostile-host symlink TOCTOU — 影响：攻击者可并发替换路径时存在竞态 — 计划：后续 sandbox/path hardening 单独处理，不在 M16 扩展
- [ ] 协作取消不能打断正在进行的 provider/tool 调用 — 影响：取消只会在下一安全边界生效 — 计划：M21 stop conditions/checkpoint 设计时继续收敛
- [ ] audit 启动压缩可能一次性读取整个旧日志文件 — 影响：超大既有日志会产生短时内存峰值 — 计划：出现真实规模需求后改为 bounded tail，不提前抽象
- [ ] Windows UNC 路径没有专门验收 — 影响：M16 仅有 Unix 路径实证 — 计划：Windows 支持排期时补平台测试
- [ ] error envelope 写出期间客户端断连时，`socketserver` 可能输出诊断 traceback — 影响：不重复 lifecycle audit，也不进入 JSON 响应，但 stderr 可能有噪声 — 计划：后续服务可观测性清理时评估抑制
- [ ] 真实 loopback bind 与 wheel/sdist 构建未在当前环境完成 — 影响：缺少当前机器上的 listener/分发产物实证 — 计划：在允许 loopback 且具备 hatchling 缓存或 PyPI DNS 的环境补跑

## 续接指引

M16 已在分支 `codex/m16-http-task-service` 完成验证并归档为 `openspec/changes/archive/2026-07-22-http-task-service/`，分支按已选方案保留，未 push。下一阶段是 M17 Context Engineering：先读取 `TECH_PATH.md` §三 M17 和本文件遗留，再通过 `/comet` 创建新的 full change。M17 应复用并保持 M16 的 HTTP 配置、`TaskService` 状态/安全结果投影、取消、审计和 headless allowlist 契约；不要顺带扩大到远程监听、TLS、多租户或持久任务数据库。
