# ForgeAgent

轻量级 code-as-action Agent：LLM 把任务目标写成 Python 程序，通过执行程序完成任务。协议是纯文本 Markdown + HTML 注释标记，不依赖厂商 function-calling API，天然模型无关。

设计文档见 [`docs/`](docs/)，行动计划见 [`ACTION_PLAN.md`](ACTION_PLAN.md)，最高宪法见 [`spec.md`](spec.md)。

## 当前验证

pytest: `2410 passed, 10 skipped`；OpenSpec strict: `23/23`.

完整 pytest 全绿。M28 RC 专项：`47 passed`；Golden: `20/20`；Ruff 与
wheel/sdist build 通过。Python 3.11.15 clean-wheel harness 的 `clean-wheel`、`cli`、
`http`、`single`、`duo`、`triad` 六项均通过。

ForgeAgent `0.1.0` 当前是已验证的 Release Candidate，正式发布暂缓：尚未上传 PyPI，也未创建
`v0.1.0` tag。发布前将先完成人类实践和易用性优化，再重新执行发布门禁。候选安装与冻结证据见
[`docs/releases/0.1.0-rc.md`](docs/releases/0.1.0-rc.md)，正式发布的待完成门禁见
[`docs/releases/0.1.0.md`](docs/releases/0.1.0.md)。

2026-07-29 的 M28 首次完整 pytest 为 `2 failed, 2401 passed, 10 skipped`。两个失败都是既有
MCP 关闭墙钟合同在当前宿主调度下超时；隔离复跑仍为 `2 failed`。提交 `83ba892` 仅将测试改为
确定性的预算转发合同，未修改生产 MCP 代码。随后 M28 新增 hostile-proxy 与 Golden 冷启动两项
回归及四项 pip cache 安全合同；最终完整 pytest 为 `2409 passed, 10 skipped`。
Docker client 29.2.1 可用，但 daemon socket 不可连接；本机
十项 container integration 与 Linux container RC smoke 未执行。GitLab M28 Pipeline 57 / Job 263
已在 required Linux Docker runner 上通过十项零 skip 容器测试及六项 installed-wheel RC smoke；
M24 Pipeline 50 / Job 249 的十项通过记录只作为历史 container 证据。

M24 已完成并归档，change 见
[`2026-07-27-m24-continuous-verification-platform-matrix`](openspec/changes/archive/2026-07-27-m24-continuous-verification-platform-matrix/)；持续验证入口见 [`.gitlab-ci.yml`](.gitlab-ci.yml)，平台证据和排期见
[`docs/platform-support.md`](docs/platform-support.md)。Linux Docker 是必需 CI 门禁；本机
macOS Docker Desktop 结果只作为 supplemental 证据；M28 Pipeline 57 / Job 263 只验证记录的
Linux Docker runner topology，不推断未记录的 Linux 架构、Podman 或 Windows 支持。

## M27 协作路由校准（已完成并归档）

M27 已根据 M25 冻结协议完成路由裁决：默认 Single；用户显式选择 Single、Duo 或 Triad 时直接
遵从，显式模式优先于可信宿主已绑定的冻结检查；只有可信宿主已经为本次任务绑定**非空冻结检查**时，
未显式选择的任务才自动使用 Triad。`has_bound_checks` 是可信宿主的内部事实。HTTP 请求和普通任务请求中出现
`has_bound_checks` 会被严格拒绝；服务器 YAML 中出现它也会被严格拒绝。任务文本不能提供或伪造该事实。
任务文本中的编程特征和候选文件就绪要求都不会
自动升级模式。`allow_weaker_override` 仅为旧配置兼容保留，不再改变路由或要求确认。M25 派生报告
新增误完成率和原样终止原因分类；没有任何任务
类别的 Triad solved rate 严格高于 Single，因此不恢复任何类别的自动 Triad。详见
[`M27 派生报告`](docs/evaluation/m25/derived/m27-collaboration-routing/report.md)。

产品 CLI 的 `run`、`loop` 和 REPL 默认把路由事件写入 `~/.forgeagent/audit.jsonl`；嵌入宿主注入
audit sink 时优先使用该 sink。审计文件初始化失败会在任务执行前停止并返回错误，固定诊断不包含
目标、命令参数或路径。路由事件只保存稳定 mode、reason 和必要关联标识。

2026-07-26 已完成 restricted worker bootstrap 加固与发布完整性收尾。sdist 采用显式输入
allowlist，只包含包源码、`pyproject.toml`、`README.md`、`uv.lock`，另保留 Hatchling
必需或生成的 `.gitignore`、`PKG-INFO`；agent/workflow/OpenSpec 开发目录和用户本地文件均由
真实构建负向测试禁止进入。验证证据见
[`2026-07-26-close-release-integrity-verify.md`](docs/superpowers/reports/2026-07-26-close-release-integrity-verify.md)
和
[`2026-07-26-review-release-integrity-closeout-verify.md`](docs/superpowers/reports/2026-07-26-review-release-integrity-closeout-verify.md)。

## M23 Single / Duo / Triad 质量—成本评估

M23 已完成并归档，不修改协作运行时、产品 CLI、模型注册或 credential 加载。归档 change 见
[`2026-07-27-m23-collaboration-mode-evaluation`](openspec/changes/archive/2026-07-27-m23-collaboration-mode-evaluation/)，
v2 固定协议见
[`protocol.json`](docs/evaluation/m23/protocol.json)，机器汇总见
[`summary.json`](docs/evaluation/m23/runs/2026-07-27-haiku-4-5/summary.json)，中立报告见
[`report.md`](docs/evaluation/m23/runs/2026-07-27-haiku-4-5/report.md)。评估固定 3 个任务、3 种
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
[`INVALID.md`](docs/evaluation/m23/runs/2026-07-27-haiku-4-5-invalid-8dbebff/INVALID.md)
审计记录，其完成率不得引用。真实请求会产生费用；该 harness 不属于 ForgeAgent 产品 CLI 或
离线 CI 门禁。

