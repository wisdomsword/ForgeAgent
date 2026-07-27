# Comet Design Handoff

- Change: m24-continuous-verification-platform-matrix
- Phase: design
- Mode: compact
- Context hash: 4296cfaf6c5a1ffea6dea05698a9fbc84505a4fd78bed274f9d953d5e28ebda3

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/m24-continuous-verification-platform-matrix/proposal.md

- Source: openspec/changes/m24-continuous-verification-platform-matrix/proposal.md
- Lines: 1-28
- SHA256: 3dd4d49c3a3ff0c140f30aac8af4c3252082e1c82020b53b04df4aad14bf8125

```md
## Why

ForgeAgent 的 Ruff、pytest、Golden、OpenSpec、构建和发布内容检查目前主要依赖人工在里程碑收尾时执行，Docker container 测试在 daemon 不可用时还会整体跳过。M24 需要把这些证据固化为持续验证门，并明确哪些平台已经验证、哪些仅排期，防止发布结论超出真实证据。

## What Changes

- 新增 GitLab CI 基础验证 job，持续执行 Ruff lint/format、完整离线 pytest、Golden 20/20、OpenSpec strict、wheel/sdist 构建和发布内容边界测试。
- 新增独立且非 `allow_failure` 的 Linux Docker job；先验证 daemon 和固定镜像，再只选择 10 项真实 container 集成/逃逸测试，禁止以 skip 伪装通过。
- 新增平台矩阵文档，记录 Linux Docker、Linux Podman 和 Windows 的发布优先级、当前证据、阻塞条件与后续 change 触发点。
- 新增离线合同测试，校验 CI 门禁、Docker job 的零 skip 语义以及平台矩阵状态，避免配置和文档漂移。
- 更新 README、ACTION_PLAN 和 M24 milestone，保留历史测试数字，不把易变计数定义为长期产品合同。

## Capabilities

### New Capabilities

- `continuous-verification`: 定义持续基础门禁、Docker container 专用验证门和证据驱动的平台支持矩阵。

### Modified Capabilities

无。

## Impact

- 新增 GitLab CI 配置及平台验证文档；新增对应测试和 M24 里程碑记录。
- CI 需要 Python 3.11、uv、Node/npm、OpenSpec 1.4.1；Docker job 需要可运行 privileged DinD 或等价 Docker daemon 的 Linux runner。
- 不新增产品依赖，不修改 `src/forgeagent/`、产品 CLI、协作运行时、credential 或 sandbox 行为。
- Podman 和 Windows 本期只排期，不声明支持；它们的兼容实现与真实验证必须进入后续独立 Comet change。

```

## openspec/changes/m24-continuous-verification-platform-matrix/design.md

- Source: openspec/changes/m24-continuous-verification-platform-matrix/design.md
- Lines: 1-69
- SHA256: d8c7b6bae8d1c565f3a04953994ae1b298c922bda742c39666af3fc09503e5a0

```md
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

```

## openspec/changes/m24-continuous-verification-platform-matrix/tasks.md

- Source: openspec/changes/m24-continuous-verification-platform-matrix/tasks.md
- Lines: 1-19
- SHA256: d6dfce20a15a3e1e7645047f8e1af03713b57ad8e4659a4c497cfb886b7f14c1

```md
## 1. 持续验证合同

- [ ] 1.1 为 GitLab 基础门、Docker job、10 项专用 marker 和平台矩阵编写离线失败合同
- [ ] 1.2 为 10 项真实 Docker 测试注册并应用 `container_integration` marker，保持 4 项无 Docker 单测始终执行

## 2. GitLab CI 门禁

- [ ] 2.1 新增必需的 `offline-verification` job，固定工具版本并执行 Ruff、完整离线 pytest、Golden、OpenSpec strict、build 和发布内容边界
- [ ] 2.2 新增必需的 `linux-docker-container` job，固定 Docker CLI/DinD、强制 daemon/镜像预检并执行 10 项 container 测试

## 3. 平台矩阵与公开文档

- [ ] 3.1 新增证据驱动的平台矩阵，明确 Linux Docker、Linux Podman、Windows 和 macOS Docker 的状态、优先级、限制与后续触发点
- [ ] 3.2 更新 README、ACTION_PLAN 和 milestone_024，保持历史验证数字不变并链接 CI/平台证据

## 4. 真实验证与收尾

- [ ] 4.1 在本机 Docker daemon + `python:3.11-slim` 环境运行 10 项 container 测试并记录 host/daemon 架构和结果
- [ ] 4.2 执行 Ruff、完整离线 pytest、Golden 20/20、OpenSpec strict、wheel/sdist 与内容边界，完成两轮自审和 Comet verify

```

