# M28 Task 4 实施报告

## 状态

DONE_WITH_CONCERNS

M28 RC 证据、公开基线、验证报告和 milestone 已生成。Task 1-4 的 task-level review、最终整分支
review 与两轮一致性复审均已完成；OpenSpec verify/archive 已完成。完整 pytest 的初始失败已由
tests-only 可移植性合同修正关闭；Docker/Linux 证据未执行，未写成 pass。

## 新鲜证据

- focused RC：JUnit `43 tests, 0 failures, 0 errors, 0 skipped`
- Ruff check：`All checks passed!`
- Ruff format：`119 files already formatted`
- full pytest：`2 failed, 2401 passed, 10 skipped in 169.62s`
- MCP timing 修正后 focused：`2 passed in 0.23s`；MCP suite：`216 passed in 9.28s`
- MCP tests-only 修正后 full pytest：`2403 passed, 10 skipped in 167.99s`
- 最终 full pytest：JUnit `2415 tests, 0 failures, 0 errors, 10 skipped`，即 `2405 passed, 10 skipped`
- 安全 cache 修正后最终 full pytest：JUnit `2419 tests, 0 failures, 0 errors, 10 skipped`，即 `2409 passed, 10 skipped`
- Golden：exit 0，`20/20 passed (100.0%)`
- OpenSpec strict：`22 passed, 0 failed`
- build：唯一 `forgeagent-0.1.0-py3-none-any.whl` 与 sdist 成功
- RC harness：exit 0；Python 3.11.15，最终 wheel SHA-256
  `44c5123b6ccc64ef69e15c9aefb9b8151cab7aed4e39eb622fbf046a2f0c04ba`，六项全 passed
- docs/continuous/collaboration 合同复跑：`21 passed in 0.09s`
- final strict 复跑：`22 passed, 0 failed`

## Full pytest 根因调查

失败测试：

- `test_capture_close_returns_before_duplicated_writer_reaches_eof`
- `test_close_wall_clock_is_bounded_by_shutdown_and_join_budgets`

隔离复跑两次均为 2 failed。前者约 0.25004 秒，后者约 0.14771-0.18022 秒；本机
`sleep(0.01)` 实测 0.0238-0.0901 秒。M28 merge-base 到 HEAD 对 MCP source/test diff 为空。
结论：旧绝对墙钟 slack 在当前宿主调度下稳定不成立；没有在 Task 4 越界修改 MCP，也没有把失败
冒充为环境 pass。

提交 `83ba892` 仅修改 `tests/test_mcp_manager.py`，用确定性 probe 保留相同的 timeout/budget 行为
合同；生产 MCP 代码不变。修正后 focused 2、MCP 216 和全量 2403 均通过，首次失败历史仍保留。

## Docker 阻塞

Docker client 29.2.1 存在，daemon preflight 返回：

```text
Cannot connect to the Docker daemon at unix:///Users/admin/.docker/run/docker.sock.
```

按 brief 未启动 Docker Desktop。因此十项 container integration 和 Linux-container RC smoke
未执行；M28 required GitLab job 保持 configured/pending。

## 交付文件

- `docs/superpowers/reports/2026-07-29-m28-v0-1-release-candidate-verify.md`
- `milestones/milestone_028.md`
- `milestones/latest`
- `ACTION_PLAN.md`
- `README.md`
- `docs/platform-support.md`
- `docs/releases/0.1.0-rc.md`
- `openspec/changes/m28-v0-1-release-candidate/tasks.md`

OpenSpec 5.1-5.3 已按 build 工作完成勾选：本机验证、最终审查/两轮复审、报告/milestone/台账与
归档输入均已就绪。实际 spec 同步、`milestones/latest` 切换和 change 移动仍由 Comet archive gate
执行，未在 build 阶段冒充归档完成。

提交：`37365bd`（`chore: close M28 release candidate milestone`），精确包含上述八个允许的
证据/台账文件；本报告与 Comet progress 未纳入提交。

## 文档合同调试

首跑为 `2 failed, 19 passed`，根因是 README 移除了既有静态合同要求的结构化 baseline 行；补回
实际完成计数并紧邻标记 `2 failed` 后，第二轮还暴露平台矩阵相同结构合同。最小修复后 fresh
结果为 `21 passed`，没有弱化测试或隐藏 full-suite failure。

## 风险信号

