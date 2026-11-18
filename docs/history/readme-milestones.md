# README 历史里程碑与验收记录

以下内容从提交 `bde9d22` 的 README 迁出，保留当时的里程碑、评估和验收说明。历史测试数字、授权状态和平台范围只描述记录时的版本，不代表当前状态。当前使用说明见[项目 README](../../README.md)，完整进度见[行动计划](../../ACTION_PLAN.md)与[里程碑目录](../../milestones/)。本页中的命令若需复现实验，应从仓库根目录执行。

## M27 协作路由校准（已完成并归档）

M27 已根据 M25 冻结协议完成路由裁决：默认 Single；用户显式选择 Single、Duo 或 Triad 时直接
遵从，显式模式优先于可信宿主已绑定的冻结检查；只有可信宿主已经为本次任务绑定**非空冻结检查**时，
未显式选择的任务才自动使用 Triad。`has_bound_checks` 是可信宿主的内部事实。HTTP 请求和普通任务请求中出现
`has_bound_checks` 会被严格拒绝；服务器 YAML 中出现它也会被严格拒绝。任务文本不能提供或伪造该事实。
任务文本中的编程特征和候选文件就绪要求都不会
自动升级模式。`allow_weaker_override` 仅为旧配置兼容保留，不再改变路由或要求确认。M25 派生报告
新增误完成率和原样终止原因分类；没有任何任务
类别的 Triad solved rate 严格高于 Single，因此不恢复任何类别的自动 Triad。详见
[`M27 派生报告`](../../docs/evaluation/m25/derived/m27-collaboration-routing/report.md)。

产品 CLI 的 `run`、`loop` 和 REPL 默认把路由事件写入 `~/.forgeagent/audit.jsonl`；嵌入宿主注入
audit sink 时优先使用该 sink。审计文件初始化失败会在任务执行前停止并返回错误，固定诊断不包含
目标、命令参数或路径。路由事件只保存稳定 mode、reason 和必要关联标识。

2026-07-26 已完成 restricted worker bootstrap 加固与发布完整性收尾。sdist 采用显式输入
allowlist，只包含包源码、`pyproject.toml`、`README.md`、`uv.lock`，另保留 Hatchling
必需或生成的 `.gitignore`、`PKG-INFO`；agent/workflow/OpenSpec 开发目录和用户本地文件均由
真实构建负向测试禁止进入。验证证据见
[`2026-07-26-close-release-integrity-verify.md`](../../docs/superpowers/reports/2026-07-26-close-release-integrity-verify.md)
和
[`2026-07-26-review-release-integrity-closeout-verify.md`](../../docs/superpowers/reports/2026-07-26-review-release-integrity-closeout-verify.md)。

## M23 Single / Duo / Triad 质量—成本评估

M23 已完成并归档，不修改协作运行时、产品 CLI、模型注册或 credential 加载。归档 change 见
[`2026-07-27-m23-collaboration-mode-evaluation`](../../openspec/changes/archive/2026-07-27-m23-collaboration-mode-evaluation/)，
v2 固定协议见
[`protocol.json`](../../docs/evaluation/m23/protocol.json)，机器汇总见
[`summary.json`](../../docs/evaluation/m23/runs/2026-07-27-haiku-4-5/summary.json)，中立报告见
[`report.md`](../../docs/evaluation/m23/runs/2026-07-27-haiku-4-5/report.md)。评估固定 3 个任务、3 种
模式、每种组合重复 3 次，共 27 份 terminal raw；所有模式使用 `claude-haiku-4-5`、相同生成
参数、restricted 环境、immutable fixture、外部产物检查和轮换顺序。Single 的协作验收字段为
`N/A`。

本次描述性结果为 Single `5/9`、Duo `8/9`、Triad `9/9`；Duo 和 Triad 的首次内部验收分别为
`8/9`、`9/9`，rejection/correction 总数分别为 `1/1`、`0/0`。三种模式分别产生 76、91、112
次逻辑模型调用，总计 279 次，usage 缺失为 `0/279`；input token 分别为 227727、129869、
193441，output token 分别为 36713、41860、66560，cached/reasoning token 均为 0。平均端到端
延迟分别为 48.93、63.54、79.30 秒。样本仅覆盖 3 个任务、一个模型路由和本机环境；本报告
不自动宣称 Triad 优于 Single，也不据此作产品决策。

首批 v1 运行因检查器缺陷失效，只保留为
[`INVALID.md`](../../docs/evaluation/m23/runs/2026-07-27-haiku-4-5-invalid-8dbebff/INVALID.md)
审计记录，其完成率不得引用。真实请求会产生费用；该 harness 不属于 ForgeAgent 产品 CLI 或
离线 CI 门禁。

完整验证结论见
[`2026-07-27-m23-collaboration-mode-evaluation-verify.md`](../../docs/superpowers/reports/2026-07-27-m23-collaboration-mode-evaluation-verify.md)，
里程碑收尾见
[`milestone_023.md`](../../milestones/milestone_023.md)。

## M25 编程模式质量—成本评估