完整验证结论见
[`2026-07-27-m23-collaboration-mode-evaluation-verify.md`](docs/superpowers/reports/2026-07-27-m23-collaboration-mode-evaluation-verify.md)，
里程碑收尾见
[`milestone_023.md`](milestones/milestone_023.md)。

## M25 编程模式质量—成本评估

M25 以独立协议扩大 M23 的证据范围，不修改 M23 历史数据。固定范围为 9 个任务 x 2 个模型
x 3 种模式 x 5 次重复，已形成 270/270 份 terminal raw；模型为 `claude-haiku-4-5` 和
`gpt-5.4-mini`。协议见
[`docs/evaluation/m25/protocol.json`](docs/evaluation/m25/protocol.json)，完整说明见
[`docs/evaluation/m25/README.md`](docs/evaluation/m25/README.md)，中立报告见
[`docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/report.md`](docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/report.md)，独立复算入口为
[`scripts/m25_independent_recompute.py`](scripts/m25_independent_recompute.py)，结果为
`INDEPENDENT_RECOMPUTE_OK runs=270`。

证据只适用于记录日期、本机平台和当时的 provider 路由；provider 侧模型权重无法独立固定。
报告不自动排名模式或模型，也不形成产品推荐。M23 的 tracked protocol 和正式证据保持字节不变。
完整验证见
[`2026-07-28-m25-programming-mode-evaluation-verify.md`](docs/superpowers/reports/2026-07-28-m25-programming-mode-evaluation-verify.md)，
归档 change 见
[`2026-07-28-m25-programming-mode-evaluation`](openspec/changes/archive/2026-07-28-m25-programming-mode-evaluation/)，
里程碑收尾见 [`milestone_025.md`](milestones/milestone_025.md)。

## M26 协作完成证据绑定

M26 已完成并归档。宿主注入冻结检查时，Duo/Triad 的全通过 `SubmitEvaluation` 必须具备当前
Evaluator Task、当前 Generator attempt、同一当前 Candidate 快照的全部最新通过证据；恢复、
新 attempt、缺失/失败检查和检查后修改均 fail closed。归档 change 见
[`2026-07-28-bind-collaboration-completion-evidence`](openspec/changes/archive/2026-07-28-bind-collaboration-completion-evidence/)，
权威受控证据见
[`2026-07-28-final-v5`](docs/evaluation/m26/runs/2026-07-28-final-v5/)。该批次绑定的是 M26 当时
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
[`milestone_017.md`](milestones/milestone_017.md)、[`milestone_018.md`](milestones/milestone_018.md)、
[`milestone_019.md`](milestones/milestone_019.md)、[`milestone_020.md`](milestones/milestone_020.md)
和 [`milestone_021.md`](milestones/milestone_021.md)、
[`milestone_022.md`](milestones/milestone_022.md)。M19 已通过无 API Key、无网络的本地
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

## M22 Duo / Triad（独立验收）

协作模式位于普通 `Task` 上层，不改变 single 模式的 `TaskOutcome` 或既有完成语义。Step 新增
默认关闭的通用 completion signal；只有协作角色 registry 显式登记 required Submit 时启用：

- Duo 串行运行 Generator → Evaluator。Generator 必须调用零载荷 `SubmitCandidate` 提交当前
  attempt；独立 Evaluator 对冻结验收项全部判定通过后，协作结果才是 `completed`。三个角色的
  Submit 工具成功后都会立即完成该角色，不需要额外 standalone `task_status`。
- Triad 在 Duo 前增加 Planner。Planner 只定义 WHAT（可观察行为与验收标准），计划必须由
  交互用户确认后冻结；条目、顺序和 `plan_digest` 在 Generator/Evaluator 与 Loop resume 中
  均不能删除、重排、替换或降标。
- Evaluator 使用独立 Task/client/runtime/registry，默认 restricted，只注册 `FileRead`、
  `FileList` 和 `SubmitEvaluation`，没有 Exec、写、编辑、Web、MCP、Skill 或 Survey 工具。
  可信宿主程序可额外注入固定 `RunCheck` ID；模型不能提供 argv/env/cwd/timeout，CLI/HTTP
  客户端也不能定义检查。检查只允许当前 Python 的固定入口并限制在一次性副本；它仍是
  Python application-layer isolation，不承诺密封 OS sandbox。项目根的 agent/workflow 元数据
  目录不属于 Candidate 快照；同名嵌套目录仍属于 Candidate，非忽略树中的 symlink 和特殊文件会
  在复制前 fail closed。宿主注入检查时，全通过
  `SubmitEvaluation` 还必须具备当前 Evaluator Task 内对同一 Generator attempt、同一当前
  Candidate 快照产生的全部最新通过证据；检查缺失、失败、超时、旧 attempt、快照变化或恢复后
  未重跑都会 fail closed。包含失败项的 verdict 仍可提前提交；未注入检查时保持原行为。
- 每次拒绝都会用有界、脱敏证据启动 fresh Generator。`--max-rejections` 默认 2、最大 10；
  达到上限以 `rejection_limit` 停止，不会无限重试。

CLI 示例：