- 跨模块：YES；本任务只更新证据文档和 lifecycle checklist，未改产品代码。
- 安全/API/并发：NO 新增；既有 harness 风险由 Task 1-3 review 覆盖。
- 外部环境：YES；Docker daemon 不可用，Linux job 无当前执行证据。
- 完整门禁：CLOSED；全部修正与新增回归后最终 full pytest `2409 passed, 10 skipped`。
- 大 diff：YES；验证报告和 milestone 需要完整场景映射，但没有新增抽象或依赖。

## Task Review Fix

Reviewer 指出的 lifecycle gate 问题已按限定范围修正：M28 改回进行中（RC 工程冻结，非正式发布），
`milestones/latest` 恢复指向 `milestone_027.md`，ACTION_PLAN 不再宣称 M28 完成；正式发布的 full
pytest 条件收紧为全绿，或失败经已批准 change 明确裁决并关闭后重跑验证。milestone/verify report
补入 Task 1-4 关键提交 provenance，Task 4 plan Steps 1-4 按实际已执行状态勾选；OpenSpec 5.2/5.3
保持 pending。本节仅记录 review fix，继续保持本报告不纳入提交。

## MCP 修正后证据刷新

提交 `521bb49`（`docs: refresh M28 verification baseline`）保留首次 full-suite 失败与复现历史，新增
`83ba892` tests-only 修正 provenance 和当时新鲜的 `2403 passed, 10 skipped` 基线。milestone 的完整
pytest 项已关闭；M28 仍为进行中，current Linux required job、最终 review/archive 和另行授权的
tag/上传仍开放。文档/continuous/collaboration 合同 `21 passed in 0.09s`，OpenSpec strict
`22 passed, 0 failed`，`git diff --check` 通过。

## Task Review Round 2

修正后复审发现一项 Important provenance 问题：公开 SHA 对应的 wheel 构建早于 `521bb49`，但
wheel METADATA 会嵌入 README，因而该 artifact 仍携带旧 M27 基线，不能作为当前候选。修复策略是
从当前 README 重建唯一 wheel/sdist、检查嵌入 metadata、用 Python 3.11 重跑六项 harness 并刷新
公开 SHA。复审同时指出 Task 4 plan Step 3 要求 `milestones/latest` 指向 M28，在最终 lifecycle
收口前不得提前勾选；现已恢复为 pending。

按复审要求从 `e2e1255` 当前 README 重建 wheel/sdist；wheel METADATA 与 sdist PKG-INFO 均包含
`2403 passed, 10 skipped`、OpenSpec `22/22` 与 M28 RC `43 passed`，不再携带旧 M27 基线。正确的父
流程由开发环境 `uv run python` 驱动，并将 clean venv 解释器固定为 Python 3.11.15；六项 JSON
全 passed，当时的 SHA 为 `e09507e4ea14023ba9833d7ecb9a57cd89de310d8070225429fcbc371d66492c`。
focused 四文件合同复跑 `41 passed`。一次直接用裸 Python 3.11 启动父脚本因开发依赖不可导入而
失败，确认是调用方式偏离实施计划，随后用计划命令成功重跑；未把该误调用记作候选失败。
原复审者对 `6be9f6a` 做定点复核后返回 `FIX_CONFIRMED`；Task 4 review gate 已关闭。

## Final Review Round 1

整分支终审无 Critical，发现一项 Important：默认 `urlopen()` 会读取宿主代理变量，使 loopback HTTP
smoke 可能经外部代理或因代理失败，违反离线确定性合同。新增 hostile-proxy 回归后 RED 为 `1 failed`
（请求确实转向 `127.0.0.1:1`）；最小修复改用标准库 `build_opener(ProxyHandler({}))` 固定禁代理。
GREEN 为 focused `1 passed`、HTTP/协作相邻 `184 passed`，Ruff、format 与 diff check 均通过。
原终审者对 `001a6fa` 定点复核后返回 `FIX_CONFIRMED`；整分支无未解决 Critical/Important。

## 两轮最终一致性复审

第一轮逐项核对 proposal、delta spec、Design Doc、计划、公开证据与 lifecycle。期间怀疑代理修复会
改变 wheel SHA；重建后确认仓库级 `scripts/` harness 不进入 wheel/sdist，候选字节和 SHA 保持
`e09507e4...d66492c`。仍用修复后的 harness 对该候选重跑 Python 3.11.15 六项并全部通过。归档前
`milestones/latest` 保持 M27；plan/OpenSpec 将 build 工作表述为准备完整归档输入，实际指针切换和
change 移动留给 archive gate。

