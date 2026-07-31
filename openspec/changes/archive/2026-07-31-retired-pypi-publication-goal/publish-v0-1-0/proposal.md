## Why

M28 和发布准备提交已证明 `0.1.0` 候选 wheel 满足本地与 required Linux 技术门禁，但人类实践与易用性优化尚未完成，且尚无 PyPI 项目、不可变 tag 或发布回读证据。正式发布必须在技术验证之外增加明确的人类使用门禁，避免把尚未实践成熟的候选固化为不可覆盖的公开版本。

## What Changes

- 保持 `0.1.0` 为已验证 Release Candidate，明确正式发布暂缓、PyPI 和 `v0.1.0` tag 均不存在，同时保留 M28 已冻结的验证边界与五类已知限制。
- 将人类实践、阻塞问题记录、易用性优化和回归验证加入正式发布门禁；在明确接受发布前不得上传或打 tag。
- 人类门禁通过后，从精确候选重新执行 required 门禁、构建发布产物，上传生产 PyPI，创建并推送 `v0.1.0` tag，再通过 PyPI JSON、下载摘要和远端 tag 回读留下证据。
- 不修改 ForgeAgent 运行时、公共 API、依赖、版本号或 M28 的历史 RC 证据。

## Capabilities

### New Capabilities
- `formal-release-publication`: 定义正式版本元数据冻结、精确候选门禁、PyPI 上传、不可变 tag 与发布回读证据的合同。

### Modified Capabilities

无。

## Impact

影响 README、`0.1.0` 发布说明及其静态合同、发布状态记录与 OpenSpec 发布规范。当前不创建 Git tag、不上传生产 PyPI；包名保持 `forgeagent`，版本保持 `0.1.0`，不新增依赖或配置面。
