---
comet_change: m24-continuous-verification-platform-matrix
role: technical-design
canonical_spec: openspec
---

# M24 持续验证与平台矩阵技术设计

## 1. 设计目标

M24 把当前里程碑收尾时人工执行的验证命令固化为 GitLab CI，并为 Docker container 测试建立不能被 skip 掩盖的独立门。设计只改变验证基础设施、测试标记和文档，不改变 ForgeAgent 产品代码、sandbox 行为、credential、模型路由或依赖锁。

规范事实源是 OpenSpec `continuous-verification` delta。本设计负责命令编排、CI 失败语义、证据格式和测试实现细节，不重新定义产品需求。

## 2. 当前事实与约束

- 远端是 GitLab，仓库当前没有 `.gitlab-ci.yml`。
- Python 要求为 3.11+，项目与开发依赖由 `uv.lock` 固定。
- OpenSpec CLI 是 npm 包 `@fission-ai/openspec`，当前验证版本为 1.4.1。
- `tests/test_container_backend.py` 有 14 项测试：4 项无 Docker 单测、10 项真实 Docker 集成/逃逸测试。
- 10 项真实测试的模块级 `skipif` 同时检查 daemon 和 `python:3.11-slim` 镜像；普通离线环境允许 skip，但 Docker 专用 job 不允许。
- `tests/test_packaging.py` 已真实构建 wheel/sdist，检查 sdist 顶层 allowlist、禁止开发/用户文件，并在隔离 venv 中验证 wheel 资源。
- GitLab DinD 需要仓库外的 privileged runner 配置；CI YAML 只能声明 service 和连接变量，不能自行提升 runner 权限。
- 当前本机是 macOS arm64，Docker Desktop 提供 Linux arm64 daemon；该结果是补充证据，不是原生 Linux runner 发布证据。

## 3. 方案比较

### 3.1 采用：直接 GitLab YAML

两个 job 直接列出验证命令，pytest marker 负责选择 Docker 测试，JUnit XML 负责证明测试数量和零 skip。优点是没有额外运行器抽象，失败命令在 CI 日志中直接可见，和现有 uv/pytest/OpenSpec 工具保持一致。

### 3.2 不采用：Python 验证 orchestrator

单个 Python 入口可在 CI/本地复用，但必须重新实现 subprocess、日志、退出码、artifact 路径和平台分支，实质上包装已有成熟 CLI。当前只有两个 jobs，不足以证明新增抽象的维护成本合理。

### 3.3 不采用：Makefile 或第三方任务运行器

Makefile 对 Linux runner 简洁，但不能解决 Windows 语义，并新增一层命令别名；第三方任务运行器还会增加依赖。本期直接命令更符合 YAGNI。

## 4. CI 架构

```text
branch / merge request
          |
          +--> offline-verification (generic Linux runner)
          |      Ruff check + format
          |      full pytest
          |      Golden 20/20
          |      OpenSpec strict
          |      uv build
          |      Golden + dist artifacts
          |
          +--> linux-docker-container (privileged Linux runner)
                 Docker CLI 29.2.1 -> DinD 29.2.1
                 daemon preflight -> image pull/inspect
                 pytest -m container_integration -> JUnit
                 assert tests=10, skipped=0
```

两个 job 位于同一 `verify` stage，可并行运行且都是 pipeline 成功的必要条件。不得设置 job 级或规则级 `allow_failure`。

### 4.1 全局配置

- `workflow.rules` 覆盖 merge request 和分支 pipeline，避免只在 main 运行后才发现问题。
- `GIT_DEPTH: "0"` 保留完整历史，因为既有测试会通过 `git show` 验证受保护文件基线。
- `UV_CACHE_DIR` 位于项目内 `.cache/uv` 并由 GitLab cache 保存。
- artifacts 使用固定仓库相对路径：`artifacts/ci/golden`、`artifacts/ci/container-junit.xml` 和 `dist/`。

### 4.2 `offline-verification`

运行环境使用 `node:22.22.0-bookworm-slim`（满足 OpenSpec 1.4.1 的 Node >=20.19），通过 Debian 包安装 Python 3.11、pip、venv 与 git，固定安装 `uv==0.11.1` 与 `@fission-ai/openspec@1.4.1`，然后执行 `uv sync --locked`。

脚本顺序：

1. `uv run ruff check .`
2. `uv run ruff format --check .`
3. `uv run pytest -q`
4. `uv run python -m tests.golden.runner --output-dir artifacts/ci/golden`
5. `openspec validate --all --strict`
6. `uv build --out-dir dist`

完整 pytest 已包含 `tests/test_packaging.py`，因此发布内容边界和隔离 wheel probe 仍是基础 job 的必需步骤；最后一次显式 build 生成供下载的 dist artifact。保留这次重复构建以区分“合同验证临时产物”和“CI 发布候选 artifact”，不修改 packaging 测试接口。

### 4.3 `linux-docker-container`

job image 固定为 `docker:29.2.1-cli`，service 固定为 `docker:29.2.1-dind`，别名 `docker`。按 GitLab 官方无 TLS DinD 连接方式设置 `DOCKER_HOST=tcp://docker:2375` 和空 `DOCKER_TLS_CERTDIR`；job 绑定 `docker-privileged` tag，管理员必须把对应 Docker executor runner 配置为 privileged。

Alpine job 安装 python3、pip 和 git，固定安装 uv 0.11.1 后执行 `uv sync --locked`。脚本先运行：