第二轮检查安全、失败路径与范围克制：没有新增依赖、产品 API、运行时配置或 `src/forgeagent`
变更；HTTP client 明确禁用 ambient proxy，CI wheel 数量/bootstrap/JSON 均 fail-closed，报告无
credential/目标/绝对临时路径；merge-base diff 不含用户已有未跟踪路径。没有新发现。

## Verify-Fail Round 1: Golden G14

最终 verify 首次 Golden 为 `19/20`，G14 的 runaway 正确超时，但随后独立 `print` worker 也在
`0.2s` 内未完成。该场景单独连续 5 次与完整 runner 立即复跑均通过，说明旧预算受全量测试后宿主
调度影响。没有把重跑成功直接当作关闭：新增回归在第二个真实 sandbox worker 内注入 `0.3s` 冷启动；
旧 `0.2s` 稳定 RED，G14 将场景专用预算提高到 `1.0s` 后 GREEN。生产 sandbox 默认与实现不变，
无限循环仍真实 timeout/reap。G14/默认 20 场景/离线 main 定向合同 `3 passed, 85 deselected`，Ruff、
format、diff 通过；最终 Golden 20/20 留给重新进入 verify 后的新鲜执行。
原终审者定点复核后返回 `FIX_CONFIRMED`：核心 timeout/feedback/isolation/reap 合同未弱化，无生产
sandbox 变更，也无未解决 Critical/Important。

## Final Verify Round 2

G14 修正后重新进入 verify：focused JUnit 为 `43/0/0/0`，完整 JUnit 为
`2415 tests, 0 failures, 0 errors, 10 skipped`（`2405 passed, 10 skipped`），Golden 为 `20/20`，
Ruff check/format、OpenSpec strict `22/22` 与 build 均通过。最终 README 增加两项回归说明后重建
唯一 wheel/sdist，wheel SHA 为 `44c5123b6ccc64ef69e15c9aefb9b8151cab7aed4e39eb622fbf046a2f0c04ba`，
sdist SHA 为 `c4633dc1efdcbadded25895f6648e9287ce52c1a30535d84de2fdf05064fada3`；两份 metadata 均携带
`2405/10`、`22/22` 与 focused `43`。首次 clean-wheel 因依赖下载超时而失败关闭；同一 wheel 的
新 venv 安装诊断通过，随后原 harness 重跑六项全通过。没有替换候选或隐藏失败历史。

## Merged-Main Verify-Fail: Packaging Bootstrap

本地合并后 full JUnit 为 `2415 tests, 1 failure, 0 errors, 10 skipped`；失败仅来自 packaging 的
clean-venv pip 安装达到旧 `180s` 预算。隔离复跑同样在约 186 秒失败。最小修复没有复用开发环境或
site-packages，而是保留 clean venv 与临时 HOME，把唯一网络安装步骤预算提高到 `600s`，并仅接受
调用者显式提供的绝对、当前 owner、非 symlink、`0700` 私有 cache。首版共享临时 cache 被独立 review
以多用户污染风险退回；relative/symlink/0755 拒绝合同 RED/GREEN 后，最终项目内私有 cache 的真实
packaging 为 `1 passed in 43.36s`。首版修正后的合并结果 JUnit 为
`2415 tests, 0 failures, 0 errors, 10 skipped`（`2405 passed, 10 skipped`，161.412 秒），Ruff
check/format 与 OpenSpec strict `22/22` 通过；随后安全 cache 修正后的最终全量也已通过。

安全 cache 修正经原审查者定点复核返回 `FIX_CONFIRMED`，无剩余 Critical/Important。最终 full JUnit
为 `2419 tests, 0 failures, 0 errors, 10 skipped`（`2409 passed, 10 skipped`，160.623 秒），focused
为 `47 passed`，Ruff check/format 与 OpenSpec strict `22/22` 通过。最终 README 基线重建的唯一
wheel/sdist SHA 分别为 `516fcfbd5dfce141d102d038c1d82e3bf8df71f4d413f22483468387c489a198` 与
`cd205327b4e7ef64672aa548bb1c380d0efc3cd273a2407a7ab70c4744db6444`；metadata 包含最终基线，
Python 3.11.15 六项 harness 全通过。

## Archive Closure

Comet verify guard 全部通过，分支已本地合并到 `main`，feature 分支已删除；归档脚本 `7/7` 成功，
delta spec 已同步到主 specs，design/plan 已标注，change 已移动到
`openspec/changes/archive/2026-07-29-m28-v0-1-release-candidate/`。`milestones/latest` 已切换到 M28。
当前 Linux job 仍 configured/pending，仅阻塞正式 release-ready；未执行 push、tag 或 PyPI 上传。
