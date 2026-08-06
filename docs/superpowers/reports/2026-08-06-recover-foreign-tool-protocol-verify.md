# 外部工具协议恢复 Hotfix 验证报告

## 结论

`recover-foreign-tool-protocol` 的 3 项任务、1 项修改需求和 7 个场景均已实现并验证。未发现 CRITICAL、WARNING 或 SUGGESTION 问题；实现可归档。

## OpenSpec 三维验证

| 维度 | 状态 | 证据 |
| --- | --- | --- |
| 完整性 | PASS | tasks `3/3`；修改需求 `1/1` |
| 正确性 | PASS | 场景 `7/7` 有实现或回归测试覆盖 |
| 一致性 | PASS | parser 边界、结构化 JSON 解码、fence 排除、固定错误反馈均符合 design |

### 需求与实现映射

- `src/forgeagent/protocol.py` 在协议解析入口排除 Markdown fenced 示例，识别独立 `cmd` JSON 和 `todo_write` + `Params:`，只生成固定 `INVALID_FORMAT` 错误，不执行或回显裸命令。
- `tests/test_protocol.py` 覆盖两类真实外部格式和 fenced 对照。
- `tests/test_task.py` 证明两类错误均在同一 Task 进入反馈轮，随后执行 Forge `Exec`、以 `completed` 结束并留下执行证据。
- 既有 prose、流式去重、required completion tool、工具/解析反馈测试继续覆盖修改需求中保留的原场景。
- Hotfix 预设不要求独立 Superpowers Design Doc；本 change 的 `design.md` 已完整记录安全边界和取舍，实现无偏离。

## 验证证据

- TDD RED：新增聚焦测试为 `4 failed, 1 passed`；失败原因分别是 parser 未产生错误、Task 仅调用模型 1 次即 `answered_in_prose`。
- TDD GREEN：相同聚焦测试 `5 passed in 0.11s`。
- protocol/Step/Task/CLI 相关回归：`531 passed in 3.33s`。
- 完整 pytest：`2985 passed, 11 skipped in 159.29s`。
- Ruff：`ruff check src tests scripts` 通过。
- OpenSpec strict：`45 passed, 0 failed`。
- `git diff --check`：通过。
- `uv build`：受限沙箱首次因 PyPI DNS 无法获取 `hatchling` 失败；开放网络后成功生成 `forgeagent-0.1.0.tar.gz` 和 `forgeagent-0.1.0-py3-none-any.whl`。
- 真实模型、restricted sandbox、项目内审计的 REPL smoke：`prompt_count=2`、`tools=Exec`、`completed=1`、`answered_in_prose=0`、`stopped=0`、`alpha_mentions=2`、`beta_mentions=2`、`reports=0`。模型实际生成并执行 SHA-256 重复文件扫描程序，临时 fixture、审计和程序制品均已清理。
- 安全检查：diff 未新增 API key、secret、password、`subprocess`、`os.system` 或 `shell=True`；外部工具 payload 仅产生固定错误。

## 审查

Comet `review_mode: off`，因此按预设跳过自动代码审查。两轮自评分别检查了执行绕过/secret 泄露边界，以及普通 prose/fenced 示例/原生 tool calls/Forge ToolCall 的兼容性；未发现需要回退 build 的问题。

## 分支处理

保留 `codex/improve-repl-session-intelligence` 分支，不合并、不 push、不删除。该选择不扩大远程或主分支状态。

## 最终评估

All checks passed. Ready for archive.

## 归档后补充

- Comet archive：`5/5 steps succeeded`，主 `completion-integrity` spec 已按 MODIFIED 语义同步。
- 归档后相关/文档回归：`129 passed in 2.51s`；Ruff 与 diff check 通过。
- 归档后 OpenSpec strict：`44 passed, 0 failed`；active change 已消失，归档状态为 `phase: archive`、`verify_result: pass`、`archived: true`。