```bash
# 非编程目标可显式使用 Duo；角色模型缺省时沿用 --model
uv run forgeagent run --mode duo \
  --evaluator-model claude-haiku-4-5 \
  --max-rejections 2 \
  "核对 report.json 是否满足说明"

# Triad 会先展示 Planner 清单并请求确认
uv run forgeagent run --mode triad \
  --planner-model claude-haiku-4-5 \
  --evaluator-model claude-haiku-4-5 \
  "实现 CSV 汇总程序并添加测试"
```

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

REPL 提供 `/duo <goal>` 和 `/triad <goal>`，并复用 `/help`、completion 与历史路径。
缺少 goal 时只显示 usage，不启动任务。

路由规则是：**默认 Single**。用户显式选择 Single、Duo 或 Triad 时直接生效；只有可信宿主已为
本次任务绑定非空冻结检查时，未显式选择的任务才使用 Triad。普通 CLI、REPL、Loop 和 HTTP 的
初始路由没有这类检查，因而保持 Single；编程文本和候选文件就绪要求都不会触发自动升级。
`allow_weaker_override` 仅为旧配置兼容保留，不再改变路由或要求确认，客户端也不能提交宿主检查
事实。

公开报告仅显示 collaboration ID、mode/status/reason/phase、计划/通过/失败数、角色尝试、
rejections、rounds、归一化 usage、`usage_available` 与最多 8 条掩码后证据摘要；不显示完整
goal、计划/verdict 正文、prompt、模型回复、工具参数、文件内容、credential 或绝对路径。

成本边界：Duo 至少比 single 多一次独立模型会话；Triad 再增加 Planner，且每次打回都会
新增 Generator + Evaluator 调用。角色可选不同模型以控制成本，但 `usage_available=false`
表示某次 provider 未提供可靠用量，不能把缺失 usage 当作零。真实模型的 single/Triad
质量对比属于 opt-in，不是离线 CI 门禁。

已知限制：v1 严格串行，不并行角色；默认 Evaluator 没有 Exec，只能读取 Generator 已产出的
文件/测试报告，`RunCheck` 也仅在可信宿主显式注入固定检查时可见；CLI 协作模式暂不接受
图片；协作状态没有公开 resume API；headless Triad 默认拒绝自动批准计划。

## M21 Loop（有界的耐久迭代）

Loop 是显式选择的多次 Task 迭代，不改变 `run`、REPL 或普通 HTTP Task 的语义。新建
Loop 必须给出目标和 token 预算；其余预算有安全默认值。每个 Loop 在允许根目录下保存
版本化 checkpoint，恢复时只接受 Loop ID，目标和预算仍使用原 checkpoint 中冻结的值。

```bash
# 创建：checkpoint 位于当前 allowed root 的 .forgeagent/loops/ 下
uv run forgeagent loop "生成依赖状态报告，不改动任何文件" --token-budget 12000

# 恢复：不要同时传 goal 或任意预算覆盖项
uv run forgeagent loop --resume LOOP_ID
```

模型在完成可独立验证的进度后调用 Loop 专用 `Checkpoint` 工具。每个 Loop ID 使用独立的
本地跨进程锁，工具成功返回前会在锁内校验并原子 commit 新 revision；进程中断后的 resume
从最后一次 commit replay，已提交条目会作为
完成项注入下一次 Task，未提交的外部副作用可能重做。因此应把副作用切成可验证步骤，并在
每一步后 checkpoint；这不是外部操作的 exactly-once 承诺。

Loop 的稳定停止原因是 `completed`、`cancelled`、`wall_clock`、
`token_usage_unavailable`、`token_budget`、`max_rounds`、
`consecutive_failures`、`unrecoverable_failure` 和 `checkpoint_error`。round、token、
wall clock 与连续失败均按整个 Loop 累计；wall clock 是协作超时，不能强杀已在途的模型或
工具调用，只会在其返回后的安全边界停止。token usage 缺失不会被当成零而绕过预算。

Loop 会产生模型调用费用，token budget 只是上限而非报价。M20 的独立 Evaluator 仍是
单独的显式 opt-in `evaluate` 命令；M22 collaborative Loop 则通过
`--collaboration-mode duo|triad` 显式冻结协作模式、state ID 与计划摘要。普通 single Loop
不会自动创建 Planner 或 Evaluator。

```bash
uv run forgeagent loop "实现并验证依赖报告生成器" \
  --collaboration-mode triad \
  --planner-model claude-haiku-4-5 \
  --evaluator-model claude-haiku-4-5 \
  --max-rejections 2 \
  --token-budget 12000
```

### HTTP 与外部调度

HTTP 的既有 `POST /tasks` 使用严格 allowlist。新 Loop body 不含 credential、路径或安全
策略；这些仍由服务端配置拥有：

```json
{
  "goal": "生成依赖状态报告，不执行安装或更新",
  "mode": "loop",
  "token_budget": 12000,
  "max_rounds": 20,
  "wall_clock_seconds": 900,
  "max_consecutive_failures": 3
}
```

恢复 body 只能是：

```json
{"mode": "loop", "resume_loop_id": "LOOP_ID"}
```

cron、launchd 和 systemd 的 user-installed 调用示例见
[`examples/loop/README.md`](examples/loop/README.md)。ForgeAgent 不内置 scheduler daemon：
同一 checkpoint 的跨进程并发恢复不应由多个调度触发器重叠执行，使用一个外部单实例策略。

## 安装

```bash
uv sync            # 安装依赖（自动拉取合规 Python ≥3.11）
```

## 快速开始

