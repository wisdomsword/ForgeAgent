# Comet Design Handoff

- Change: m28-v0-1-release-candidate
- Phase: design
- Mode: compact
- Context hash: 4c4d92e556546787ed03843a4094c345b1bb8e116d288796728d3ef22a960521

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/m28-v0-1-release-candidate/proposal.md

- Source: openspec/changes/m28-v0-1-release-candidate/proposal.md
- Lines: 1-27
- SHA256: c1cb64b9993db645cefc2fce966cfe0587d73b677c798085f22ddcada1ceaf64

```md
## Why

ForgeAgent 已具备 `0.1.0` 包元数据和各入口的分散测试，但尚无一条从干净 wheel 安装出发、同时覆盖 CLI、HTTP 与 Single/Duo/Triad 协作入口的发布候选门禁。M28 将这些证据收敛为可在 Linux Docker CI 重复执行的 RC 验收，并冻结发布说明与已知限制，避免把“源码测试通过”误当作“发布包可用”。

## What Changes

- 构建 wheel/sdist，在隔离的 Python 3.11 环境安装 wheel，并证明运行时模块与 `forgeagent` 命令来自该环境而非源码树。
- 新增一条确定性、离线、无凭据的 RC 冒烟入口，覆盖安装后 CLI、HTTP 任务生命周期，以及显式 Single、Duo、Triad 协作终态。
- 将 RC 冒烟接入 Linux Docker CI；失败、跳过或未产出机器可读证据均阻止候选发布。
- 发布 `0.1.0` RC 说明，冻结安装方式、支持范围、验证证据和已知限制。
- 保持现有默认 Single 路由、HTTP/协作公开契约与安全边界不变；不新增运行时依赖。

## Capabilities

### New Capabilities

- `release-candidate-verification`: 定义从干净 wheel 安装到 CLI、HTTP、Single/Duo/Triad 冒烟及发布文档冻结的一体化 RC 验收合同。

### Modified Capabilities

- `continuous-verification`: 将安装后 RC 冒烟及其机器可读证据加入必需的 Linux Docker CI 发布门禁。

## Impact

- 影响 packaging 测试、发布候选 smoke 脚本、GitLab Linux Docker job、README/发布说明、平台支持与里程碑台账。
- 不改变产品 public API、协议 schema、模型路由、凭据处理或 sandbox 语义。
- 不执行 PyPI 上传、Git tag、push 或真实外部模型请求；这些动作和证据不属于 M28。

```

## openspec/changes/m28-v0-1-release-candidate/design.md

- Source: openspec/changes/m28-v0-1-release-candidate/design.md
- Lines: 1-67
- SHA256: 963c5f5aafe590e2e42dc9998f35e7b67b2c338d7303ab54c01a0fd58f175b70

