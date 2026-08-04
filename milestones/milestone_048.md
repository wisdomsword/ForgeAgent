# 里程碑 M48: 交互行为移植与任务执行证据

- 状态: 已完成并归档
- 起止: 2026-08-03 ~ 2026-08-05
- 对应 ACTION_PLAN 行: M48（本里程碑新增）
- 前置里程碑: [milestone_047](milestone_047.md)
- OpenSpec changes: `port-startup-logo-persistence`、`port-direct-prose-completion`、`port-task-filesystem-authority`、`expose-task-execution-evidence`

## 目标与范围

以 M47 后的 `main` 为唯一基线，移植三个已在旧分支验证但未进入 `main` 的行为：启动 Logo 持久显示、直接接受 prose 完成、任务级文件系统授权；新增任务执行证据契约，使 Single/REPL、HTTP、Loop、Duo 和 Triad 在终态明确公开使用过的工具、状态与程序制品信息。CLI 只显示安全本地路径，HTTP 只显示相对制品引用；不增加下载端点、自动清理系统、任意工具输出归档、外部 listener、依赖或发布目标。

## 方案设计

- 三个移植项分别使用独立 tweak change，从 M47 基线移植并验证，不整体合并旧分支。
- 执行证据使用 full workflow：Task 拥有有界 recorder，内部最多 128 条，公开/durable 最多 32 条。
- 所有实际执行的 named/inline/Edit 后程序先原子持久化，再 dispatch 到 trusted/restricted/container backend；失败时 fail closed。
- 制品目录位于项目根下 `.forgeagent/execution-artifacts/<execution-id>/programs/`，限制 100 个程序、单文件 1 MiB、总量 8 MiB。
- HTTP 只返回 canonical relative reference，不新增读取 route；CLI 只解析并显示可信 project root 下的本地路径。
- Loop 按 iteration 聚合，Duo/Triad 按 role/attempt 聚合；恢复保持前缀、全局截断计数和原子状态边界。
- 公开/durable evidence 丢弃模型控制的 block、代码、参数、prompt、异常正文、secret 和非本地绝对路径。

## 子任务清单

- [x] 移植并归档启动 Logo 持久显示。
- [x] 移植并归档直接 prose 完成，同时保留 required completion tool 优先级。
- [x] 移植并归档任务级 `RequestFilesystemAccess` 授权。
- [x] 完成执行证据模型、制品 store、Exec/Step/Task 接入和三 backend fail-closed。
- [x] 完成 CLI/REPL、HTTP、Loop、Duo/Triad 终态投影和 durable 恢复。
- [x] 完成离线端到端矩阵、全量验证、安全/兼容性审查与 OpenSpec 归档。

## 交付物清单

- [x] `src/forgeagent/execution_evidence.py` — 有界证据模型、安全投影、聚合与程序制品 store。
- [x] `src/forgeagent/tools.py`、`step.py`、`task.py` — 持久化先于 dispatch、稳定失败证据和 Task 终态快照。
- [x] `src/forgeagent/cli.py`、`_cli_collaboration.py`、`http_task_service.py` — 各入口终态工具/状态/制品信息。
- [x] `src/forgeagent/loop.py`、`collaboration.py` — iteration 与 role/attempt durable 聚合、恢复和原子提交。
- [x] `tests/test_execution_evidence.py` 及 CLI/HTTP/Loop/Collaboration 测试 — 数值边界、安全、恢复和真实制品端到端矩阵。
- [x] [执行证据验证报告](../docs/superpowers/reports/2026-08-04-expose-task-execution-evidence-verify.md) — 命令、输出、工具与程序路径。
- [x] 四个归档 change：`openspec/changes/archive/2026-08-04-port-*` 与 `2026-08-04-expose-task-execution-evidence`。

## 三次评审

### 技术方案评审

- [x] 四个独立 change 的归属、顺序和 M47 基线符合批准方案，未整体合并旧分支。
- [x] 执行证据采用任务级持久化契约，CLI/HTTP 路径边界和容量/保留策略符合 design 决策。
- [x] 未新增依赖、下载端点、外部 listener、发布或自动清理目标。

### 代码评审

- [x] 每个 build Task 均有独立实现与审查；whole-change 最终复审无 P0-P2 finding。
- [x] 已修复 Rich markup 注入、累计 omitted 重复计数、协作成功边界非原子、公开 block 泄露和 CLI 反向依赖。
- [x] 已修复 Task 急切初始化制品 store 与 lazy wrapper 类型契约；不可用根目录和容量失败均 fail closed。

### 验收评审

- [x] 最终受影响集合 `1007 passed, 10 skipped`；合并到 main 后同一集合再次 `1007 passed, 10 skipped`。
- [x] 沙箱内全量 `2921 passed, 23 skipped, 15 failed`；15 条均为 loopback/build 权限限制，对应沙箱外失败集合 `16 passed`。
- [x] 里程碑收尾提交后，沙箱外本地 main 全量 `2952 passed, 11 skipped`。
- [x] Ruff format `149 files already formatted`、Ruff check 全绿、diff check 通过。
- [x] 归档后 OpenSpec strict `40 passed, 0 failed`；四个 change 均 `verify_result: pass` 且 `archived: true`。

## 遗留问题

- [ ] 程序制品无 HTTP 下载端点 — 影响：HTTP 客户端只能获得安全相对引用，不能直接读取制品 — 计划：当前明确为非目标，只有出现受认证读取需求时另立 change。
- [ ] 程序制品未实现自动清理 — 影响：任务目录由项目生命周期管理，长期运行可能需要外部保留策略 — 计划：收集真实容量/保留需求后独立设计。
- [ ] 最终全量测试保留 11 个既有 skip — 影响：对应场景未在本次主机配置中执行，具体原因以各测试的 skip 标记为准 — 计划：继续由现有 CI 或具备对应运行时的主机复验，不阻塞 M48。

## 续接指引

M48 已在本地 `main` 完成并归档，后续以 `milestones/latest` 和 `ACTION_PLAN.md` 为准。ForgeAgent 的任务终态现在必须明确投影工具、状态与程序制品：CLI 使用本地路径，HTTP 使用相对引用，Loop/Duo/Triad 保留 iteration/role/attempt 来源。新增入口或 durable report 时必须复用 `ExecutionEvidence` 安全投影，不能重新暴露 block、代码、参数、prompt、secret 或非本地绝对路径。HTTP 下载端点、制品自动清理和任意工具输出归档仍是独立非目标；普通开发分支 push 继续需要明确授权。