```bash
# 单次执行一个目标
uv run forgeagent run "统计 data.csv 中 value 列的总和，写入 result.json"

# 交互式 REPL（输入目标 → 执行 → 显示结果 → 循环；空行或 quit 退出）
uv run forgeagent

# 选择沙箱档位（默认 restricted）
uv run forgeagent --tier trusted run "..."

# 指定模型（默认 claude-sonnet-5）
uv run forgeagent --model claude-haiku-4-5 run "..."

# 列出已登记的模型与别名
uv run forgeagent models

# 允许任务中途向你提问（Survey 工具）——单次命令默认不交互，加 --interactive 开启
uv run forgeagent --tier trusted run "..." --interactive

# 流式显示：响应逐字实时渲染（非终端环境如管道/CI 自动降级为非流式）
uv run forgeagent --stream run "..."

# 禁用 session/project memory 的读取、注入与写入
uv run forgeagent --no-memory run "..."

# 附加图片：单个文件或整个目录（≤5MB/张、≤20 张），模型需支持图片输入
uv run forgeagent run "描述这张图" --image ./screenshot.png
```

每轮结束后打印会话级用量状态行（M10）：

```
usage: in=1234 out=567 cached=200 reasoning=0 (session total) cache_hit=16.2%
```

`in`/`out` 为累计 input/output tokens，`cached` 为命中缓存的 input tokens（Anthropic 的 cache_creation+cache_read 合并、OpenAI-compatible 的 `prompt_tokens_details.cached_tokens`），`reasoning` 为计费的 thinking/reasoning tokens（Anthropic 已并入 `out`，此处恒为 0；OpenAI-compatible 视供应商在标准/非标准字段间取值，见 [`docs/m9-streaming-multimodal-commands.md`](docs/m9-streaming-multimodal-commands.md) §8 S2）。`cache_hit` 使用 provider adapter 归一化后的累计 prompt 分母；provider 未提供可靠分母或分母为零时显示 `n/a`，不以目标百分比作为完成门禁。

REPL 内输入 `/` 加回车查看指令菜单，或直接 `/help`。当前支持的指令：

- `/model [id-or-alias]` — 列出已登记模型，或切换本次会话使用的模型
- `/search <query>` — 联网搜索，结果只打印，绝不自动送进对话内容
- `/image <path> [goal...]` — 附加图片（文件或目录）；不带 goal 则暂存到下一条输入
- `/mcp [status|enable <s>|disable <s>]` — 看 MCP server 连接状态与工具清单、启停某个 server
- `/memory` — 查看当前 session/project memory（已掩码）
- `/remember <session|project> <key>=<value>` — 显式保存一条陈述性事实
- `/duo <goal>` — Generator + 独立 Evaluator；比 single 产生更多模型调用
- `/triad <goal>` — Planner 确认 + Generator/Evaluator；成本最高
- `/reload` — 重读 `~/.forgeagent/{models,config}.yaml`，配置写错时当场报错而非等到下次 run
- `/help [command]` — 列出全部指令，或查看某个指令的详细用法

REPL 命令必须以 `/` 开头。裸 `models`、`reload`、`mcp` 和 `mcp ...` 都是普通任务目标；这与顶层 CLI 子命令 `forgeagent models` 无关，后者仍用于列出模型。

Memory 只保存经过确定性准入的事实、偏好和决策。session scope 只在当前 REPL 进程内有效，绝不落盘；
只有通过确定性准入的合法 project scope 候选才使用稳定本地锁，在锁内重读并合并最新条目后原子持久化。
相同 key 按后获得锁者替换，不同 key 不互相丢失。文件仍可直接编辑纠正，`--no-memory` 同时关闭两级记忆。

交互式终端中的 REPL 会在输入 `/` 时即时显示 slash 指令，并随继续输入过滤候选；可用键盘选择候选。上下方向键只回放当前进程内的会话输入，ForgeAgent 不会把 REPL 历史写入文件。测试注入 reader 和非 TTY 输入仍沿用普通输入路径。

启动摘要只属于真实交互式 REPL：必须使用默认 reader，且 stdin 与 stdout 都是 TTY。初始化完成后会显示所选模型、sandbox 档位、项目根目录和已启用 MCP 的可用数；可选 MCP 故障只显示一行固定、脱敏的降级信息。支持颜色、且不在 `CI`/`TERM=dumb` 等降级环境时，初始化期间显示瞬态的彩色动画 Logo；`NO_COLOR`、`console.no_color` 或无颜色系统只关闭动画和 ANSI 颜色，真实交互式 REPL 仍显示一次静态、单色标识和启动摘要。`CI`、`TERM=dumb` 与非 TTY 路径不显示该标识或动画；`run` 和 `serve` 也不进入 REPL 启动界面。

目标提示符 `forge> ` 与动画/标识是独立条件：只要仍是默认 reader 加 stdin/stdout 双 TTY 的 REPL，`CI`、`TERM=dumb` 或 `NO_COLOR` 不会抑制它；只有非 TTY 或显式注入 reader 的路径使用空提示符。`printf 'quit\\n' | uv run forgeagent` 因而让 stdout 和 stderr 都保持零启动字节，而管道输入的实际任务结果仍会输出。

## Skills（可验证的程序性知识）

Skill 是本地、只读、按需加载的 Markdown 文档，不是工作流引擎或权限配置。每个 Skill 必须位于以其名称命名的目录中的 `SKILL.md`，并且严格采用下面五部分；`name` 必须与目录名相同：

```markdown
---
name: review-python
trigger: Use when reviewing Python changes before completion.
---

## Steps

1. Inspect the diff and affected call paths.

## Failure Branches

- If focused tests fail, report the exact failure and stop completion.

## Completion Criteria

- Findings are resolved or explicitly reported.
```

