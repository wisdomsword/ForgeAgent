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