```md
## Context

ForgeAgent 已有显式 wheel/sdist 内容边界、隔离导入探针、完整 pytest/Golden/OpenSpec 离线门禁，以及 Linux Docker 十项 container integration 门禁。缺口在于这些证据彼此分散：当前 packaging 测试只证明安装后导入和 prompt 资源，Linux Docker job 只证明 container backend；它们都没有从同一 wheel 贯穿已安装 CLI、真实 loopback HTTP 与三种协作模式。`0.1.0` 已是项目版本，因此 M28 聚焦候选验证和发布信息冻结，不扩大产品能力。

## Goals / Non-Goals

**Goals:**

- 用一条可复用的确定性离线 harness 验证干净 wheel、CLI、HTTP、Single/Duo/Triad。
- 同一 harness 同时服务本地 packaging 合同和 Linux Docker CI，输出稳定 JSON 证据。
- 冻结 `0.1.0` RC 发布说明、平台证据边界和已知限制。
- 不新增依赖，不改变公开运行时协议、路由或 sandbox 语义。

**Non-Goals:**

- 不上传 PyPI、不创建或推送 tag/分支，不声明正式 GA。
- 不调用真实模型，不验证外部 provider 可用性或费用/质量。
- 不新增平台支持，不把 macOS Docker、Podman 或 Windows 外推为 Linux RC 证据。
- 不重构 CLI、HTTP 或 collaboration runtime，不恢复任何自动 Triad 类别。

## Decisions

### 1. 使用单一仓库级 Python harness，而非新增产品子命令

新增一个窄的 `scripts/` 验证入口。父进程负责创建临时 Python 3.11 venv、安装指定 wheel 并清洗 import 覆盖；子进程在 isolated mode 下执行安装后验证。它只使用 Python 标准库、现有 `uv` 命令与已安装 ForgeAgent API。

选择该方案是因为 RC smoke 属于发布工程而非用户能力。新增 `forgeagent rc-smoke` 会永久扩大 public CLI；为每个入口创建独立脚本又会复制环境准备与证据格式。

### 2. CLI 走 console script，HTTP 走 loopback，协作走真实 runtime + MockClient

- CLI 直接执行 venv 中的 `forgeagent` console script，验证帮助与包内模型目录，确保 entry point 和 package data 同时有效。
- HTTP 使用 `127.0.0.1:0` 启动真实 server，通过 `urllib` 发 bearer 请求，覆盖拒绝未授权请求以及 submit/query/cancel；任务主体用本地可取消替身，避免 provider 和身份配置。
- Single 使用真实 `Task` 与确定性 `MockClient`；Duo/Triad 使用真实 `CollaborationRunner`、store、角色 registry 和结构化 Submit 工具，只替换模型回复。Triad 的计划确认由 harness 固定批准，不引入人工输入。

这比复用 pytest 内部 helper 更接近安装后的公开边界，也避免 wheel smoke 依赖未发布的 `tests/` 包。

### 3. 一份版本化 JSON 是 CI 证据边界

报告只保存 schema、候选版本、Python 版本、wheel SHA-256，以及 `clean-wheel`、`cli`、`http`、`single`、`duo`、`triad` 六项稳定状态。失败只记录固定检查名和固定错误类别，详细 subprocess 输出保留在有界 stderr，不写 secret、绝对路径、目标或模型文本。输出使用临时文件加 `os.replace()` 原子发布。

### 4. Linux Docker job 在既有十项门禁后运行同一 RC smoke

保留现有 DinD、非 root 执行和 JUnit 精确计数，随后构建 wheel、运行 harness 并校验 JSON 六项全通过。这样 RC 证据与真实 Linux Docker topology 绑定，不新增一套 CI 服务或 Dockerfile。现有 offline job 继续承担全 pytest、Golden、OpenSpec strict 与分发包构建。

### 5. 单一 RC 文档冻结发布口径

新增一份版本化 `docs/releases/0.1.0-rc.md`，集中记录安装、能力、验证、正式发布阻塞条件和已知限制；README 只链接并给出精简候选状态，`docs/platform-support.md` 记录新的 Linux RC 证据。测试只守住必需章节与不夸大边界，不锁死自然语言全文。

## Risks / Trade-offs

- **[MockClient 只能证明产品装配，不能证明 provider 连通性]** -> 发布说明将真实模型列为 opt-in/未由 RC CI 验证，不把离线结果外推。
- **[loopback 被受限执行环境禁止]** -> 本地如实报告未验证；required Linux runner 必须真实执行且不接受 skip。
- **[clean venv 安装依赖需要索引或预热缓存]** -> CI 使用锁定工具环境并保留安装失败为真实 gate；不通过复用开发 venv 绕过。
- **[直接使用运行时 API 的协作 smoke 对内部构造有一定耦合]** -> 仅覆盖最小结构化完成路径；这种耦合是预期的 RC 装配回归信号，不抽象新测试框架。
- **[Linux job 时间增加]** -> 复用已有 checkout/cache，只增加一次 wheel build、clean install 和短离线 smoke，不重复全套 pytest。

## Migration Plan

1. 先以测试锁定报告 schema、环境隔离、HTTP/协作成功和失败语义。
2. 实现最小 harness，并让 packaging 合同对构建 wheel 调用它。
3. 将同一命令加入 Linux Docker job并发布 JSON artifact。
4. 完成 RC 发布说明、平台证据和 README 链接；运行全部门禁后记录实际结果。
5. 若门禁不稳定，可移除新 CI 命令和 harness，现有十项 container gate 与产品 runtime 不受影响。

## Open Questions

无。M28 的所有产品与发布边界已在用户请求和本设计中冻结；真实发布动作留给单独授权。

```

## openspec/changes/m28-v0-1-release-candidate/tasks.md

- Source: openspec/changes/m28-v0-1-release-candidate/tasks.md
- Lines: 1-26
- SHA256: fa5fca78dea62a9da67a3e0dfb6d677227ecb65236ae3c7281f5d23782454566