用户 Skill root 是 `<home>/.forgeagent/skills/`，项目 Skill root 是
`<project>/.forgeagent/skills/`。用户级 Skill 默认可用。项目级 Skill 首次使用及内容
变化后需要终端确认：确认摘要只显示经过掩码且有界的名称/trigger；批准状态单独保存在
`<home>/.forgeagent/skills-trust.json`，将规范项目身份同时绑定到原始内容摘要和掩码后
有效输入摘要。这份独立的双摘要记录不与身份文件的 trust record 共用。可信项目 Skill
可以覆盖同名用户 Skill；未确认的项目 Skill 不会隐藏用户版本。`--no-identity` 关闭项目
Skill 输入，但不关闭用户 Skill。

初始系统提示词中的 Skill 段只包含按名称稳定排序、数量和字节均受限的 `name — trigger` 目录，
不包含 Steps、Failure Branches 或 Completion Criteria 正文。模型根据 trigger 自主决定是否调用
只读 `Skill` 工具读取全文或某个段落；不存在的名称会作为可恢复的工具失败反馈返回。交互
CLI 可以进行项目 Skill 确认和 `/reload` 快照替换；headless HTTP 没有确认通道，只使用用户
Skill 及已预先批准、双摘要仍匹配的项目 Skill。每个 CLI 会话和 HTTP 服务启动时取得一个
不可变 Skill 快照，HTTP Task 不共享可变的 Skill 执行状态。

Skill 的 Steps、Failure Branches 和 Completion Criteria 只是给模型的执行指导。它们不能
授予工具权限、绕过 sandbox、跳过确认，或直接把 Task 标记为完成；现有工具确认、审计与
两阶段完成判定保持不变。

### M19 本地人类验收

不配置 API Key、也不访问网络即可验证项目 Skill 信任、渐进加载、`/reload`、斜杠
候选和当前会话方向键历史：

```bash
uv run --offline python scripts/m19-skills-human-smoke.py
```

该命令必须在真实交互终端运行；它使用临时 HOME/项目和确定性客户端，隔离密钥形态
环境变量，退出后自动恢复并清理，不会读取或修改真实 `~/.forgeagent`。

### M19 归档后补充：Startup-Information

真实交互式 REPL 在初始化期间显示可清理的七色 ASCII Logo，完成后只保留模型、sandbox、
项目根目录和 enabled MCP 实际可用数摘要；`NO_COLOR` 降级为静态单色标识。MCP 子进程
stderr 按 server generation 隔离并限制为 8 KiB，只映射为固定、脱敏的诊断字段。
非 TTY、显式 reader、`run` 和 `serve` 不显示启动 UI；管道只输入 `quit` 时 stdout/stderr
保持零字节。完整证据见
[`2026-07-23-startup-information-verify.md`](docs/superpowers/reports/2026-07-23-startup-information-verify.md)。

## 配置（API key 与端点）

随包提供的内置配置只通过环境变量读取 key，**不在内置配置或代码中保存 literal API
key**，运行时才解析：

按**模型 → provider group** 精确路由，不做跨 group 优先级扫描：每个模型注册在 `res/config.yaml` 的唯一一个 group 下，请求该模型时只读取**它自己所属 group** 的 key/端点变量——其它 group 的环境变量即使设了也不生效（不会把 A 家的 key 发到 B 家的端点）。内置三个 group：

| Group | 模型 | key 变量 | 端点变量 |
|---|---|---|---|
| `anthropic` | claude-sonnet-5 / claude-opus-4-8 / claude-haiku-4-5 / claude-fable-5 | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL`（可选，不设则用官方端点） |
| `openai` | gpt-5.5 / gpt-5.4-mini | `OPENAI_API_KEY` | `OPENAI_BASE_URL`（必须含 `/v1`） |
| `llm` | glm-5.2 / deepseek-v4-flash | `LLM_API_KEY` | `LLM_BASE_URL`（必须含 `/v1`） |

缺对应 key 时报清晰错误并退出（退出码 2），不会崩溃、不会用错 group 的 key。可用
`~/.forgeagent/config.yaml`/`models.yaml` 扩展或覆盖分组与模型（见
[`docs/model-client-contract.md`](docs/model-client-contract.md)）。用户 `config.yaml` 也允许为
provider group 配置 literal `api_key` 或 `base_url`，并优先于对应的 `*_env` 值；literal key
会以明文保存在该文件中，因此推荐继续使用环境变量，且不要提交或共享含凭证的用户配置。
随包配置和源码不硬编码任何厂商端点或 API key。

```bash
export ANTHROPIC_API_KEY="你的-key"
export ANTHROPIC_BASE_URL="..."         # 可选，自建代理/兼容网关

# OpenAI 官方或第三方 OpenAI 兼容网关：
export OPENAI_API_KEY="你的-key"
export OPENAI_BASE_URL="..."            # 必须含 /v1（如 https://api.openai.com/v1）

