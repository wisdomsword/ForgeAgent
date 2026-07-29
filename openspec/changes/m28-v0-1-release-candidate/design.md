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
