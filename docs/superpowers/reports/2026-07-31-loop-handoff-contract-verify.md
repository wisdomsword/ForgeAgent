# Loop handoff contract 验证报告

- 变更：`loop-handoff-contract`
- 里程碑：M40
- 日期：2026-07-31
- 验证模式：full

## 结论

M40 的实现符合结构化 Loop handoff、旧 checkpoint 兼容迁移、宿主控制面保护和有界非重放恢复契约。普通 Task/Collaboration 保持一次提交恢复的兼容默认值，CLI/HTTP 的 Loop-owned Task 显式使用两次上限，避免改变独立 Collaboration 的既有失败语义。

## 契约核对

- `LoopCheckpoint.handoff` 是冻结的 `LoopHandoff`，包含有界 `completed_items`、`open_questions` 与 `summary`。
- `CheckpointArgs` 的公开 schema 只暴露上述候选字段；额外 goal、budget、permission、status、stop reason、collaboration、plan、attention 或 recovery 字段被拒绝。
- 旧字符串 handoff 和旧顶层列表只在校验边界迁移；新 JSON 写入嵌套结构并继续使用公开 `schema` 键。
- 已完成项不可删除；Checkpoint 成功反馈只公开 revision 和计数，不回显 handoff 正文。
- 下一轮只接收标记为 `UNTRUSTED LOOP STATE` 的结构化 JSON，公开报告和审计只包含计数。
- 提交恢复由宿主计数并有限终止；恢复消息不重放历史 tool call，外部动作仍受 receipt 安全边界约束。

## 自评与修正

- 第一轮按模型候选、宿主持久化、提示投影和公开审计四个信任边界检查，未发现模型可修改控制面字段的路径。
- 第二轮逐条对照 OpenSpec 场景和向后兼容测试，保留隐藏的 deprecated `handoff` 输入别名以兼容历史调用方；工具 schema 与新持久化格式仍只使用 `summary`。
- 全量回归首次发现把两次恢复设为全局默认会改变独立 Collaboration 的失败语义；已改为默认一次、Loop 入口显式两次。
- 恢复工作区原有改动后的专项复验发现一处错误的 CLI `CollaborationStore(receipt_store=...)` 参数；已撤销该误恢复，原有五处 receipt 投影改动保持未提交。

## 验证证据

- Loop/Step/CLI/Task/Collaboration 专项：`550 passed`。
- 全量 pytest：`2534 passed, 10 skipped in 164.56s`。
- `uv run ruff check .`：通过；`uv run ruff format --check .`：`129 files already formatted`。
- `uv build`：成功生成 sdist 与 wheel；未上传产物。
- OpenSpec strict：verify 前 `31 passed, 0 failed`，归档后结果记录在 M40 里程碑。
- `git diff --check`：通过。

## 范围与边界

未新增依赖，未引入调度器、事件溯源、LLM 自动摘要或动作自动重放。未执行包索引上传、tag、push 或发布自动化。
