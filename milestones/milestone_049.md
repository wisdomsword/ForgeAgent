# 里程碑 M49: REPL 会话连续性与执行智能收敛

- 状态: 已完成并归档
- 起止: 2026-08-05 ~ 2026-08-06
- 对应 ACTION_PLAN 行: M49（本里程碑新增）
- 前置里程碑: [milestone_048](milestone_048.md)
- OpenSpec changes: `retain-repl-session-history`、`improve-context-limits-and-execution-guidance`

## 目标与范围

修复真实使用中 REPL 多轮失忆、执行型目标被 prose/单层工具草草收尾和长结果截断难读的问题。每条 `forge>` 输入在 `/new` 或 `/reset` 前携带完整会话历史；每轮仍创建 fresh Task、刷新 system/runtime authority，并保持文件系统授权与工具收据的任务边界。反馈限额由统一 resolver 计算并在交互边界可见；项目外配置中的两条过低显式限额按用户裁决删除，回落到自适应默认。固定协议按完整目标路由 Survey、直接内置工具和 Python/Exec，并要求大结果写入获准文件后报告完整摘要。

不扩大 HTTP schema、非交互输出、工具协议参数、sandbox 权威、网络边界、依赖或发布目标；不读取或回显用户配置中的 API key。

## 方案设计

- REPL 保存进程内 transcript；每个顶层输入创建新 Task，并把历史作为上下文而非权限或运行时状态。`/new` 与 `/reset` 清除 transcript 和暂存图片，但保留模型、sandbox、Memory、MCP 与累计 usage。
- Context policy 继续保留 system、首个 user 和完整 assistant/user 单元，避免拆分工具反馈；Task/Step 只把安全、有界的会话投影传回下一次输入。
- `ResolvedFeedbackLimits` 是 policy、HTTP 校验和 REPL 展示的唯一解析结果；显式值仍优先，但低于当前模型 adaptive 值时只告警，不静默覆盖。
- 启动、成功 `/model` 和成功 `/reload` 显示 effective round/tool 限额；非交互路径保持安静，模型/reload 失败保留旧状态。
- 协议按完整目标选择：缺少必要信息先 Survey 并在同一 Task 续接；单个直接工具能完成整个目标时使用该工具；递归、内容哈希、聚合、转换、跨文件比较或大量结果使用 Python/Exec，并将完整结果写到获准路径。

对应设计与验证文档：

- [REPL 会话设计](../docs/superpowers/specs/2026-08-05-retain-repl-session-history-design.md)
- [REPL 会话验证报告](../docs/superpowers/reports/2026-08-05-retain-repl-session-history-verify.md)
- [反馈限额与协议设计](../docs/superpowers/specs/2026-08-05-improve-context-limits-and-execution-guidance-design.md)
- [反馈限额与协议验证报告](../docs/superpowers/reports/2026-08-06-improve-context-limits-and-execution-guidance-verify.md)

## 子任务清单

- [x] 完成 Task/Step/context 的会话历史传递、严格轮次配对校验和安全终态投影。
- [x] 完成 Single/REPL/协作入口的连续会话与公开协作结果投影。
- [x] 完成 `/new`、`/reset` 管理命令及状态保留/清除回归测试。
- [x] 完成共享反馈限额 resolver、交互限额摘要、低值告警与非交互静默门。
- [x] 完成 Survey → Exec → 文件交付的协议指引和 mock replay 回归。
- [x] 完成外部配置的授权两行删除、自适应加载验证、专项/全量/真实模型 smoke 与 OpenSpec 归档。

## 交付物清单

- [x] `src/forgeagent/task.py`、`src/forgeagent/step.py`、`src/forgeagent/context.py` — 新 Task 的 fresh authority、会话配对校验与受控历史传递。
- [x] `src/forgeagent/cli.py` 及 REPL 辅助模块 — 完整历史、协作投影、`/new`/`/reset` 和交互限额状态。
- [x] `src/forgeagent/context.py`、HTTP 配置校验与相关测试 — 统一 `ResolvedFeedbackLimits` 解析，保持 HTTP schema 兼容。
- [x] `src/forgeagent/res/prompts/protocol.md`、`tests/test_task.py` — 完整目标路由、同 Task Survey 续接和 Exec 文件交付 replay。
- [x] [REPL 会话验证报告](../docs/superpowers/reports/2026-08-05-retain-repl-session-history-verify.md)。
- [x] [反馈限额与协议验证报告](../docs/superpowers/reports/2026-08-06-improve-context-limits-and-execution-guidance-verify.md)。
- [x] 两个归档 change：`openspec/changes/archive/2026-08-05-retain-repl-session-history`、`openspec/changes/archive/2026-08-05-improve-context-limits-and-execution-guidance`。
- [x] `ACTION_PLAN.md`、`milestones/milestone_049.md`、`milestones/latest` — 当前台账和续接指引。
- [x] `docs/README.md`、两份治理基线文档及 `tests/test_borrowing_roadmap.py` — 收尾复核后同步 M49 当前入口与离线契约。

