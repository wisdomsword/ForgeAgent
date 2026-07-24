# ForgeAgent

轻量级 code-as-action Agent：LLM 把任务目标写成 Python 程序，通过执行程序完成任务。协议是纯文本 Markdown + HTML 注释标记，不依赖厂商 function-calling API，天然模型无关。

设计文档见 [`docs/`](docs/)，行动计划见 [`ACTION_PLAN.md`](ACTION_PLAN.md)，最高宪法见 [`spec.md`](spec.md)。

当前主线已完成 M17 Runtime Context Engineering、M18 Memory Runtime（含归档后两次
人工复测 hotfix）、M19 Skills Runtime（程序性知识从 Memory 分流到可验证、快照化、渐进
加载的 Skill）、M20 Eval（离线评估记录、趋势与显式 opt-in 独立 Evaluator）与 M21 Loop
Engineering（有界的耐久多 Task 迭代、版本化 checkpoint/resume、stop conditions、
HTTP/CLI/cron 调度示例）。收尾记录见
[`milestone_017.md`](milestones/milestone_017.md)、[`milestone_018.md`](milestones/milestone_018.md)、
[`milestone_019.md`](milestones/milestone_019.md)、[`milestone_020.md`](milestones/milestone_020.md)
和 [`milestone_021.md`](milestones/milestone_021.md)。M19 已通过无 API Key、无网络的本地
人类验收；归档后补充的 Startup-Information 已完成真实 TTY 启动标识、能力摘要、MCP
脱敏诊断和非 TTY 零启动噪声，并作为独立 OpenSpec change 归档。

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

模型在完成可独立验证的进度后调用 Loop 专用 `Checkpoint` 工具。工具成功返回前会原子
commit 新 revision；进程中断后的 resume 从最后一次 commit replay，已提交条目会作为
完成项注入下一次 Task，未提交的外部副作用可能重做。因此应把副作用切成可验证步骤，并在
每一步后 checkpoint；这不是外部操作的 exactly-once 承诺。

Loop 的稳定停止原因是 `completed`、`cancelled`、`wall_clock`、
`token_usage_unavailable`、`token_budget`、`max_rounds`、
`consecutive_failures`、`unrecoverable_failure` 和 `checkpoint_error`。round、token、
wall clock 与连续失败均按整个 Loop 累计；wall clock 是协作超时，不能强杀已在途的模型或
工具调用，只会在其返回后的安全边界停止。token usage 缺失不会被当成零而绕过预算。

Loop 会产生模型调用费用，token budget 只是上限而非报价。M20 的独立 Evaluator 仍是
显式 opt-in，普通 Loop 不会自动调用它；M22 的 Generator/Evaluator/Triad 打回语义也不在
M21 范围内。

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
- `/reload` — 重读 `~/.forgeagent/{models,config}.yaml`，配置写错时当场报错而非等到下次 run
- `/help [command]` — 列出全部指令，或查看某个指令的详细用法

REPL 命令必须以 `/` 开头。裸 `models`、`reload`、`mcp` 和 `mcp ...` 都是普通任务目标；这与顶层 CLI 子命令 `forgeagent models` 无关，后者仍用于列出模型。

Memory 只保存经过确定性准入的事实、偏好和决策。程序性做事方法会被拒绝并提示沉淀为 Skill；项目级冲突按后写入者替换，文件可直接编辑纠正。`--no-memory` 同时关闭两级记忆。

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

key 只从环境变量读取，**绝不写进配置文件或代码**，运行时才解析：

按**模型 → provider group** 精确路由，不做跨 group 优先级扫描：每个模型注册在 `res/config.yaml` 的唯一一个 group 下，请求该模型时只读取**它自己所属 group** 的 key/端点变量——其它 group 的环境变量即使设了也不生效（不会把 A 家的 key 发到 B 家的端点）。内置三个 group：

| Group | 模型 | key 变量 | 端点变量 |
|---|---|---|---|
| `anthropic` | claude-sonnet-5 / claude-opus-4-8 / claude-haiku-4-5 / claude-fable-5 | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL`（可选，不设则用官方端点） |
| `openai` | gpt-5.5 / gpt-5.4-mini | `OPENAI_API_KEY` | `OPENAI_BASE_URL`（必须含 `/v1`） |
| `llm` | glm-5.2 / deepseek-v4-flash | `LLM_API_KEY` | `LLM_BASE_URL`（必须含 `/v1`） |

缺对应 key 时报清晰错误并退出（退出码 2），不会崩溃、不会用错 group 的 key。可用 `~/.forgeagent/config.yaml`/`models.yaml` 扩展或覆盖分组与模型（见 [`docs/model-client-contract.md`](docs/model-client-contract.md)）。不硬编码任何厂商端点。

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
- **FileRead / FileWrite / FileList**（M10）：读/写/列出 `allowed_root` 下的文件，路径校验拒绝逃出项目根目录。FileRead 默认不设确认门（只在非 trusted 档记日志，不拦截）；**FileWrite 的确认门只是 UX 提示，不是安全边界**——Exec 工具跑的代码在 `restricted`/`container` 档下本来就能在 `allowed_root` 内任意写文件，不经过这个确认门。FileList 只返回相对路径，不暴露宿主真实目录结构。
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
- `<allowed_root>/.forgeagent/MEMORY.md`：项目级记忆，同 `AGENTS.md` 走确认门。当前版本只读——ForgeAgent 不会自动写入或提炼记忆内容，由用户手工维护。

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
