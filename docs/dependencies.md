# 依赖与环境

GitHub 仓库包含 ForgeAgent 源码、提示词、内置模型声明、测试与构建配置。
项目不依赖仓库外的参考源码或本机 Agent 插件；依赖包通过公开包管理器安装。

| 内容 | 是否必需 | 来源与用途 |
|---|---|---|
| Python ≥3.11 | 是 | 运行时；CI 验证 Python 3.11.15 |
| uv | 推荐 | 安装锁定依赖与构建；CI 使用 0.13.4 |
| Python 依赖 | 是 | `pyproject.toml` 声明八个直接依赖，`uv.lock` 固定完整依赖图 |
| 模型服务、账号与 Key | 真实任务需要 | 使用者自备；仅提交环境变量名称与无密钥配置示例 |
| Docker | container 档位需要 | 使用者安装并启动；worker 默认镜像 `python:3.11-slim` |
| pytest、Ruff | 开发需要 | 已包含在 uv 的 dev 依赖组 |
| Node.js、OpenSpec | 维护规格需要 | CI 使用 Node 22.22.0、OpenSpec 1.13.1 |
| Comet、CodeGraph | 可选 | 开发工作流与代码导航；不参与运行时和 CI 必需环路 |
| MCP 服务、Skills、Memory、用户数据 | 按需 | 用户启用对应功能时提供；不是启动必需文件 |
| `resource/agent/` | 否 | 只读历史参考，不进入构建或运行时 |

## 从公开仓库安装

先通过 [uv 官方说明](https://docs.astral.sh/uv/getting-started/installation/)
安装 uv，再执行：

```bash
git clone https://github.com/wisdomsword/ForgeAgent.git
cd ForgeAgent
uv sync --locked
uv run forgeagent --help
uv run forgeagent models
```

只安装运行时依赖可用 `uv sync --locked --no-dev`。构建 wheel/sdist 用 `uv build`，
uv 从 `pyproject.toml` 读取构建后端及传递依赖的版本约束。

用 pip 安装本地 wheel 时，可以从同一提交的锁文件导出经过依赖扫描的运行时解析结果。
请在新环境中运行：

```bash
mkdir -p artifacts
uv export --locked --no-dev --no-emit-project --no-hashes --no-annotate \
  -o artifacts/runtime-constraints.txt
python -m pip install -c artifacts/runtime-constraints.txt dist/forgeagent-0.1.0-py3-none-any.whl
```

该约束文件用于固定版本。通过源代码安装时，优先用 `uv sync --locked` 保留锁文件的哈希校验。

依赖需要从包索引下载，当前不提供离线依赖包或完整系统镜像。首次使用真实任务前，
按 [模型客户端契约](model-client-contract.md) 设置凭据与路由；自定义网关可参考
[`examples/gateway/`](../examples/gateway/)。示例只包含环境变量名称，没有可用凭据。

## 可选开发工具

规格维护工具安装命令：

```bash
npm ci --prefix tools/openspec --ignore-scripts --no-audit --no-fund
tools/openspec/node_modules/.bin/openspec validate --all --strict
```

`tools/openspec/package-lock.json` 锁定完整工具树。已知 picomatch 通告的处理和
复查期限见[整改记录](security/dependency-remediation-2026-11-18.md)。

需要 Docker 集成时，先启动 Docker，再执行：

```bash
docker pull python:3.11-slim
uv run pytest -q tests/test_container_backend.py -m container_integration
```

首次拉取镜像需要联网；worker 执行时禁网。第三方 Python 包不会自动进入 worker，
需要在自备镜像中安装并用 `--container-image` 选择。镜像标签可能随上游更新，
若需长期复现应记录实际 image digest。

Comet 和 CodeGraph 不是 CI 的安装前提。未安装时仍可直接编辑、测试和构建项目；
它们的配置与本机 Skills 不能替代仓库里的代码、测试或必要安装说明。
后续若选用这些工具，应按其上游授权与安装说明独立安装，不复制本机插件缓存。

用户配置 `~/.forgeagent/`、API Key、真实输入文件及运行历史由使用者管理。
不把这些文件补进公共仓库，也不在安装过程中自动覆盖现有配置。