# 通用 OpenAI-compatible 网关（glm-5.2 / deepseek-v4-flash）：
export LLM_API_KEY="你的-key"
export LLM_BASE_URL="..."               # 必须含 /v1
```

**`OPENAI_BASE_URL`/`LLM_BASE_URL` 必须自带 `/v1` 路径段**——OpenAI SDK 不会自动拼接（不同于 Anthropic SDK）。多数网关在缺 `/v1` 的路径上返回 200 的 HTML 前端页面而不是 404，容易误判成"连上了"，实际每次请求都会因响应体不是 JSON 而解析失败。

### 上下文窗口

`config.yaml` 可含顶层 `context`：`utilization_ratio`（无量纲比例，默认 `0.8`）、
`image_token_reserve`、`round_feedback_max_tokens` 和 `tool_result_max_tokens`。后三者
均为**近似 token**；后两个为 `null` 时自动推导。对模型窗口 `C`、比例 `R` 和有效
输出预留 `O`，输入预算为 `floor(C * R) - O`；先独立计算自适应单轮反馈预算
`floor(input * 10%)` 和自适应单工具结果预算 `floor(adaptive_round * 25%)`，再由
`round_feedback_max_tokens` 和 `tool_result_max_tokens` 分别覆盖对应自适应值，最后验证
两个最终值均为正且单轮预算不小于单工具预算。`O` 使用本次请求的
`max_output_tokens`，未指定时使用模型 capability 的 `max_output_tokens`。

估算是本地、保守的字符/图片储备近似值，不等同 provider tokenizer 或计费口径；默认
`0.8` 留出误差余量，仍可能提前滑动，provider 的实际 context-length 错误仍按普通
结构化 client error 返回。每次请求都保留 system prompt 和初始 goal，只按完整的
assistant + feedback 交互单元淘汰最旧历史；前缀或最新完整单元无法放入时 fail-fast，
不会截断或调用 provider。工具反馈按 head/tail 规则限额，并在被截断时如实给出原始
总量、展示范围和真实 continuation；固定元数据本身超预算也会 fail-fast。

## 沙箱档位（安全边界）

执行后端按档位挂载，档位语义即隔离强度（详见 [`docs/threat-model.md`](docs/threat-model.md)）：

- `trusted`：同进程执行，无隔离，代码能碰宿主一切。仅在完全信任任务来源时用。
- `restricted`（默认）：每块新起子进程 + 跨平台应用层限权——`sys.addaudithook` 拦 `open`/`socket.*`/进程 spawn 审计事件做路径白名单、默认禁网、禁子进程，配超时强杀与 `rlimit`（Unix）。能挡绝大多数越权与一部分蓄意逃逸，但非 OS 级隔离——`ctypes` 直调 syscall 等仍可绕过。适合日常使用与来源基本可信的任务。
- `container`（M8）：OS 级隔离——每块跑在一次性 docker 容器里，只挂载项目目录（宿主其余文件系统在容器内**不存在**）、无网络设备（`--network none`）、资源硬限（`--pids-limit`/`--memory`/`--cpus`）、非 root + `--cap-drop ALL` + 只读 rootfs + `/sys` 遮蔽。restricted 挡不住的 native 代码逃逸在这一档被 namespace 拦住。需要本机安装并运行 docker（缺 docker 时报错退出，绝不静默降级）；镜像默认 `python:3.11-slim`，可用 `--container-image` 换（要第三方库就换自备镜像——容器内 pip 会被断网挡住）。不防内核 0-day——是 OS 级隔离，不是虚拟机级。

```bash
# 容器档（需 docker；首次先 docker pull python:3.11-slim）
uv run forgeagent --tier container run "..."
uv run forgeagent --tier container --container-image my-image:latest run "..."
```

隔离强度 = 所选档位对应后端能提供的强度，与提示词或静态规则数量无关。来源完全不可信且后果严重时用 container 档，或不在敏感环境运行。

## 工具集

模型通过文本协议标记调用工具（详见 [`docs/text-protocol-spec.md`](docs/text-protocol-spec.md)）。工具集可插拔（`ToolRegistry`）：

- **Exec / Edit**：写并执行 Python 代码块 / 对已有块做 old→new 增量修改。核心的 code-as-action 工具。
- **Survey**（M7）：任务中途向你提问获取信息（`question` + 可选 `options`）。REPL 与 `run --interactive` 下在终端提问并等你输入；无交互通道（headless）时任务以 `need_info` 干净终止，把问题回传给调用方，而不是卡住或瞎猜。
- **Skill**（M19）：从当前不可变 Skill 快照只读一个已验证的 Skill 全文，或重读 `steps`、`failure_branches`、`completion_criteria` 段。它没有文件路径或写入参数，不需要确认，也不改变其他工具的确认或审计规则。
- **WebFetch**（M10）：GET 单个 http(s) URL，经 SSRF 防护后抓取。正文存到 `allowed_root` 下的文件（模型可在后续轮用 Exec/FileRead 处理全文），`detail` 只回传预览（≤1MB 截断），未经审查的网页正文不会整段进模型上下文。`restricted`/`container` 档下这是**唯一**出网路径（Exec 在这两档不能开 socket），因此确认门在这两档是真实的安全边界，不是提示性的 UX。
- **FileRead / FileWrite / FileList**（M10）：读/写/列出 `allowed_root` 下的文件，路径校验拒绝逃出项目根目录；FileWrite 还通过 directory fd 逐级 `O_NOFOLLOW` 打开父目录和最终目标，拒绝校验后发生的 symlink 替换。FileRead 默认不设确认门（只在非 trusted 档记日志，不拦截）；**FileWrite 的确认门只是 UX 提示，不是安全边界**——Exec 工具跑的代码在 `restricted`/`container` 档下本来就能在 `allowed_root` 内任意写文件，不经过这个确认门。FileList 只返回相对路径，不暴露宿主真实目录结构。
- **MCP**（M7）：调用外部 [MCP](https://modelcontextprotocol.io) server 暴露的工具，见下节。

出网与文件访问的边界详见 [`docs/threat-model.md`](docs/threat-model.md)；SSRF 防护实现见 [`docs/m10-usage-observability-and-tools.md`](docs/m10-usage-observability-and-tools.md)（逐候选地址校验 + NAT64 解包 + 直连已校验 sockaddr 堵 DNS-rebinding TOCTOU + 重定向逐跳复检）。

### 直连网络变更

**[SECURITY][BREAKING]** WebFetch 和 `/search` 强制直连：运行时使用 `ProxyHandler({})`，不读取大小写形式的 `HTTP_PROXY`、`HTTPS_PROXY` 或 `ALL_PROXY`，`NO_PROXY`/`no_proxy` 也不能恢复代理。每个重定向跳都重新校验目标，最多允许 10 跳。

仅有三种迁移方式：允许该进程直连；在 ForgeAgent 外部预取到 `allowed_root` 后用 FileRead；或使用一个明确受信任的 MCP fetch 工具。不要恢复环境代理作为绕过方式。当前没有 `network.proxy` 配置；未来只能明确选择 trusted-forward-proxy 或 guarded-tunnel 信任模型。

## 身份与提示词（SOUL/USER/AGENTS/MEMORY）

ForgeAgent 的系统提示词由固定协议段（不可覆盖，见 [`docs/text-protocol-spec.md`](docs/text-protocol-spec.md)）和身份段组合而成。SOUL 段始终存在：自定义文件缺失时使用内置中性默认人格。只有 USER/AGENTS/MEMORY 属于可省略 section；对应内容缺失时 section 不出现，不影响固定协议：

- `~/.forgeagent/SOUL.md`：用户级 Agent 人格/身份描述，存在时**完全替换**内置中性默认人格，不与默认内容合并；缺失时保留该默认人格作为 SOUL 段。
- `~/.forgeagent/USER.md`：用户级偏好说明（如“回答从简”“默认用中文”），随每次任务注入。
- `<allowed_root>/.forgeagent/AGENTS.md`：项目级协作规则。**首次使用需终端确认**（有界、控制字符转义、secret 掩码后的内容预览 + 截断项目标签），确认结果原子写入 `~/.forgeagent/identity-trust.json`；内容变化会使旧确认失效并重新提示确认；无交互终端（headless）时默认拒绝，不会静默生效。
- `<allowed_root>/.forgeagent/MEMORY.md`：项目级记忆，同 `AGENTS.md` 走确认门。M18 的准入规则会把
  合法的 `/remember` 输入或模型候选以原子方式持久化到该文件；用户可以直接编辑以更正或删除记忆，
  下一个任务会重新读取。`--no-memory` 关闭两个记忆作用域；`--no-identity` 按身份合同同时关闭
  SOUL、USER、AGENTS 和 MEMORY。

所有身份文件都有 32 KiB 单文件上限，多个文件掩码后合计 96 KiB 上限，任何正文都不会被截断：SOUL/USER 超限时任务以身份配置错误停止；AGENTS/MEMORY 超限或使合计超限时，仅剥离相应项目段、输出脱敏诊断并继续。路径解析拒绝 `.forgeagent` 目录或身份文件通过 symlink 逃出 `home`/`allowed_root`。详见 [`docs/threat-model.md`](docs/threat-model.md) T12。

```bash
# 禁用全部自定义身份文件（固定协议与 MCP 工具说明仍然存在）
uv run forgeagent --no-identity run "..."