1. `docker info`
2. `docker pull python:3.11-slim`
3. `docker image inspect python:3.11-slim`

任一步失败都在 pytest 收集前使 job 失败。随后运行：

```bash
uv run pytest -q tests/test_container_backend.py \
  -m container_integration \
  --junitxml=artifacts/ci/container-junit.xml
```

pytest 成功后，用 Python 标准库 `xml.etree.ElementTree` 遍历 JUnit 根节点中的单个或多个 `testsuite`，求和 `tests`、`failures`、`errors`、`skipped`。仅当 `tests == 10` 且后三者均为 0 时成功。这样即使未来某项测试新增动态 skip，也不会得到绿色 job。

ForgeAgent 容器后端使用 same-path bind mount。Docker job 因此固定
`TMPDIR=$CI_PROJECT_DIR/.tmp`：测试临时目录和 worker skeleton 均位于 GitLab job 与 DinD
service 共同挂载的 build volume 下，不能落在各容器私有的 `/tmp`。

JUnit artifact 使用 GitLab `reports.junit` 发布，便于在 MR 中查看逐项结果；原始 XML 同时作为普通 artifact 保留。

## 5. 测试标记设计

在 pytest 配置中注册：

```toml
markers = [
    "container_integration: requires a real container daemon and worker image",
]
```

10 个当前带 `@docker_required` 的真实测试再增加 `@pytest.mark.container_integration`。4 个无 Docker 单测不带该 marker，仍由完整 pytest 在任何环境执行。

不删除现有 `docker_required` skipif：开发者在普通离线环境直接运行完整 pytest 时仍应得到可解释的 skip；Docker job 通过前置检查和 JUnit 断言收紧语义。

## 6. 离线 CI 合同测试

新增 `tests/test_continuous_verification.py`：

1. 用 `yaml.safe_load` 结构化读取 `.gitlab-ci.yml`。
2. 断言存在两个 job，stage 正确且不存在 `allow_failure: true`。
3. 断言基础 job 固定 Python、uv、OpenSpec 版本并包含六类命令与 artifact 路径。
4. 断言 Docker job 固定 CLI/DinD、连接变量、daemon/image preflight、marker 选择、JUnit 输出和结构化零 skip 校验。
5. 反射 `tests.test_container_backend` 中 `test_*` 函数的 `pytestmark`，断言总数 14、`container_integration` 恰好 10。
6. 断言平台矩阵包含四个平台元组、状态词、证据限制和后续 change 触发条件。
7. 断言 README、ACTION_PLAN 和 `milestone_024.md` 链接 CI、平台矩阵和真实 Docker 结果。

合同测试不调用 GitLab API、不需要 Docker、不解析日志文本，也不把易变的全量 pytest 数定义为永久产品合同。

## 7. 平台状态模型

平台文档使用以下有限状态：

- `verified`：指定 OS/arch/runtime 上全部要求通过，并有日期与证据引用。
- `configured`：自动验证已配置，但目标 runner 的完整结果尚未取得。
- `supplemental`：开发环境证据，仅能补充、不能满足发布目标。
- `scheduled`：已明确优先级、前置条件和后续 change。
- `deferred`：不是当前发布目标，且存在已知设计阻塞。

初始矩阵：

| 平台 | 优先级 | M24 状态 | 说明 |
|---|---:|---|---|
| Linux amd64/arm64 + Docker Engine | P0 | `configured` | required DinD job 已配置；拿到目标 runner 10/10 后可升级 |
| Linux + rootless Podman | P1 | `scheduled` | 需验证 CLI flags、挂载、网络、pids、user 和 kill 语义 |
| Windows native | P2 | `deferred` | drive-letter 冒号、rlimit、locking 和 container 隔离需独立设计 |
| macOS arm64 + Docker Desktop Linux daemon | 非发布门 | `supplemental` | 记录本地 10/10，不外推原生 Linux |

## 8. 真实验证

本地 Docker 验证必须记录：

- host OS/arch；
- `docker info` 的 Server OS/Architecture；
- worker image ID/digest；
- marker 收集数和 `10 passed, 0 skipped`；
- 执行日期和 commit。

仓库完整门包括 Ruff check/format、完整 pytest、Golden 20/20、OpenSpec change/all strict、显式 build、`tests/test_packaging.py`、`git diff --check`。CI YAML 只能通过合同测试和可选本地容器模拟验证；没有实际 push/pipeline 时不得声明 GitLab pipeline 已运行。

## 9. 失败与恢复

- 基础 job 任一步失败：修复对应 lint/test/spec/build 问题，不继续发布。
- Docker daemon/image preflight 失败：修复 runner/registry，不把测试改为 skip 或 allow failure。
- JUnit tests 不是 10：先检查 marker 漂移；需求变更必须更新 OpenSpec 和合同测试，不能静默改阈值。
- Podman/Windows 需求提前出现：创建独立 Comet change，不扩张 M24 runtime 范围。
- CI 配置需回滚：撤销 `.gitlab-ci.yml`、marker和文档即可，无数据迁移。

## 10. 完成标准

- OpenSpec 所有场景均有对应离线合同或真实证据。
- 本机 Docker 可用环境下 10 项 marker 测试全部通过且无 skip。
- 基础仓库门全部通过。
- 平台矩阵不包含超出证据的 `verified` 声明。
- README、ACTION_PLAN、milestone 与验证报告互相一致。