M25 以独立协议扩大 M23 的证据范围，不修改 M23 历史数据。固定范围为 9 个任务 x 2 个模型
x 3 种模式 x 5 次重复，已形成 270/270 份 terminal raw；模型为 `claude-haiku-4-5` 和
`gpt-5.4-mini`。协议见
[`docs/evaluation/m25/protocol.json`](../../docs/evaluation/m25/protocol.json)，完整说明见
[`docs/evaluation/m25/README.md`](../../docs/evaluation/m25/README.md)，中立报告见
[`docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/report.md`](../../docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/report.md)，独立复算入口为
[`scripts/m25_independent_recompute.py`](../../scripts/m25_independent_recompute.py)，结果为
`INDEPENDENT_RECOMPUTE_OK runs=270`。

证据只适用于记录日期、本机平台和当时的 provider 路由；provider 侧模型权重无法独立固定。
报告不自动排名模式或模型，也不形成产品推荐。M23 的 tracked protocol 和正式证据保持字节不变。
完整验证见
[`2026-07-28-m25-programming-mode-evaluation-verify.md`](../../docs/superpowers/reports/2026-07-28-m25-programming-mode-evaluation-verify.md)，
归档 change 见
[`2026-07-28-m25-programming-mode-evaluation`](../../openspec/changes/archive/2026-07-28-m25-programming-mode-evaluation/)，
里程碑收尾见 [`milestone_025.md`](../../milestones/milestone_025.md)。

## M26 协作完成证据绑定

M26 已完成并归档。宿主注入冻结检查时，Duo/Triad 的全通过 `SubmitEvaluation` 必须具备当前
Evaluator Task、当前 Generator attempt、同一当前 Candidate 快照的全部最新通过证据；恢复、
新 attempt、缺失/失败检查和检查后修改均 fail closed。归档 change 见
[`2026-07-28-bind-collaboration-completion-evidence`](../../openspec/changes/archive/2026-07-28-bind-collaboration-completion-evidence/)，
权威受控证据见
[`2026-07-28-final-v5`](../../docs/evaluation/m26/runs/2026-07-28-final-v5/)。该批次绑定的是 M26 当时
运行时源码 hash，继续作为历史版本证据保留，不随后续修复改写。

2026-07-29 归档后审计发现，检查副本原先没有排除项目根的 `.codegraph`、`.claude` 等本地
agent/workflow 元数据，真实开发仓库会因其中的 socket 或 Skill symlink 在检查开始前稳定
`copy_error`。当前复制、校验与摘要仅忽略 `.agent`、`.agents`、`.claude`、`.codegraph`、
`.codex`、`.superpowers` 这六个顶层真实目录；同名嵌套目录、顶层同名普通文件，以及非忽略
Candidate 树中的 symlink/特殊文件仍进入摘要或 fail closed。

当前主线已完成 M17 Runtime Context Engineering、M18 Memory Runtime（含归档后两次
人工复测 hotfix）、M19 Skills Runtime（程序性知识从 Memory 分流到可验证、快照化、渐进
加载的 Skill）、M20 Eval（离线评估记录、趋势与显式 opt-in 独立 Evaluator）与 M21 Loop
Engineering（有界的耐久多 Task 迭代、版本化 checkpoint/resume、stop conditions、
HTTP/CLI/cron 调度示例）。M22 Duo/Triad 协作运行时已完成并归档，归档前全量验证为
`2069 passed, 11 skipped`，OpenSpec strict 为 `17/17`；含后续复核 hotfix 与 P1 持久化加固的
阶段整合验证为 `2093 passed, 11 skipped`。结构化角色提交门收尾后完成两次真实模型 Triad 验收
（见下文 2026-07-25 复核段）。
收尾记录见
[`milestone_017.md`](../../milestones/milestone_017.md)、[`milestone_018.md`](../../milestones/milestone_018.md)、
[`milestone_019.md`](../../milestones/milestone_019.md)、[`milestone_020.md`](../../milestones/milestone_020.md)
和 [`milestone_021.md`](../../milestones/milestone_021.md)、
[`milestone_022.md`](../../milestones/milestone_022.md)。M19 已通过无 API Key、无网络的本地
人类验收；归档后补充的 Startup-Information 已完成真实 TTY 启动标识、能力摘要、MCP
脱敏诊断和非 TTY 零启动噪声，并作为独立 OpenSpec change 归档。

2026-07-25 归档后复核补齐了 Planner `behavior`/`acceptance` 双字段 WHAT-only 校验，以及
`collaboration.route`、角色 start/outcome（含稳定 model/tier/status、耗时与归一化 usage）
审计；异常路径同样产生不含原文的 outcome 事件。复核修复后的全量验证为
`2073 passed, 11 skipped`。随后修复晚到取消覆盖终态 Collaboration report 的竞态，并加固
FileWrite 路径绑定、项目 Memory 跨进程更新和 Loop checkpoint revision CAS；两个 change 均已
归档。最终整合验证为 `2093 passed, 11 skipped`、golden `20/20`，OpenSpec 主规格为 `17/17`。

