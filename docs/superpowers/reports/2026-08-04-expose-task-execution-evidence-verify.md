# expose-task-execution-evidence 验证报告

日期：2026-08-04  
基线：`cf51c632a71fa810f81397401d215c8990f1c4ee`  
验证模式：full

## 结论

PASS。11/11 OpenSpec 任务完成，4 个 delta capability 的 Requirement 与 Scenario 均有实现和测试证据；最终 whole-change 审查无 P0-P2 finding，可以进入本地合并与归档。

## 完整性

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| OpenSpec tasks | PASS | 11/11 `[x]` |
| Superpowers plan | PASS | 8 个 Task 的全部 Step 已完成 |
| Proposal 目标 | PASS | Task/CLI/HTTP/Loop/Duo/Triad 均提供终态执行证据 |
| Delta specs | PASS | 4 个 capability、8 个 Requirement、35 个 Scenario 已映射到测试 |
| Design Doc | PASS | 技术设计存在且实现遵循任务级 recorder、制品 store、安全投影和 durable 聚合决策 |

## 正确性与安全

- 内部 recorder 最多 128 条；公开与 durable 投影最多 32 条，并维护稳定 `omitted_count`。
- 程序制品最多 100 个，单文件 1 MiB，总量 8 MiB；使用 descriptor-relative、no-follow、原子发布、identity recheck 和稳定失败状态。
- named、inline、Edit 后 Exec 以及 trusted/restricted/container 均先持久化再 dispatch；持久化失败时 backend 不执行。
- Task 的制品 store 延迟初始化；根目录缺失、执行前消失或容量失败均产生 `artifact_persistence_failed` 终态证据。
- CLI 仅显示可安全解析的本地路径；HTTP 仅显示 canonical relative reference，且未增加制品下载 route。
- 公开和 durable evidence 不包含模型控制的 block、代码、参数、prompt、异常正文、secret 或非本地绝对路径；Rich 输出按字面渲染。
- Loop 保持 iteration 来源、恢复前缀和累计协作去重；Duo/Triad 的 role submission、counter、usage 与 evidence 单次原子保存。
- 旧 Task/Loop/Collaboration payload 通过加法式空默认保持兼容；既有 acceptance `evidence` 字段未改名。

## 测试与静态检查

| 命令 | 结果 |
| --- | --- |
| Task 8 精确受影响集合 | `1007 passed, 10 skipped` |
| 最后 lazy-store 修复后的核心集合 | `736 passed` |
| 沙箱内全量 `pytest -q` | `2921 passed, 23 skipped, 15 failed`；15 条仅因 loopback bind 或 `uv build` 权限被 sandbox 拒绝 |
| 沙箱外精确重跑上述失败集 | `16 passed` |
| `ruff format --check .` | `149 files already formatted` |
| `ruff check .` | `All checks passed!` |
| `openspec validate expose-task-execution-evidence --strict` | valid |
| `git diff --check` | PASS |

全量测试的 15 条失败不属于实现失败：11 条 M16 loopback 黑盒、2 条 M28 loopback smoke、1 条 M44 loopback smoke、1 条 packaging build。允许所需权限后，包含这些场景的精确集合共 16 条全部通过。

## 审查记录

- Task 级审查发现并修复：Rich markup 注入、Loop 累计 omitted 重复计数、Collaboration 成功边界非原子、公开 block 泄露、CLI 反向依赖、LoopReport 基线漂移。
- whole-change 审查发现并修复：Task 急切初始化制品 store，以及 lazy wrapper 的类型契约不一致。
- 最终 whole-change 复审结论：无 P0-P2 finding，APPROVE。

## 使用的工具与程序路径

- Comet 状态与阶段门禁：`~/ForgeAgent/.agents/skills/comet/scripts/comet-state.mjs`、`~/ForgeAgent/.agents/skills/comet/scripts/comet-guard.mjs`
- Subagent 任务与审查包：`~/ForgeAgent/.agents/skills/subagent-driven-development/scripts/task-brief`、`~/ForgeAgent/.agents/skills/subagent-driven-development/scripts/review-package`
- 测试与检查：`uv`、`pytest`、`ruff`、`openspec`、`git diff --check`
- 核心新增程序：`~/ForgeAgent/.worktrees/m48-expose-task-execution-evidence/src/forgeagent/execution_evidence.py`
- 运行时接入程序：`src/forgeagent/tools.py`、`src/forgeagent/step.py`、`src/forgeagent/task.py`
- 入口与聚合程序：`src/forgeagent/cli.py`、`src/forgeagent/http_task_service.py`、`src/forgeagent/loop.py`、`src/forgeagent/collaboration.py`、`src/forgeagent/_cli_collaboration.py`

## 残余风险

无已知 correctness/security 阻塞项。程序制品读取端点、自动清理和跨任务任意工具输出归档仍按设计明确为非目标。