```md
## 1. RC smoke 合同

- [ ] 1.1 为 clean-wheel 环境隔离、报告 schema、失败非零与脱敏边界增加测试。
- [ ] 1.2 为安装后 CLI、真实 loopback HTTP 和显式 Single/Duo/Triad 离线终态增加测试。

## 2. RC smoke 实现

- [ ] 2.1 实现单一 `0.1.0` RC smoke harness：构建/接收 wheel、创建 Python 3.11 venv、安装并验证模块与 console script 来源。
- [ ] 2.2 实现 CLI/HTTP/Single/Duo/Triad 子检查和原子、版本化 JSON 报告，不新增运行时依赖或产品命令。
- [ ] 2.3 让 packaging 合同调用同一 harness，并保留现有 wheel/sdist 内容负向边界。

## 3. Linux Docker CI

- [ ] 3.1 在既有 required Linux Docker job 中构建候选 wheel、以非 root 用户运行 RC smoke，并校验六类证据全部通过。
- [ ] 3.2 发布 RC JSON 与既有 container JUnit artifact；保持十项 container integration 精确计数、零 skip 约束。

## 4. 发布冻结

- [ ] 4.1 编写 `0.1.0` RC 发布说明，冻结安装、能力、验证口径、正式发布阻塞条件和五类已知限制。
- [ ] 4.2 更新 README、平台支持矩阵和文档合同测试，确保不把未执行或历史证据描述为当前通过。

## 5. 验证与收尾

- [ ] 5.1 运行 RC/packaging/CLI/HTTP/协作专项、Ruff、完整 pytest、Golden 20/20、OpenSpec strict、build 与本机可用的 Docker 门禁。
- [ ] 5.2 完成独立代码审查与两轮最终一致性复审，修复全部发现并记录无法执行的环境证据。
- [ ] 5.3 生成 M28 验证报告与 milestone，更新 `ACTION_PLAN.md` 和 `milestones/latest`，归档 change。

```

## openspec/changes/m28-v0-1-release-candidate/specs/continuous-verification/spec.md

- Source: openspec/changes/m28-v0-1-release-candidate/specs/continuous-verification/spec.md
- Lines: 1-24
- SHA256: ba96398eefc2e7478d226faa80a8b69ae5e7824ea43a884f39603cbabc552f50

```md
## MODIFIED Requirements

### Requirement: Required Linux Docker container gate
The repository SHALL define a required Linux Docker CI job that proves daemon availability, makes the fixed worker image available, runs exactly the ten marked real container integration and escape tests without accepting skips as success, builds the release artifacts, installs the wheel into a clean Python 3.11 environment, and runs the complete offline RC smoke suite against that installed wheel. The job SHALL publish machine-readable JUnit and RC smoke evidence.

#### Scenario: Docker environment is ready
- **WHEN** the pinned Docker CLI can reach its daemon and inspect the fixed worker image
- **THEN** the job runs the ten `container_integration` tests and succeeds only when all ten pass

#### Scenario: Docker daemon or image is unavailable
- **WHEN** daemon preflight or worker-image preparation fails
- **THEN** the job fails before pytest rather than producing a successful result with ten skipped tests

#### Scenario: Container test is skipped or fails
- **WHEN** any selected container integration test does not pass
- **THEN** the required Docker job fails and the platform cannot be recorded as verified

#### Scenario: Installed-wheel RC smoke passes on Linux
- **WHEN** the Linux Docker job builds the candidate artifacts and runs the RC smoke harness in a newly created Python 3.11 environment
- **THEN** clean-wheel, CLI, HTTP, Single, Duo, and Triad checks all pass and the job publishes the versioned JSON report

#### Scenario: Installed-wheel RC smoke is incomplete or fails
- **WHEN** wheel installation fails, any required smoke is skipped or fails, or the JSON report is absent or incomplete
- **THEN** the Linux Docker job fails and the candidate cannot be represented as release-ready

```

## openspec/changes/m28-v0-1-release-candidate/specs/release-candidate-verification/spec.md

- Source: openspec/changes/m28-v0-1-release-candidate/specs/release-candidate-verification/spec.md
- Lines: 1-67
- SHA256: b6fd57671351391668062b71b2512eb4962821acf911ac3794891b189b11cd7e

