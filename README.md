# ForgeAgent

轻量级 code-as-action Agent：LLM 把任务目标写成 Python 程序，通过执行程序完成任务。协议是纯文本 Markdown + HTML 注释标记，不依赖厂商 function-calling API，天然模型无关。

设计文档见 [`docs/`](docs/)，行动计划见 [`ACTION_PLAN.md`](ACTION_PLAN.md)，最高宪法见 [`spec.md`](spec.md)。

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

# 附加图片：单个文件或整个目录（≤5MB/张、≤20 张），模型需支持图片输入
uv run forgeagent run "描述这张图" --image ./screenshot.png
```

每轮结束后打印会话级用量状态行（M10）：

```
usage: in=1234 out=567 cached=200 reasoning=0 (session total)
```

`in`/`out` 为累计 input/output tokens，`cached` 为命中缓存的 input tokens（Anthropic 的 cache_creation+cache_read 合并、OpenAI-compatible 的 `prompt_tokens_details.cached_tokens`），`reasoning` 为计费的 thinking/reasoning tokens（Anthropic 已并入 `out`，此处恒为 0；OpenAI-compatible 视供应商在标准/非标准字段间取值，见 [`docs/m9-streaming-multimodal-commands.md`](docs/m9-streaming-multimodal-commands.md) §8 S2）。

REPL 内输入 `/` 加回车查看指令菜单，或直接 `/help`。当前支持的指令：

- `/model [id-or-alias]` — 列出已登记模型，或切换本次会话使用的模型
- `/search <query>` — 联网搜索，结果只打印，绝不自动送进对话内容
- `/image <path> [goal...]` — 附加图片（文件或目录）；不带 goal 则暂存到下一条输入
- `/mcp [status|enable <s>|disable <s>]` — 看 MCP server 连接状态与工具清单、启停某个 server
- `/reload` — 重读 `~/.forgeagent/{models,config}.yaml`，配置写错时当场报错而非等到下次 run
- `/help [command]` — 列出全部指令，或查看某个指令的详细用法

旧的裸词命令（`models`/`reload`/`mcp status`）仍可用但已弃用，下个里程碑移除，用时会提示对应新指令。

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
- **WebFetch**（M10）：GET 单个 http(s) URL，经 SSRF 防护后抓取。正文存到 `allowed_root` 下的文件（模型可在后续轮用 Exec/FileRead 处理全文），`detail` 只回传预览（≤1MB 截断），未经审查的网页正文不会整段进模型上下文。`restricted`/`container` 档下这是**唯一**出网路径（Exec 在这两档不能开 socket），因此确认门在这两档是真实的安全边界，不是提示性的 UX。
- **FileRead / FileWrite / FileList**（M10）：读/写/列出 `allowed_root` 下的文件，路径校验拒绝逃出项目根目录。FileRead 默认不设确认门（只在非 trusted 档记日志，不拦截）；**FileWrite 的确认门只是 UX 提示，不是安全边界**——Exec 工具跑的代码在 `restricted`/`container` 档下本来就能在 `allowed_root` 内任意写文件，不经过这个确认门。FileList 只返回相对路径，不暴露宿主真实目录结构。
- **MCP**（M7）：调用外部 [MCP](https://modelcontextprotocol.io) server 暴露的工具，见下节。

出网与文件访问的边界详见 [`docs/threat-model.md`](docs/threat-model.md) T10a-T10c；SSRF 防护实现见 [`docs/m10-usage-observability-and-tools.md`](docs/m10-usage-observability-and-tools.md) §3.3（逐候选地址校验 + NAT64 解包 + 直连已校验 sockaddr 堵 DNS-rebinding TOCTOU + 重定向逐跳复检）。

## MCP 服务（连接外部工具）

配置了 MCP server 时，`MCP` 工具自动出现在工具集里；未配置则完全不出现。配置放在 `~/.forgeagent/mcp.yaml`，用与 Claude Desktop / Cursor **相同的 `mcpServers` 格式**（现有配置可直接粘贴）：

```yaml
mcpServers:
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/data"]
    autoApprove: [read_file, list_directory]   # 只读工具，跳过确认门
  github:
    command: docker
    args: ["run", "-i", "--rm", "-e", "GITHUB_TOKEN", "ghcr.io/github/github-mcp-server"]
    env: {GITHUB_TOKEN: "${GITHUB_TOKEN}"}       # ${VAR} 从环境变量取，绝不写字面 secret
```

- **多 server 同时接入**：启动时并发连接所有 `enabled` server，单个连不上只标记 unavailable、不影响其余。同名工具（两个 server 都有 `search`）靠调用里的 `server` 字段区分，不冲突。
- **确认门（安全边界）**：MCP server 在**主进程执行，不受 restricted 沙箱约束**。所以有副作用的工具调用会逐次要你确认（终端 y/N）；只有列在该 server `autoApprove` 里的只读工具才免确认。未批准 → 结构化拒绝，不执行。因此 `mcpServers` 里只应放你信任的可执行文件，`autoApprove` 只列真正只读的工具。安全模型详见 [`docs/threat-model.md`](docs/threat-model.md) T8。
- 每 server 可 `enabled: false` 暂时关掉、`expose: [toolA]` 只广告部分工具（控制注入系统提示词的工具清单体积）。REPL 里 `mcp status` 看连接状态。

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

## 开发

```bash
uv run pytest      # 运行全部测试（无需 key、无需网络）
uv run ruff check  # 静态检查
```

参考项目 `resource/agent/` 为只读借鉴对象，不属本项目代码，已排除在检查与测试之外。

