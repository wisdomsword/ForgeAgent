## Why

当前 sdist 依赖构建后端的默认文件发现，会把开发代理目录、OpenSpec 工作资料和用户本地文件带入发布物；README 的当前验证结果同时被历史 M22 测试数量合同锁死，导致新测试加入后文档难以诚实更新。

## What Changes

- 为 sdist 配置最小显式 allowlist，只发布包源码和构建所需的根文件。
- 增加发布物负向测试，禁止开发目录、OpenSpec 资料和用户本地文件进入 sdist。
- 在 README 中建立格式稳定的“当前验证”章节，记录本次新鲜验证结果。
- 调整协作文档合同测试，只验证当前验证章节存在且格式正确；保留历史报告、ACTION_PLAN 和 M22 里程碑中的历史数字。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `golden-validation-core`: 将发布内容边界与 README 当前验证证据格式纳入机器验证合同，同时不把易变数量定义为永久值。

## Impact

- 构建配置：`pyproject.toml`。
- 自动化测试：`tests/test_packaging.py`、`tests/test_collaboration_docs.py`。
- 当前文档：`README.md`。
- 不修改运行时、公共 API、依赖、历史报告或里程碑证据。
