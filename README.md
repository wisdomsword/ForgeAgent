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
```

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

隔离强度 = 所选档位对应后端能提供的强度，与提示词或静态规则数量无关。来源完全不可信且后果严重时，不要在敏感环境运行（OS 级容器隔离规划在 M10，待定）。

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