## 三次评审

### 技术方案评审

- [x] 对照两个 design 文档复核：完整历史仅作上下文，fresh Task/authority/授权边界保持不变。
- [x] 对照用户裁决复核：选择模式 2；采用删除两条低值配置并回落 adaptive；启动摘要显示生效上限并对过低显式值告警。
- [x] 复核未扩大 HTTP、非交互输出、工具 schema、sandbox 或发布边界。

### 代码评审

- [x] 已委派独立 subagent 审查相对 `b2716e2` 基线的本里程碑 diff。
- [x] 两轮自评检查 resolver 公式、交互 gating、probe 生命周期、协议 schema、Task 配对和敏感信息边界；独立审查确认未发现 P0/P1/P2 问题，HTTP schema 与工具参数未漂移。
- [x] 修复评审发现的 `_cli_collaboration.py` context-policy 返回值静态注解不一致；协作/CLI/context 回归 `424 passed`。
- [x] 未发现需要回退到 build 或继续修改的 P0-P2 代码问题；配置字节保真残余风险单独记录在“遗留问题”。

### 验收评审

- [x] REPL 会话专项：`736 passed, 10 skipped`，CLI reset 专项 `343 passed`；第二个任务收到完整历史，`/reset` 后恢复干净会话。
- [x] 第二变更专项：`742 passed, 10 skipped`；跨 Task1–3 回归 `547 passed`；Ruff check 和 diff check 通过。
- [x] 真实模型 REPL smoke：同一 session 完成两条输入，重复文件报告为 1 组/2 个文件，审计仅记录 1 次 `Exec`，没有以 FileList 截断片段收尾。
- [x] 完整 pytest 在受限沙箱为 `2953 passed, 23 skipped, 15 failed`；失败均为 loopback/审计临时文件/构建权限限制，对应提升权限集合 `52 passed`。
- [x] `openspec validate --all --strict`：`44 passed, 0 failed`；两个 Comet change 均 verify/pass/archive。
- [x] `mypy src` 未执行成功，原始错误为 `Failed to spawn: mypy`；`ruff format --check` 仅报告第二变更基线已有的 `tests/test_task.py` 格式差异，均已在报告中如实记录。

## 遗留问题

- [ ] 项目外配置修改的非目标字节保真未能证明 — 影响：无法提供修改前后 filtered digest 相等的证据 — 计划：当前目标已满足且未暴露 key；后续若需编辑该配置，必须先获得项目外路径授权并重新设计可审计的字节级修改流程。
- [ ] `mypy` 当前环境不可用 — 影响：静态类型检查未完成 — 计划：在提供 mypy 的 CI/开发环境补跑，不阻塞本里程碑行为验收。
- [ ] 受限沙箱无法验证 loopback、默认外部审计路径和完整 `uv build` — 影响：这些环境边界未在本沙箱直接通过 — 计划：保留失败原样，在具备对应权限的 CI/主机复验。
- [ ] 尚未有独立的真实 TTY 多目标 transcript/context-trim 断言 — 影响：真实 TTY 的完整多目标续接和裁剪组合只由受控 smoke 与非交互回归覆盖 — 计划：在允许默认审计路径写入的环境补跑，不改变当前会话和权限语义。

## 续接指引

M49 已完成并归档，`milestones/latest` 已指向本文件。后续开发先读取本文件与 `ACTION_PLAN.md`，保持 REPL 的完整历史直到 `/new`/`/reset`，同时每轮刷新 Task/system/runtime authority；任何新的会话压缩、摘要或持久化需求必须另立 change，不得把 transcript 变成权限状态。复杂文件任务继续遵循固定协议的 Survey → 同 Task 续接 → Exec/完整文件交付路径；反馈限额继续由共享 resolver 计算，HTTP 和非交互入口保持现有安静/兼容契约。项目外配置仍不应擅自编辑，用户 key 不得读取或回显。HTTP 制品下载、自动清理、外部 listener、发布与远程 push 仍是非目标。
