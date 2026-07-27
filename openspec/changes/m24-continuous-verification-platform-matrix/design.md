## Context

仓库远端托管在 GitLab，但当前没有 CI 配置。基础验证依赖 Python/uv、Node/npm/OpenSpec；`tests/test_container_backend.py` 包含 4 项无 Docker 单测和 10 项真实 Docker 集成/逃逸测试，后者当前用 daemon/镜像探测控制 skip。发布内容边界已经由 `tests/test_packaging.py` 对真实 wheel/sdist 构建、sdist allowlist 和隔离安装进行验证。

当前本机是 macOS arm64 + Docker Desktop，可提供补充证据但不能替代 Linux 发布环境。`ContainerBackend` 使用 Docker CLI 语义和 POSIX 同路径挂载；Windows 盘符会命中冒号拒绝，Podman 的 rootless mount、资源限制和 kill 语义也尚未验证。

## Goals / Non-Goals

**Goals:**

- 在 GitLab 分支和合并请求 pipeline 中强制执行完整基础验证门。
- 在具备 privileged DinD 的 Linux runner 中强制执行恰好 10 项真实 container 测试，daemon 或镜像不可用时明确失败。
- 以证据驱动的平台矩阵区分“已验证”“计划验证”“暂不支持”，并给出后续工作触发条件。
- 保持 CI 命令可在本地复现，不新增产品依赖或修改产品运行时。

**Non-Goals:**

- 不实现 Podman 适配、Windows container tier 或跨平台路径改造。
- 不把 macOS Docker Desktop 的通过结果声明为 Linux Docker 通过。
- 不运行 credentialed、真实模型或网络评估。
- 不建立发布、签名、部署或多 Python 版本矩阵。

## Decisions

### 1. 使用两个必需 GitLab CI jobs

`offline-verification` 在 Python 3.11 环境执行 Ruff check/format、完整 pytest、Golden、OpenSpec strict、显式 build 和发布内容合同。`linux-docker-container` 使用固定 Docker CLI/DinD 版本，只执行真实 container 测试。两个 job 都不设置 `allow_failure`。

选择 GitLab CI 是因为仓库远端已经是 GitLab；不同时维护 GitHub Actions。拆分 job 可让 Docker runner 前置条件独立可见，也避免基础测试依赖 privileged daemon。

### 2. 固定工具版本并保留锁文件事实源

基础 job 使用 Python 3.11、`uv==0.11.1` 和 `@fission-ai/openspec@1.4.1`，项目依赖继续由 `uv.lock` 固定。Docker job 固定 `docker:29.2.1-cli` 与 `docker:29.2.1-dind`，并拉取产品默认的 `python:3.11-slim` worker 镜像。

CI 工具版本显式固定，避免 runner 隐式全局工具漂移；不把这些 CI 工具加入产品依赖。

### 3. 为 10 项真实 container 测试增加专用 marker

10 项 Docker 集成/逃逸测试统一标记为 `container_integration`，CI 通过 `-m container_integration` 选择。job 在 pytest 前运行 `docker info` 和 `docker pull python:3.11-slim`；预检失败直接失败，不能让模块级 skip 产生绿色结果。离线合同测试同时断言 marker 数量为 10、job 命令包含预检且没有 `allow_failure`。

专用 marker 比复用 pytest 内建 `skipif` 更稳定，也比在 CI 中硬编码 10 个测试名更易维护。

### 4. 平台矩阵按发布目标分级

- P0：Linux Docker，M24 自动 CI 目标；需要真实 DinD runner 证据后才标为 verified。
- P1：Linux rootless Podman，在 Docker 门稳定后以独立 compatibility spike/change 验证；M24 状态为 scheduled。
- P2：Windows 原生，在产品决定正式支持 Windows 后再设计路径、rlimit/locking 替代和 container tier 语义；M24 状态为 deferred/unsupported。
- macOS Docker Desktop 仅记录开发机补充证据，不是发布平台门。

矩阵记录日期、架构、runtime、证据命令/报告和限制；无证据不得升级状态。

## Risks / Trade-offs

- [GitLab Runner 未启用 privileged DinD] → Docker job 会失败或无法调度；在平台文档中列为管理员前置条件，不用 `allow_failure` 掩盖。
- [CI 每次安装 Node/OpenSpec 增加耗时] → 保持配置直观并使用 GitLab cache；待有稳定内部基础镜像后再独立优化。
- [固定 Docker patch 版本需要维护] → 版本升级通过独立小 change，并重新运行 10 项证据。
- [本地 macOS 通过不能证明 Linux] → 验证报告分别标注 host 与 daemon OS/arch，Linux 证据只接受 Linux runner。
- [Windows 当前路径冒号限制] → 明确 deferred，不在 M24 顺手修改 runtime。

## Migration Plan

1. 合入 CI、marker 和离线合同测试；通用 runner 先运行基础 job。
2. 为 Docker job 配置 privileged Linux Runner 或等价隔离 daemon，运行 10 项测试。
3. 根据真实 pipeline 更新平台矩阵证据；若 runner 尚未提供，状态保持 configured/not-yet-evidenced。
4. 回滚只需撤销 CI 配置和 marker/文档；不涉及产品数据或 runtime 迁移。

## Open Questions

- 当前 GitLab 项目是否已有 privileged runner 由仓库外配置决定；本 change 不能从代码库内证明。CI 配置和管理员前置条件仍可完整交付，本地 Docker 10/10 作为补充证据。
