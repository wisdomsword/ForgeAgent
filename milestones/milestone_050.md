# 里程碑 M50: 外部工具协议恢复与真实执行闭环

- 状态: 已完成并归档
- 起止: 2026-08-06 ~ 2026-08-06
- 对应 ACTION_PLAN 行: M50（本里程碑新增）
- 前置里程碑: [milestone_049](milestone_049.md)
- OpenSpec change: `recover-foreign-tool-protocol`

## 目标与范围

修复真实 REPL 中模型输出其他 coding agent 的 `{"cmd":"..."}` 或 `todo_write` + `Params:` 文本后，ForgeAgent 未执行任何工具却直接以 `answered_in_prose` 软完成的问题。外部工具文本必须进入同一 Task 的可恢复协议反馈环，模型随后只能通过 Forge CodeBlock + Exec 执行；普通知识型 prose 和 fenced 代码示例保持原行为。

不直接执行裸 shell JSON，不实现第三方 agent 工具协议，不新增工具、依赖、配置、CLI/public schema 或权限；sandbox、确认门、审计与执行证据仍由既有 Forge 工具链负责。

## 方案设计

- 根因是 M48 直接 prose 软完成删除了通用纠偏轮，而 M49 仅增强系统提示；`protocol.parse()` 对外部工具正文既无 ToolCall 也无 ParseError，Step 因此终止为 `answered_in_prose`。
- 在 parser 归一化边界识别真实观察到的两类外部文本，生成固定 `INVALID_FORMAT`，复用现有 Step 反馈环；外部 payload 不执行、不回显。
- 使用 `json.JSONDecoder` 解析行边界上的独立 `cmd` 对象，精确识别 `todo_write` + `Params:`；先移除 Markdown fenced 示例，避免破坏知识回答。
- 只覆盖真实样本，不按用户目标关键词猜测执行意图，也不构建通用第三方协议适配层。

对应设计与验证：

- [Hotfix design](../openspec/changes/archive/2026-08-06-recover-foreign-tool-protocol/design.md)
- [验证报告](../docs/superpowers/reports/2026-08-06-recover-foreign-tool-protocol-verify.md)

## 子任务清单

- [x] 完成真实 `cmd`/`todo_write` 样本和 fenced/prose 对照的 TDD RED。
- [x] 完成 parser 最小恢复实现，证明同一 Task 可转入 Forge Exec 并保留执行证据。
- [x] 完成聚焦、相关、完整、真实模型、构建、Ruff 与 OpenSpec 验证并归档 change。

## 交付物清单

- [x] `src/forgeagent/protocol.py` — 外部工具正文的固定、非执行型 ParseError 恢复。
- [x] `tests/test_protocol.py`、`tests/test_task.py` — 两类真实样本、fenced 对照和 Task→Exec 证据回归。
- [x] `docs/text-protocol-spec.md`、`openspec/specs/completion-integrity/spec.md` — 运行时协议和主规格同步。
- [x] `openspec/changes/archive/2026-08-06-recover-foreign-tool-protocol/` — 完整 Comet/OpenSpec 生命周期工件。
- [x] `docs/superpowers/reports/2026-08-06-recover-foreign-tool-protocol-verify.md` — 三维验证、真实 smoke 与构建证据。

## 三次评审

### 技术方案评审

- [x] 达成既定目标：真实外部工具文本不再被接受为普通 prose，而是反馈到同一 Task。
- [x] 未偏离安全设计：裸命令不执行、不转换为工具，仍需注册 ToolCall、schema、sandbox 和审计。
- [x] 普通 prose、fenced 示例、原生 tool calls 与 Forge ToolCall 兼容边界均有现有或新增测试。

### 代码评审

- [x] Comet `review_mode: off` 按 hotfix 预设跳过自动 subagent 审查；按用户要求完成两轮自评。
- [x] 第一轮检查执行绕过、payload/secret 回显和错误反馈边界；未发现问题。
- [x] 第二轮检查 JSON 终止条件、Markdown fence 排除、重复错误和既有 parser 顺序；未发现 P0-P2 问题。

### 验收评审

- [x] TDD RED 为 `4 failed, 1 passed`，GREEN 为 `5 passed`；相关回归 `531 passed`。
- [x] 完整 pytest `2985 passed, 11 skipped`；归档后相关/文档回归 `129 passed`；Ruff、diff check 通过；OpenSpec strict 归档前 `45/45`、归档后 `44/44`。
- [x] `uv build` 在开放网络后成功生成 sdist/wheel；初次沙箱 DNS 失败如实记录。
- [x] 真实模型 REPL smoke：`tools=Exec`、`completed=1`、`answered_in_prose=0`，结果包含两个重复文件路径；临时程序制品已清理。
- [x] Comet verify/pass/archive 完成，归档脚本 `5/5 steps succeeded`。

## 遗留问题

- [ ] 未观察到的其他第三方 agent 文本工具格式仍可能落入 prose 软完成 — 影响：本 hotfix 只保证用户提供的 `cmd` 和 `todo_write` 两类真实样本 — 计划：仅在取得新的真实失败样本后扩充 parser 与回归，避免脆弱的通用猜测器。

## 续接指引

M50 已完成并归档，`milestones/latest` 指向本文件。后续若再次出现“answered in prose, not executed”，先保存模型原始正文和 execution evidence，区分普通知识回答、供应商原生 tool call、Forge ToolCall 与新的第三方文本 envelope；只有取得真实样本后才扩充恢复识别。不得直接执行裸 `cmd`/shell 文本或用目标关键词取代协议边界。M49 的 REPL 完整历史、adaptive 限额和复杂任务 Exec 路由继续有效；HTTP 公网入口、自动清理、正式发布和远程 push 仍是非目标。
