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
