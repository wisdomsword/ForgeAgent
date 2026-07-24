# 里程碑 M21: Loop Engineering

- 状态: 已完成并归档
- 起止: 2026-07-24 ~ 2026-07-24
- 对应 ACTION_PLAN 行: M21（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_020](milestone_020.md)
- 技术设计: [2026-07-24-loop-engineering-design](../docs/superpowers/specs/2026-07-24-loop-engineering-design.md)
- 验证报告: [2026-07-24-loop-engineering-verify](../docs/superpowers/reports/2026-07-24-loop-engineering-verify.md)
- OpenSpec change: [`2026-07-24-loop-engineering`](../openspec/changes/archive/2026-07-24-loop-engineering/)

## 目标与范围

在现有 `Task` 上方交付轻量持久化 Loop：由 CLI、既有 HTTP `/tasks` 或用户安装的
cron/launchd/systemd 调度入口显式触发；使用版本化 checkpoint 提交跨 Task 进度并恢复；
按累计轮次、token、墙钟、连续失败和协作取消收敛停止。普通 `run`、REPL、普通 HTTP、
M20 Evaluator 和 trusted golden 热路径保持不变；不引入 scheduler daemon、数据库、新 HTTP
endpoint、workflow framework、跨进程 exactly-once 或 M22 Duo/Triad 验收语义。

## 方案设计

- `LoopCheckpointStore` 在 `<allowed_root>/.forgeagent/loops/` 内持久化严格
  `forgeagent.loop.v1` JSON，使用固定目录 fd、相对 open/replace/fsync、revision 与大小/文本
  上限，拒绝 symlink、父目录换绑、未知字段和不一致终态。
- `LoopRunner` 每次迭代构造全新 Task，以 Loop-only `Checkpoint` 工具提交 completed/open/handoff，
  自动累计预算、生成有界失败摘要，并按 cancel、wall clock、usage、token、round、failure、
  unrecoverable 的稳定边界收敛。
- CLI 新建需要 goal + token budget，resume 只接收 Loop ID；首次 SIGINT 请求协作取消，二次
  SIGINT 保留强制退出。HTTP 保持单 endpoint，通过严格 body allowlist 选择 ordinary/new/resume，
  server 持有 root、tier、model、identity、credentials 与 checkpoint 路径权限。
- 公开 CLI/HTTP/审计只包含 schema、ID、稳定枚举和计数，不包含 goal、checkpoint 正文、
  handoff、tool 参数、绝对路径、文件内容或 secret。

## 子任务清单

- [x] 实现严格 checkpoint/report/budget 模型、原子 store 与 Loop-only Checkpoint 工具
- [x] 实现 LoopRunner create/resume、累计预算、失败收敛、取消、审计与资源关闭
- [x] 实现 `forgeagent loop` 新建/resume、参数、输出、退出码和 SIGINT 语义
- [x] 扩展既有 HTTP `/tasks` 支持普通 Task、新 Loop 与 resume Loop
- [x] 添加 cron/launchd/systemd、HTTP 与只报告依赖状态的安全示例
- [x] 完成逐任务审查、全变更终审、两轮自审、验证、主分支合并与 OpenSpec 归档

## 交付物清单

- [x] `src/forgeagent/loop.py` — checkpoint store、Checkpoint tool、LoopRunner、报告与审计
- [x] `src/forgeagent/cli.py` — CLI Loop 装配、SIGINT 与 client 生命周期
- [x] `src/forgeagent/http_server.py`、`src/forgeagent/http_task_service.py` — HTTP schema、worker 与投影
- [x] `tests/test_loop_checkpoint.py`、`tests/test_loop_runner.py` — 持久化、恢复、预算、竞态和收敛
- [x] CLI/HTTP 集成、文档静态契约和 ordinary-path/Evaluator 隔离回归
- [x] README、文本协议、威胁模型、golden 边界、外部调度示例和验证报告

## 三次评审

### 技术方案评审

- [x] 对照 ACTION_PLAN M21、OpenSpec proposal/design/specs 与技术 Design Doc 核对全部范围。
- [x] 方案保持 Task 上层串行控制器，没有序列化 conversation/runtime/blocks 或引入通用 workflow。
- [x] M20 Evaluator 保持 opt-in，M22 Planner/Generator/Evaluator 打回与完成语义未提前实现。

### 代码评审

- [x] 每个实现任务均由独立 reviewer 审查，安全任务采用高强度审查和 TDD fix/re-review。
- [x] 修复 checkpoint token/Unicode/schema、symlink/目录 TOCTOU、fd 复用/换绑等耐久边界。
- [x] 修复零 usage、失败证据、预算优先级、MCP/Skills 装配、SIGINT、审计字段与 client close。
- [x] 修复 HTTP terminal/cancel 线性化竞态；最终完整 reviewer 结论为 no Critical/Important findings。

### 验收评审

- [x] 完整回归：`1758 passed, 11 skipped`；归档提交后专项：`462 passed`。
- [x] trusted golden：`20/20 passed (100.0%)`；Ruff format/check 与 diff check 通过。
- [x] wheel/sdist 构建成功；OpenSpec strict 在归档前后均为 `16 passed, 0 failed`。
- [x] OpenSpec archive 7/7 steps succeeded，主 specs 已合并，归档状态 `archived: true`。
- [x] 修正归档后 ACTION_PLAN 静态契约测试仍要求“进行中”的收尾遗漏，并重跑完整门禁。

## 遗留问题

- [ ] Checkpoint 只保证提交边界，不保证外部副作用 exactly-once — 影响：最后一次提交之后的副作用可能在恢复时重做 — 计划：保持显式契约，出现真实需求时另立 change。
- [ ] CLI 同一 checkpoint 的跨进程重叠没有全局锁 — 影响：并发进程可能发生 revision 冲突 — 计划：调度示例禁止重叠；HTTP 单进程已拒绝 same-ID overlap。
- [ ] 墙钟和 SIGINT 只能协作取消 — 影响：在途 provider/tool 调用无法强杀 — 计划：继续在安全边界持久化，不伪造硬截止。

## 续接指引

M21 已实现、验证、合并 `main` 并归档。下一计划里程碑是 M22 运行时 Duo/Triad：阶段一引入
Generator + 独立 Evaluator 的打回环并改变 Duo 模式完成语义；阶段二增加 Planner 清单、用户
确认门和编程类任务路由。启动 M22 前先读取 `TECH_PATH.md` §三 M22，并保持 M21 checkpoint/
handoff 仅作为角色交接载体、普通单角色路径零变化、Evaluator 真实模型成本显式可控。
