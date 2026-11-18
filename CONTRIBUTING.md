# Contributing to ForgeAgent

从 [依赖与环境说明](docs/dependencies.md) 建立环境。运行时依赖以 `pyproject.toml`
和 `uv.lock` 为准；测试使用仓库内的 fixtures，不需要模型 Key。

```bash
git clone https://github.com/wisdomsword/ForgeAgent.git
cd ForgeAgent
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run python -m tests.golden.runner
openspec validate --all --strict
uv build
```

`openspec` 是可选的规格维护工具，安装方式见依赖说明。普通使用者不需要它。
Docker 集成需要运行中的 Docker 和本地 `python:3.11-slim` 镜像；没有这些条件时，
相关用例会跳过。GitHub CI 的独立 Linux Docker job 要求十项用例零跳过。

修改应围绕具体问题，保留安全边界，为非平凡行为补充回归测试。提交前检查 `git diff`，
运行对应测试与 Ruff；涉及规格时同步验证 OpenSpec。遵循 conventional commits。

真实模型验收是独立、显式收费的操作，见 [验收指南](docs/live-model-acceptance.md)。
不要把 Key、个人配置、真实用户输入或原始响应提交到仓库。验收输出默认进入忽略的
`artifacts/`，公开报告需要人工检查后另行整理。依赖变更应同时提交 `pyproject.toml`
和 `uv.lock`；不要提交虚拟环境、下载的 SDK 源码或 Docker 镜像。
