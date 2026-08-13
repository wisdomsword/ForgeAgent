# 里程碑 M51: 安全与契约加固

- 状态: 已完成并归档
- 起止: 2026-08-12 ~ 2026-08-13
- 对应 ACTION_PLAN 行: M51
- 前置里程碑: [milestone_050](milestone_050.md)
- 实施计划: [M51 hardening plan](../docs/superpowers/plans/2026-08-12-milestone-051-hardening.md)
- 验证报告: [M51 verification](../docs/superpowers/reports/2026-08-13-milestone-051-hardening-verify.md)

## 目标与范围

修复评审清单 S1-S14，并完成 Phase 0-5：restricted 写边界与资源限额、WebFetch 完整 URL 授权、严格配置输入、完成语义与图片输入一致性、稳定错误/协议边界、存储多进程准入，以及不改变行为的低耦合结构拆分。所有变更均通过 Comet/OpenSpec 生命周期并归档；不扩大到 OS 密封沙箱、NFS/断电耐久性或发布自动化。

## 方案设计

- S1 只限制 restricted 的写入路径，保留 runtime prefix 读权限以支持 import；`.pth` 与 worker 自身写入均拒绝。
- WebFetch 授权键绑定规范化 origin/path 加原始 query 的稳定摘要，初始请求和每次 redirect 都重新校验，明文 query 不落配置。
- 每份 YAML 在 merge 前校验根、顶层和嵌套结构；模型入口 `extra="forbid"`，MCP 启停字段严格布尔，temperature 使用 `FiniteFloat`。
- restricted 限额由配置和 CLI 覆盖，信号反馈保留有界 stdout/stderr；TaskStatus 以不可变三态投影兼容旧布尔字段。
- 图片目录复用单文件加载，先 stat/有界头部识别，识别出的超限图片整体失败；模型组显式 models 替换列表；TTL 使用 monotonic。
- protocol/step/MCP/collaboration 采用 facade/re-export 的纯移动与小函数提取；存储锁以多进程、SIGKILL 和父目录 fsync 证据作为准入。

## 子任务清单

- [x] 删除 4 个与 archive 重复且无独有内容的 active change，锁定直接依赖上界并更新 `uv.lock`。
- [x] 完成 S1-S14 安全、输入、反馈和语义修复及回归测试。
- [x] 完成 collaboration/memory 多进程竞争、SIGKILL 恢复和原子替换耐久性步骤的本地 POSIX 证据。
- [x] 完成 protocol → step → MCP → collaboration 结构拆分，保留公共 facade。
- [x] 11 个 Comet change 全部 verify/pass/archive，并同步主 specs。
- [x] 完成两轮自我审查和独立只读复核；发现问题均修复并重跑覆盖验证。

## 交付物清单

- [x] `src/forgeagent/_sandbox_worker.py`、`executor.py`、`sandbox.py` — restricted 写边界、限额配置和稳定资源反馈。
- [x] `src/forgeagent/headless.py`、`http_action_approvals.py`、`model_registry.py`、`mcp_manager.py`、`models.py` — URL 授权、严格配置、有限温度和 monotonic TTL。
- [x] `src/forgeagent/task.py`、`image_input.py`、`protocol.py`、`step.py`、`transport_errors.py` — 三态完成、图片失败语义和稳定协议错误。
- [x] `src/forgeagent/protocol_text.py`、`step_types.py`、`mcp_config.py`、`collaboration_routing.py` — 低耦合内部边界与兼容 facade。
- [x] `src/forgeagent/collaboration.py`、`memory.py`、`tests/test_storage_process_safety.py` — 锁覆盖、SIGKILL 恢复和父目录 fsync。
- [x] `openspec/changes/archive/2026-08-12-*/` — 11 个已归档 change 及 delta spec。
- [x] `milestones/milestone_051.md`、`milestones/latest`、`ACTION_PLAN.md`、`docs/README.md`、`docs/threat-model.md` — 当前状态和安全边界文档。

## 三次评审

### 技术方案评审

- [x] 对照 M51 计划逐项复核：P0/P1 先于语义和拆分，存储多进程证据先于结构移动，C901 仅 report-only。
- [x] 未新增依赖、manager/factory/framework 抽象或发布面；restricted 仍明确为应用层隔离。

### 代码评审

- [x] 两轮全 diff 自审完成。
- [x] 独立只读复核完成；发现并修复 canonical spec 占位 Purpose、图片增长后的无界读取、内置配置错误来源丢失、TaskStatus 终态投影可变四项问题。
- [x] 修复后的核心回归 `605 passed, 1 skipped`；全量回归最终 `3055 passed, 11 skipped`。

### 验收评审

- [x] Golden `20/20`；`uv lock --check`、`uv build`、Ruff check/format、`git diff --check` 通过。
- [x] 归档前 OpenSpec `51/51`，归档后 `42/42`；11 个 change 均 `verify_result: pass`、`archived: true`。
- [x] 存储准入仅声明本地 POSIX 进程锁、SIGKILL 恢复和父目录 fsync 证据，不外推 NFS 或断电耐久性。

## 遗留问题

- [ ] restricted 仍是 Python 应用层隔离而非 OS 密封沙箱 — 影响：native/kernel 技术与受损解释器仍可能绕过 — 计划：只有出现真实需求时另立 container/OS 隔离 change。
- [ ] C901 仍有既有复杂函数 — 影响：静态复杂度报告未全绿 — 计划：沿用 report-only，结构拆分收敛后另立维护性 change。
- [ ] NFS、断电恢复和 Windows 原生 rlimit 未在本里程碑证明 — 影响：跨平台/非本地文件系统保证有限 — 计划：在目标平台和真实部署需求出现时补专门验证。

## 续接指引

M51 已完成并归档，下一阶段从 `ACTION_PLAN.md` 与本文件开始。继续保持：配置严格拒绝未知输入，restricted/container 权限边界不放宽，TaskStatus 三态与兼容布尔投影一致，HTTP 仍 loopback-only；新的跨平台、OS 隔离、NFS 或发布需求必须另立 Comet change，不把本里程碑的本地 POSIX 证据扩张为更强承诺。