# 让下一个任务重新读取身份文件（项目级内容变化会重新触发确认）
# REPL 内：
/reload
```

`/reload` 先读取并验证新的 models 与 context 配置及当前模型的窗口预算；全部成功后
才一次性替换 REPL 的 registry + context 快照。任一步失败会保留先前的 registry 与
context，并报告 `reload failed`，不会部分发布这两个配置。随后独立重读身份；身份重载
失败只保留先前身份，不会回滚已经成功发布的 registry + context 快照。

## MCP 服务（连接外部工具）

配置了 MCP server 时，`MCP` 工具自动出现在工具集里；未配置则完全不出现。配置放在 `~/.forgeagent/mcp.yaml`，用与 Claude Desktop / Cursor **相同的 `mcpServers` 格式**（现有配置可直接粘贴）：

```yaml
mcpServers:
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/data"]
    required: false                         # default; optional failures degrade
    autoApprove: [read_file, list_directory]   # 只读工具，跳过确认门
  github:
    command: docker
    args: ["run", "-i", "--rm", "-e", "GITHUB_TOKEN", "ghcr.io/github/github-mcp-server"]
    env: {GITHUB_TOKEN: "${GITHUB_TOKEN}"}       # ${VAR} 从环境变量取，绝不写字面 secret
```

- **多 server 同时接入**：启动时并发连接所有 `enabled` server。默认 optional server 连不上时标记 unavailable 并从工具目录移除，不影响其余；`required: true` 的 enabled server 连不上会清理已启动资源并使 CLI 非零退出。同名工具（两个 server 都有 `search`）靠调用里的 `server` 字段区分，不冲突。
- **确认门（安全边界）**：MCP server 在**主进程执行，不受 restricted 沙箱约束**。所以有副作用的工具调用会逐次要你确认（终端 y/N）；只有列在该 server `autoApprove` 里的只读工具才免确认。未批准 → 结构化拒绝，不执行。因此 `mcpServers` 里只应放你信任的可执行文件，`autoApprove` 只列真正只读的工具。安全模型详见 [`docs/threat-model.md`](docs/threat-model.md)。
- 每 server 可 `enabled: false` 暂时关掉、`expose: [toolA]` 只广告部分工具（控制注入系统提示词的工具清单体积）。REPL 里用 `/mcp status` 看连接状态。关闭使用绝对 deadline；若后台 MCP 清理未完成，会给出不完整关闭警告并保留资源引用以供重试，而不是伪造清理成功。
- Docker 只是某个已配置 MCP integration runtime 的可选依赖，不是 ForgeAgent 的安装或启动前提。Docker 不可用时，`/mcp` 仅对该 server 报告固定的 `Status`、`Tools`、`Reason`、`Impact`、`Action` 字段（例如 `Docker is not running`），不会回显 child stderr、命令、参数、环境、异常类型或 secret。

## 多模型支持

配置驱动、模型无关。当前已登记 8 个模型，覆盖 Anthropic 原生客户端与 OpenAI-compatible 客户端两种 `client_kind`（能力矩阵见 [`docs/model-capability-matrix.md`](docs/model-capability-matrix.md)）：

| 模型 | client_kind | 定位 | 备注 |
|---|---|---|---|
| `claude-sonnet-5` | anthropic | 默认主模型 | 能力/成本平衡最佳 |
| `claude-haiku-4-5` | anthropic | 廉价档 | 最快最便宜；无 thinking/effort，max output 64K |
| `claude-opus-4-8` | anthropic | 全力档 | 用户显式要求更强能力时 |
| `claude-fable-5` | anthropic | opt-in | 最强但贵、thinking 强制开、有拒答风险 |
| `gpt-5.5` | openai_compatible | OpenAI 官方 | 无 thinking，支持 effort |
| `gpt-5.4-mini` | openai_compatible | OpenAI 官方廉价档 | 无 thinking，支持 effort |
| `glm-5.2` | openai_compatible | 第三方网关 | 支持 thinking + effort |
| `deepseek-v4-flash` | openai_compatible | 第三方网关 | 支持 thinking + effort |

各模型的参数差异（thinking / effort / max output）由客户端内部按能力自动适配，调用方无需感知——即 capability-gating。

## 真实模型冒烟（opt-in）

`smoke` 命令用**真实模型**跑一小组目标做端到端连通性检查（需 API key，会产生真实调用费用）：

```bash
export ANTHROPIC_API_KEY="你的-key"
uv run forgeagent smoke                                # sonnet-5 + haiku-4-5
uv run forgeagent smoke --include-fable                # 额外加 fable-5（更贵、有拒答风险）

