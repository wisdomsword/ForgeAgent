# 里程碑 M40: Loop handoff contract

- 状态: 已完成
- 起止: 2026-07-31 ~ 2026-07-31
- 对应 ACTION_PLAN 行: M40（见该文件 §四里程碑表）
- 前置里程碑: [milestone_039](milestone_039.md)
- 分发边界: 包索引发布、tag、push 和发布自动化不在当前目标中

## 目标与范围

将 Loop handoff 从模型可写自由字符串收敛为宿主拥有的结构化状态；旧 checkpoint 继续可加载，模型只能提交有界状态候选，不能改变目标、权限、预算、协作冻结状态、终态或恢复语义。提交恢复允许 Loop 有限纠正，但不得自动重放历史工具或外部动作。

## 方案设计

- `LoopHandoff` 是冻结且禁止额外字段的持久化事实源，包含 `completed_items`、`open_questions` 和 `summary`。
- `CheckpointArgs` 是独立候选模型；公开工具 schema 只暴露三项候选字段，旧 `handoff` 仅作为隐藏的 deprecated 输入别名兼容历史调用方。
- 旧 checkpoint 的字符串 handoff 与顶层列表在加载时合并；冲突投影 fail-closed，新写入只使用嵌套结构并保持公开 `schema` 键。
- `completed_items` 只增不减；下一轮提示把结构化 JSON 标记为不可信状态，公开报告与审计只给出计数。
- 普通 Task/Collaboration 保持一次恢复，CLI/HTTP 的 Loop-owned Task 显式允许两次；达到上限后失败，Step 不重放任何历史 ToolCall。

## 子任务清单

- [x] 定义结构化 handoff、旧数据迁移和控制面拒绝契约。
- [x] 收敛 CheckpointTool 写入与 Loop 下一轮提示投影。
- [x] 实现兼容默认值下的 Loop 有界提交恢复。
- [x] 完成专项、全量、静态、构建和 OpenSpec 验证。
- [x] 完成 Comet verify、主规格合并和 change 归档。

## 交付物清单

- [x] `src/forgeagent/loop.py`：结构化 handoff、迁移、候选提交与安全投影。
- [x] `src/forgeagent/step.py`、`src/forgeagent/task.py`、`src/forgeagent/cli.py`：可配置恢复上限和 Loop 显式装配。
- [x] `tests/test_loop_checkpoint.py`、`tests/test_loop_runner.py`、`tests/test_step.py`、`tests/test_cli.py`：兼容、越权、持久化、投影和恢复回归。
- [x] `openspec/specs/loop-handoff-contract/spec.md`、`openspec/specs/loop-execution/spec.md`：归档后的主规格。
- [x] `docs/superpowers/reports/2026-07-31-loop-handoff-contract-verify.md`：验证证据。

## 三次评审

### 技术方案评审

- [x] 两轮方案自评确认模型候选与宿主控制面分离，旧数据只在兼容边界迁移。
- [x] 保留隐藏 deprecated 输入别名，不在新工具 schema 中继续宣传自由字符串。
- [x] 未引入调度器、事件溯源、LLM 自动摘要、新依赖或发布范围。

### 代码评审

- [x] 受本轮禁止启动子代理约束，主 agent 按 base ref 对完整 diff、信任边界和调用路径完成两轮自审。
- [x] 修复全局两次恢复导致独立 Collaboration 行为回归，改为默认一次、Loop 显式两次。
- [x] 修复工作区原有 receipt 改动恢复时误传 CLI Store 参数的问题；用户原有改动保持未提交。
- [x] 修复归档脚本在实施计划正文产生的重复注解。

### 验收评审

- [x] 专项验证：`550 passed`。
- [x] 全量验证：`2534 passed, 10 skipped in 164.56s`。
- [x] Ruff check 通过；format check 为 `129 files already formatted`；`git diff --check` 通过。
- [x] `uv build` 成功生成本地 sdist/wheel，未上传。
- [x] OpenSpec strict 在归档前后均为 `31 passed, 0 failed`；Comet archive `7/7` 通过。

## 遗留问题

无 M40 范围内未完成项。Memory 迁移、Rewrite/依赖门禁和 HTTP 远程动作审批绑定仍是条件触发候选，不因本里程碑自动启动。

## 续接指引

读取本文件与 `ACTION_PLAN.md`。当前 Loop handoff 主规格已归档，下一阶段只在出现真实触发条件或用户明确立项后启动新的独立 Comet change；继续保持分发目标移除，不执行包索引上传、tag、push 或发布自动化。