随后完成 M22 结构化提交门收尾：Planner、Generator、Evaluator 只有成功调用各自唯一的
Submit 工具才能完成角色；Generator 使用零载荷 `SubmitCandidate` 提交当前 attempt，普通 prose
或 `task_status.completed` 不会启动 Evaluator。成功 Submit 会立即终止当前角色并截断同一响应
中的后续工具。Candidate phase、attempt 与 verdict 在 revision-checked 保存中原子更新，且每个
collaboration ID 使用私有 `flock` 串行化跨 Store/进程提交。两次真实模型 Triad 均 completed，其中
第二次覆盖了一次 reject → 修正 → pass 的完整反馈环。

2026-07-25 P2/P3 收尾新增了可信宿主可选注入的 Evaluator `RunCheck`、可执行 MCP hung-call
回归和 `/search` 固定双引擎 fallback。`RunCheck` 只接受宿主冻结的检查 ID，在一次性项目
副本中通过 restricted Python worker 执行，禁止副本外文件内容访问、目录枚举、路径变更、
网络、派生进程和进程信号控制，并使用最小环境、超时/取消进程组终止和有界脱敏输出；标准
CLI/HTTP 请求不能定义或启用检查，默认 Evaluator 工具集保持不变。真实模型与跨平台证据
仍按下文的 opt-in/环境边界单独记录，不从离线测试外推。

### M22 真实模型 Triad 人类冒烟

以下命令会调用真实模型并可能产生费用；必须在交互式终端运行。请在 Planner
显示计划后人工选择是否批准，restricted tier 的其他确认也会保持原样：

```bash
uv run --offline python scripts/m22-triad-human-smoke.py
```

可通过 `FORGEAGENT_M22_MODEL`、`FORGEAGENT_M22_PLANNER_MODEL` 和
`FORGEAGENT_M22_EVALUATOR_MODEL` 覆盖 Generator、Planner 和 Evaluator 模型。
脚本会自动检查协作终态、生成文件、pytest 与 CLI JSON；生成代码的自动检查会在
受限的一次性项目副本中运行，不继承 credential。为避免用户日常的低反馈限额让
Evaluator 只能看到截断文件，脚本仅在 ForgeAgent 子进程中固定使用 4000-token 单轮、
2000-token 单工具反馈预算；不会修改用户配置，也不会改变模型路由或人工确认。无论成功或失败，现场目录都会
保留在 `/tmp/forgeagent-m22-human-*`。这是人工验收冒烟测试，不是 benchmark 或 CI gate。

针对真实 Generator 在未创建目标文件时直接提交空 Candidate 的行为，脚本还会仅在本次
ForgeAgent 子进程中冻结 `calc.py` 和 `test_calc.py` 的最小就绪要求。`SubmitCandidate` 成功前，
两者必须已是 allowed root 下的非符号链接普通文件；该门禁不读取文件内容、不检查实现正确性，
也不替代 Evaluator 的逐项验收。Planner 和 restricted `FileWrite` 仍由人类在终端批准。
该私有要求不会写入用户配置，普通 CLI、Loop 和 HTTP 默认不启用。

### M19 本地人类验收

不配置 API Key、也不访问网络即可验证项目 Skill 信任、渐进加载、`/reload`、斜杠
候选和当前会话方向键历史：

```bash
uv run --offline python scripts/m19-skills-human-smoke.py
```

该命令必须在真实交互终端运行；它使用临时 HOME/项目和确定性客户端，隔离密钥形态
环境变量，退出后自动恢复并清理，不会读取或修改真实 `~/.forgeagent`。

### M19 归档后补充：Startup-Information

真实交互式 REPL 在初始化期间显示可清理的七色 ASCII Logo，动画结束后保留一份稳定 Logo，
并显示模型、sandbox、项目根目录和 enabled MCP 实际可用数摘要；`NO_COLOR` 降级为静态单色标识。MCP 子进程
stderr 按 server generation 隔离并限制为 8 KiB，只映射为固定、脱敏的诊断字段。
非 TTY、显式 reader、`run` 和 `serve` 不显示启动 UI；管道只输入 `quit` 时 stdout/stderr
保持零字节。M19 阶段原始启动信息范围的证据见
[`2026-07-23-startup-information-verify.md`](../../docs/superpowers/reports/2026-07-23-startup-information-verify.md)。

## 发布前历史 CI 状态

M28 required Linux Docker CI 运行是历史的十项零 skip 容器测试与六项 installed-wheel
冒烟证据，只证明当时的 candidate 和 runner topology。本次 GitHub Actions 配置尚不构成
已执行证据；本机 Docker 不可用时，容器测试必须记为未验证。
持续验证入口为 [GitHub Actions](../../.github/workflows/verify.yml) 与
[GitLab CI](../../.gitlab-ci.yml)；两者运行离线门禁和必需 Linux Docker 门禁，
不包含发布 job。平台状态和历史证据见 [平台支持](../../docs/platform-support.md)。

## 历史真实模型授权边界

P2/P3 收尾时检测到本机存在模型凭证，但真实 golden、single/Triad 对比和 credentialed
Evaluator 会向外部 provider 发送仓库派生内容，执行授权未获通过，因此仍记为未验证，
不能把凭证存在写成真实模型通过。
