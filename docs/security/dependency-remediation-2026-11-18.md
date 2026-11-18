# 依赖整改记录（2026-11-18）

整改基线包含 24 组 Python 运行时通告、3 组 uv 通告和 1 组 npm 通告。
[依赖审计基线](dependency-audit-2026-11-18.md)

| 依赖 | 原版本 | 整改版本 |
|---|---|---|
| anyio | 4.14.1 | 4.14.2 |
| certifi | 2026.6.17 | 2026.10.18 |
| cryptography | 49.0.0 | 50.0.0 |
| mcp | 1.28.1 | 1.30.0，项目声明最低 1.30.0，保持 1.x |
| pyjwt | 2.13.0 | 2.15.0 |
| CI uv | 0.11.1 | 0.13.4 |

GitHub 和 GitLab 的独立依赖任务扫描 `uv.lock` 的全部平台版本、固定的 Python
构建依赖、CI 的 uv 和 OpenSpec npm 锁文件。扫描报告保存在
`artifacts/ci/dependency-audit/`。Python 锁文件使用 PyPI 和 OSV 交叉复扫，构建工具和
CI uv 使用 PyPI。构建环境的版本固定在 `pyproject.toml`。普通 wheel 安装的运行时
约束可从项目锁文件导出。[依赖与环境](../dependencies.md)

项目的 wheel 和源码包包含 MIT 许可与第三方说明。Windows 自包含包、离线包和容器
如内装第三方依赖，应核对实际产物并履行分发义务，包括 MPL 覆盖文件和 pywin32
附带的 LGPL 组件。[第三方声明](../../THIRD_PARTY_NOTICES.md)

## OpenSpec 工具的剩余通告

OpenSpec 1.13.1 的已锁定依赖树包含 picomatch 2.3.2。截至 2026-11-18，npm 上
picomatch 的最新版本是 4.0.7，仍在通告范围内。审计中另行解析的 OpenSpec 1.14.3
和 2.1.0 也命中同一通告。[GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf)

CI 使用固定工作目录命令验证仓库规格，不从请求参数读取 glob，并为任务配置超时。
这项防护限制 CI 暴露范围。上游补丁仍待发布，工具树仍会被扫描。门禁只在
**2026-12-18 UTC 之前**允许这一通告出现在固定位置的 picomatch 2.3.2 及其依赖方上。
每次命中均保留 JSON 并打印通告链接。新增通告、扫描错误或到期后仍命中都会阻断
依赖门禁。到期前复查 picomatch 和 OpenSpec 的发布版本，采用兼容修复并移除例外。

## 验证记录

`uv.lock` SHA-256 为
`452502674c88a0bf735225adf113babd2b79e0dc0f6178aa6040d1ddcc7c343a`。
PyPI 和 OSV 均扫描了 52 个外部 Python 包，零命中、零跳过。6 个构建包与 CI uv 的
PyPI 扫描也为零命中。npm 扫描仅命中上文已登记的通告。

MCP 回归用本地 schema fixture 检查文档内引用可用，以及 SDK 提供的显式 registry
拒绝查找不存在的资源。旧 SDK 上首次结果为 `assert None is not None`。
新版本通过检查。离线 Golden 为 20/20。wheel 与 sdist 均通过构建，归档实际包含
项目许可及第三方说明。扫描发生在 2026-11-18，结果与当日公开通告和精确版本对应。