export OPENAI_API_KEY="你的-key"; export OPENAI_BASE_URL="https://api.openai.com/v1"
export LLM_API_KEY="你的-key"; export LLM_BASE_URL="..."   # glm-5.2/deepseek-v4-flash 的网关，必须含 /v1
uv run forgeagent smoke --include-openai-compatible     # 额外加 gpt-5.4-mini/glm-5.2/deepseek-v4-flash
```

缺 key 时清晰提示并退出，不会伪造成功。这是 opt-in 检查，不属于基础 CI（基础测试全程无 key、无网络，用 MockClient 驱动）。

## Golden 验证核心

400 项文档任务中，只有 20 项是可执行的可信核心：`G01,G03,G05,G06,G08,G11,G13,G14,G15,G17,G27,G43,G58,G59,G324,G329,G330,G332,G333,G355`。其余 380 项保留为候选目录，不会被 runner 当作可执行验收。

```bash
# 离线、无凭证的 20 项核心；写 results.json 和 report.md
uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-golden-offline

# 明确 opt-in 的真实模型五项：G01,G03,G08,G11,G43；会产生真实请求和费用
uv run python -m tests.golden.runner --real-model claude-sonnet-5 \
  --output-dir /tmp/forgeagent-golden-real
```

离线 runner 当前验证结果为 **20/20（100%）**。真实模型入口不是 CI 门禁，且本文档不声明真实请求已经运行。成功退出 `0`，场景失败退出 `1`，配置、manifest 或报告预检失败退出 `2`。

P2/P3 收尾时检测到本机存在模型凭证，但真实 golden、single/Triad 对比和 credentialed
Evaluator 会向外部 provider 发送仓库派生内容，执行授权未获通过，因此仍记为未验证，
不能把凭证存在写成真实模型通过。

## 独立 Evaluator（显式 opt-in）

`forgeagent evaluate` 使用单独的真实模型会话检查声明的外部产物，会产生模型调用费用，
不属于基础 CI，也不会被普通 Task 或离线 golden 自动调用。命令只向 Evaluator 传入任务
描述、期望行为和 `artifact-root` 下显式列出的相对 artifact；声明文件会先复制到一次性
只读视图，未声明文件不可见。不传 Generator 对话、Memory、项目 Skills、MCP 或 audit sink。

```bash
uv run forgeagent evaluate --model claude-sonnet-5 \
  --artifact-root ./evaluation-output \
  --task-description "Export summary" \
  --expected-behavior "summary.json contains the total" \
  --artifact summary.json \
  --record-dir /tmp/forgeagent-evaluation
```

每个 artifact 必须是受限根目录内的规范相对 POSIX 路径，并受单文件、总大小和数量上限
约束。可选的 `--golden-report` 与 `--audit-jsonl` 生成
`forgeagent.evaluation.v1` 指标；缺失证据显示 `n/a`，不会伪造 0 或 100。audit JSONL
中由 Task 终态产生的 `task.outcome` 用于首轮正确率和修正轮数；没有该证据时两项保持
`n/a`。只有显式传入绝对 `--record-dir` 时才原子保存本次 record 和有界趋势。Evaluator 通过退出 `0`，未通过
退出 `1`，模型/产物/证据预检或持久化失败退出 `2`；真实模型评估不作为离线 CI 门禁。

## 开发

```bash
uv run pytest      # 运行全部测试（无需 key、无需网络）
uv run ruff check  # 静态检查
```

## 本地 HTTP 服务（可选）

HTTP 服务默认不启动，必须显式执行 `forgeagent serve --config PATH`。它只监听
loopback，不提供 TLS；配置文件负责模型、sandbox、allowed root、容量、TTL、审计和
精确 allowlist。`FORGEAGENT_HTTP_TOKEN` 优先于配置文件中的 `token`，修改 token 或
策略后重启生效，不支持热加载。完整路由、请求 schema、结果投影、取消和残余风险见
[`docs/http-task-service.md`](docs/http-task-service.md)。