## openspec/changes/m24-continuous-verification-platform-matrix/specs/continuous-verification/spec.md

- Source: openspec/changes/m24-continuous-verification-platform-matrix/specs/continuous-verification/spec.md
- Lines: 1-53
- SHA256: e87f520e5761b1f0cfeb78440bb74622b0d54c00de52bc9963d2ed38443f916f

```md
## ADDED Requirements

### Requirement: Mandatory offline verification pipeline
The repository SHALL define a GitLab CI job that runs Ruff lint and format checks, the complete offline pytest suite, the twenty-case Golden runner, OpenSpec strict validation, wheel and sdist builds, and the release-content boundary contract without model credentials.

#### Scenario: All offline gates pass
- **WHEN** a branch or merge-request pipeline runs in the pinned Python and tool environment
- **THEN** every offline gate completes successfully and the job publishes the Golden and distribution artifacts

#### Scenario: Any offline gate fails
- **WHEN** lint, formatting, pytest, Golden, OpenSpec, build, or release-content validation returns a non-zero result
- **THEN** the pipeline job fails and cannot be reported as a successful verification

### Requirement: Release artifacts preserve the explicit boundary
The continuous verification pipeline SHALL build a wheel and sdist and SHALL execute the packaging contract that rejects development directories and user-local files from the release artifacts.

#### Scenario: Forbidden release content appears
- **WHEN** a built sdist includes an agent/workflow/OpenSpec development path or a forbidden user-local file
- **THEN** the release-content contract fails the offline verification job

#### Scenario: Installed wheel lacks runtime resources
- **WHEN** the isolated wheel probe cannot import ForgeAgent or render its required prompt resources
- **THEN** the release-content contract fails the offline verification job

### Requirement: Required Linux Docker container gate
The repository SHALL define a required Linux Docker CI job that proves daemon availability, makes the fixed worker image available, and runs exactly the ten marked real container integration and escape tests without accepting skips as success.

#### Scenario: Docker environment is ready
- **WHEN** the pinned Docker CLI can reach its daemon and inspect the fixed worker image
- **THEN** the job runs the ten `container_integration` tests and succeeds only when all ten pass

#### Scenario: Docker daemon or image is unavailable
- **WHEN** daemon preflight or worker-image preparation fails
- **THEN** the job fails before pytest rather than producing a successful result with ten skipped tests

#### Scenario: Container test is skipped or fails
- **WHEN** any selected container integration test does not pass
- **THEN** the required Docker job fails and the platform cannot be recorded as verified

### Requirement: Evidence-driven platform matrix
The repository SHALL maintain a platform matrix that records release priority, current support state, evidence, prerequisites, limitations, and the next validation trigger for Linux Docker, Linux Podman, Windows, and local macOS Docker evidence.

#### Scenario: Platform has complete evidence
- **WHEN** the required commands pass on the named operating system, architecture, and runtime
- **THEN** the matrix may record that exact platform tuple as verified with a dated evidence reference

#### Scenario: Platform has no complete evidence
- **WHEN** a platform is only planned, partially exercised, or blocked by known runtime assumptions
- **THEN** the matrix records it as scheduled, deferred, or unsupported and does not imply release support

#### Scenario: Release target changes
- **WHEN** maintainers promote Podman or Windows to a release target
- **THEN** a separate Comet change MUST define and verify the required compatibility work before the matrix status becomes verified

```
