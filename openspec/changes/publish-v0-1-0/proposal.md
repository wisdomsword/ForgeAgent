## Why

M28 已证明 `0.1.0` 候选 wheel 满足本地与 required Linux 门禁，但仓库公开说明仍明确标记为未正式发布，且尚无 PyPI 项目、不可变 tag 或发布回读证据。直接上传当前候选会把错误的 RC 状态固化进包索引，因此必须先冻结正式版合同，再发布并验证同一候选。

## What Changes

- 将 `0.1.0` 的公开包描述和发布说明从 Release Candidate 更新为正式发布状态，同时保留 M28 已冻结的验证边界与五类已知限制。
- 用自动化合同阻止正式发布文档重新出现“未正式发布”或 RC 安装路径，并要求稳定的 PyPI 安装与版本化 tag 信息。
- 仅在精确候选通过本地和 required Linux CI 后构建发布产物，上传生产 PyPI，创建并推送 `v0.1.0` tag，再通过 PyPI JSON、下载摘要和远端 tag 回读留下证据。
- 不修改 ForgeAgent 运行时、公共 API、依赖、版本号或 M28 的历史 RC 证据。

## Capabilities

### New Capabilities
- `formal-release-publication`: 定义正式版本元数据冻结、精确候选门禁、PyPI 上传、不可变 tag 与发布回读证据的合同。

### Modified Capabilities

无。

## Impact

影响 README、`0.1.0` 发布说明及其静态合同、发布状态记录、OpenSpec 发布规范、Git tag 和生产 PyPI。包名保持 `forgeagent`，版本保持 `0.1.0`，不新增依赖或配置面。