```md
## ADDED Requirements

### Requirement: 发布候选必须从干净 wheel 安装验收
ForgeAgent `0.1.0` 发布候选 MUST 在新建的 Python 3.11 隔离环境中只从构建出的 wheel 安装运行时及依赖。验收 MUST 清除 `PYTHONPATH`、`PYTHONHOME` 等源码覆盖，并证明导入模块与 console script 均来自该隔离环境；不得用仓库 `src/` 或开发虚拟环境冒充安装成功。

#### Scenario: 干净 wheel 安装成功
- **WHEN** RC 门禁构建 wheel 并在空隔离环境安装该 wheel
- **THEN** `forgeagent` 可导入、所需包资源可读取、console script 可执行，且模块路径位于隔离环境内

#### Scenario: 源码树遮蔽安装缺陷
- **WHEN** wheel 缺文件或安装后入口损坏，但仓库源码仍可直接导入
- **THEN** 隔离探针仍失败，不得把源码导入结果计为 RC 通过

### Requirement: 安装后 CLI 冒烟必须离线且确定
RC 门禁 MUST 通过 wheel 生成的 `forgeagent` console script 执行无凭据、无网络、非交互的 CLI 冒烟，并核对稳定的成功状态和关键输出。CLI 冒烟 MUST NOT 发起真实模型请求。

#### Scenario: 安装后 CLI 可用
- **WHEN** 隔离环境执行 CLI 帮助和内置模型目录探针
- **THEN** 两个命令均以零状态退出，并显示 ForgeAgent 命令帮助和包内模型信息

#### Scenario: console script 未生成或资源缺失
- **WHEN** wheel 未安装 `forgeagent` 入口或 CLI 不能读取包内资源
- **THEN** CLI 冒烟失败并阻止 RC 通过

### Requirement: 安装后 HTTP 冒烟覆盖真实请求生命周期
RC 门禁 MUST 使用安装后代码启动仅绑定 loopback 临时端口的 HTTP 服务，通过真实 HTTP 请求验证鉴权、提交、查询与取消生命周期，并在结束后有界关闭服务。该冒烟 MUST 使用确定性本地任务替身，不加载凭据、MCP、Memory、Skills 或外部模型。

#### Scenario: HTTP 提交查询取消成功
- **WHEN** smoke client 使用合法 bearer token 提交一个受控任务、查询其公开状态并请求取消
- **THEN** 服务返回约定状态码与有界公开投影，任务进入稳定取消终态，监听线程和 worker 被关闭

#### Scenario: HTTP 鉴权仍生效
- **WHEN** smoke client 不带有效 bearer token 请求受保护端点
- **THEN** 服务拒绝请求且不创建任务

### Requirement: 安装后协作冒烟覆盖 Single Duo Triad
RC 门禁 MUST 使用安装后的运行时和确定性 MockClient 脚本分别执行显式 Single、Duo、Triad。Duo MUST 完成 Generator 与 Evaluator 的结构化提交；Triad MUST 额外完成 Planner 计划冻结；所有模式 MUST 验证稳定终态且不得访问真实 provider。

#### Scenario: 三种显式模式均完成
- **WHEN** RC 冒烟依次执行 Single、Duo、Triad 的固定离线脚本
- **THEN** Single 返回普通 completed 结果，Duo 与 Triad 返回各自 mode 的 completed 协作报告，Triad 包含已冻结并通过的计划项

#### Scenario: 任一角色或结构化提交回归
- **WHEN** Planner、Generator 或 Evaluator 的入口、工具协议、状态持久化或终态投影不再满足固定脚本
- **THEN** 对应模式失败，整个 RC 门禁返回非零状态

### Requirement: RC 冒烟产生机器可读且不泄密的证据
RC 门禁 MUST 原子写出一个版本化 JSON 报告，记录候选版本、Python 版本、wheel 文件摘要、各 smoke 名称与 pass/fail 状态。报告 MUST NOT 包含环境变量值、凭据、目标正文、模型回复、绝对临时路径或文件内容；任一检查失败时进程 MUST 非零退出且不得生成全通过结论。

#### Scenario: 全部检查通过
- **WHEN** clean-wheel、CLI、HTTP、Single、Duo、Triad 全部成功
- **THEN** JSON 报告完整列出六类成功证据并以零状态退出

#### Scenario: 检查失败
- **WHEN** 任一检查抛错、超时、被跳过或返回不符合契约的结果
- **THEN** 进程以非零状态退出，报告标记对应失败且不包含敏感诊断原文

### Requirement: 发布说明与已知限制在 RC 时冻结
仓库 MUST 提供 `0.1.0` RC 发布说明，明确安装命令、已交付入口、验证口径、发布前阻塞条件以及冻结的已知限制。限制 MUST 至少覆盖平台证据边界、真实模型验证边界、sandbox 安全边界、HTTP 暴露边界和协作 v1 边界；文档 MUST NOT 把未执行证据写成通过。

#### Scenario: 用户评估 RC
- **WHEN** 用户阅读 `0.1.0` RC 发布说明
- **THEN** 用户可区分已验证能力、opt-in 或未验证能力、已知限制及正式发布前仍需满足的条件

#### Scenario: 限制被静默弱化
- **WHEN** 文档删除必需限制类别或把历史、supplemental、配置态证据描述成当前正式验证
- **THEN** 发布文档合同测试失败并阻止 RC 通过

```
