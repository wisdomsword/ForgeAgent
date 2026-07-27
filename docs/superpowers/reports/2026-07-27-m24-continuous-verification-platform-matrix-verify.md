# M24 持续验证与平台矩阵验证报告

日期：2026-07-27

## 范围

M24 只增加仓库验证基础设施：两个必需的 GitLab job、精确的容器测试 marker、离线 CI
合同、平台证据矩阵和里程碑文档。没有修改 `src/forgeagent/`、协作行为、credential、模型
路由或 sandbox 策略。

## 验证结果

| 门禁 | 结果 |
| --- | --- |
| CI/文档合同 | `4 passed` |
| Docker 从 `PATH` 隐藏后的完整离线 pytest | `2309 passed, 10 skipped` |
| Docker 可用时的本机完整 pytest | `2319 passed` |
| macOS Docker Desktop 容器专项 | JUnit `tests=10`、`failures=0`、`errors=0`、`skipped=0` |
| Golden 离线 runner | `20/20 passed (100.0%)` |
| Ruff check | 通过 |
| Ruff format check | 108 个文件格式正确 |
| OpenSpec strict | 含 M24 active change，`20 passed, 0 failed` |
| wheel/sdist build | 两种产物构建成功 |
| 发布内容边界 | 随完整 pytest 通过 |
| 精确 offline CI 镜像 bootstrap | Node 22.22.0、Python 3.11.2、uv 0.11.1、OpenSpec 1.4.1 |
| 精确 Docker CLI 镜像 bootstrap | Docker 29.2.1、Python 3.12.13、uv 0.11.1 |
| git diff whitespace | 通过 |

在 main fast-forward 合并后，再次执行完整离线 pytest，结果仍为
`2309 passed, 10 skipped`；Docker 专项再次为 `10 passed, 4 deselected`。

补充容器测试环境为 macOS 26.5.1 arm64、Docker client/server 29.2.1、Linux arm64
daemon，以及 `python:3.11-slim` 镜像
`sha256:e031123e3d85762b141ad1cbc56452ba69c6e722ebf2f042cc0dc86c47c0d8b3`。

## 自审一：合同与历史证据

- 删除 M23 测试中“`milestones/latest` 必须永远指向 M23”的错误冻结；M23 里程碑及证据
  链接仍保持不变。
- M23 pyproject 快照只剔除 M24 新增的 pytest marker 后做整份结构等值比较；运行时文件、
  `uv.lock`、依赖、入口、构建后端和发布边界仍受历史合同保护。
- 确认 M22/M23 历史测试数字和报告未被改写；只有 README 当前验证段及 M24 记录使用新数字。
- 消除 M24 合同中的 `2305` 硬编码，改为验证“当前验证”章节唯一且格式正确。

## 自审二：CI 可执行性与证据边界

- 发现 OpenSpec 1.4.1 要求 Node >=20.19；将不兼容的 Debian Node 路径改为已验证多架构
  tag `node:22.22.0-bookworm-slim`，并安装 Debian Python 3.11。
- 两条 bootstrap 路径补齐 `--break-system-packages`，并实际执行两个精确 job 镜像的版本检查。
- 发现 ContainerBackend 的 same-path bind mount 在远端 DinD service 使用私有 `/tmp` 时可能
  失败；Docker job 现要求 `docker-privileged` Docker executor，并固定
  `TMPDIR=$CI_PROJECT_DIR/.tmp`，使临时目录位于共享 build volume。
- 两个 job 均位于必需的 `verify` stage，不允许失败；daemon/image 预检、JUnit 计数和证据
  artifact 都是硬门禁。

## 独立 Diff Review

独立 reviewer 未发现 Critical，发现 3 个 Important，均在最终门禁前修复：

- 平台矩阵扩展为精确 platform tuple，并增加 prerequisites、current evidence、limitations 和
  next Comet trigger 字段。
- CI 合同补齐 workflow 失败策略、Git depth、artifact、DinD endpoint/TLS/TMPDIR、privileged
  runner tag 与 JUnit 发布检查。
- M23 pyproject 保护恢复为整份解析文档比较，只忽略 M24 的 marker，不再仅比较依赖数组。

另有 2 个 Minor 也已修复：marker 合同精确匹配十个具名 `docker_required` 测试；实施计划的
base SHA 修正为真实提交对象。所有 review 修复后均完成定向和全量复验。

## OpenSpec 完整验证

| 维度 | 状态 |
| --- | --- |
| 完整性 | 8/8 tasks 完成；4/4 requirements 已实现 |
| 正确性 | 10/10 scenarios 已映射到 CI、测试、构建证据或平台状态规则 |
| 一致性 | OpenSpec design、技术设计、实施计划、CI、测试和公开文档一致 |

- Mandatory offline pipeline：`.gitlab-ci.yml` 与结构化合同覆盖全部必需命令、失败行为和
  Golden/dist artifacts。
- Release boundary：offline job 运行现有真实 packaging 合同，再生成 wheel/sdist；最终构建
  和 packaging 测试通过。
- Linux Docker gate：精确十项 `docker_required` 测试带 integration marker；daemon/image
  预检以及 JUnit tests/failures/errors/skips 均为硬失败条件。
- Platform matrix：四个平台 tuple 都包含优先级、状态、前置条件、证据、限制与下一 Comet
  触发点；没有缺少证据的平台被标为 `verified`。

OpenSpec 验证没有遗留 Critical、Warning 或 Suggestion。

## 限制

本工作区没有目标 GitLab runner，因此没有实际执行 GitLab pipeline。Linux Docker 保持
`configured`，不能标为 `verified`。两个 job 镜像及依赖 bootstrap 已在本机执行，但这不能
证明 GitLab 调度、privileged DinD service 或共享 build-volume 拓扑。macOS Docker Desktop
结果仅是 supplemental。Podman 为 scheduled，Windows 为 deferred；均未宣称支持或验证通过。
