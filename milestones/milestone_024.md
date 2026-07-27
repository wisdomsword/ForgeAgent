# 里程碑 M24: 持续验证与平台矩阵

- 状态: 进行中
- 起止: 2026-07-27 ~ 2026-07-27
- 对应 ACTION_PLAN 行: M24（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_023](milestone_023.md)
- 技术设计: [2026-07-27-m24-continuous-verification-platform-matrix-design](../docs/superpowers/specs/2026-07-27-m24-continuous-verification-platform-matrix-design.md)
- 实施计划: [2026-07-27-m24-continuous-verification-platform-matrix](../docs/superpowers/plans/2026-07-27-m24-continuous-verification-platform-matrix.md)
- OpenSpec change: [`m24-continuous-verification-platform-matrix`](../openspec/changes/m24-continuous-verification-platform-matrix/)
- 验证报告: [2026-07-27-m24-continuous-verification-platform-matrix-verify](../docs/superpowers/reports/2026-07-27-m24-continuous-verification-platform-matrix-verify.md)

## 目标与范围

建立两个不可选失败的 GitLab verify job：离线质量/发布门禁，以及 Docker daemon 可用时的十项
容器集成门禁。平台矩阵只记录可复核状态，不把单次本机结果扩展为跨平台产品承诺。

## 方案设计

- `.gitlab-ci.yml` 固定 Node 22、Python 3.11、uv 0.11.1、OpenSpec 1.4.1、Docker 29.2.1 与
  `python:3.11-slim`，并保留构建及 JUnit 证据。
- `container_integration` 标记精确覆盖现有十项真实 Docker 测试；CI 对 tests=10、skipped=0、
  failures=0、errors=0 做硬断言。
- Docker job 绑定 `docker-privileged` runner，并把 `TMPDIR` 放在共享 build volume 中，保持
  ContainerBackend same-path bind mount 在 DinD service 中可见。
- Linux Docker 为 P0 configured；Podman 为 P1 scheduled；Windows 为 P2 deferred；macOS
  arm64 Docker Desktop 仅 supplemental。详细矩阵见 [`docs/platform-support.md`](../docs/platform-support.md)。

## 子任务清单

- [x] 添加 CI、平台与容器测试合同
- [x] 标记十项真实容器测试并注册 pytest marker
- [x] 编写离线验证 job
- [x] 编写 Linux Docker job 与 JUnit 零 skip 合同
- [x] 更新 README、ACTION_PLAN 与平台矩阵
- [ ] 在 Linux Docker runner 上执行完整证据 — 待 CI runner 可用
- [ ] 完成 Comet verify 与归档 — 依赖最终门禁

## 交付物清单

- [x] [`.gitlab-ci.yml`](../.gitlab-ci.yml) — 两个 required verify jobs
- [x] [`tests/test_continuous_verification.py`](../tests/test_continuous_verification.py) — CI/文档/标记合同
- [x] [`docs/platform-support.md`](../docs/platform-support.md) — 平台状态与证据边界
- [x] [`tests/test_container_backend.py`](../tests/test_container_backend.py) — 十项 integration marker

## 三次评审

### 技术方案评审

- [x] 未修改协作运行时或引入新产品依赖；平台状态与证据范围保持保守。
- [x] 离线与 Docker job 分离，Docker 不可用时不会把十项测试静默算作通过。

### 代码评审

- [x] 独立 reviewer 未发现 Critical，发现 3 个 Important 与 2 个 Minor
- [x] 已修复平台 tuple/schema、CI DinD/Artifacts 合同、M23 pyproject 保护范围、精确 marker
  名单与 base SHA，并通过定向及全量复验

### 验收评审

- [x] 完整离线 pytest `2309 passed, 10 skipped`；本机 Docker 全量 `2319 passed`
- [x] Golden `20/20`、OpenSpec strict `20/20`、Ruff、wheel/sdist 与发布边界通过
- [x] macOS Docker Desktop supplemental JUnit：tests=10、failures/errors/skipped=0
- [ ] Linux Docker 十项 tests=10 且零 skip — 依赖目标 GitLab runner，状态保持 configured

## 遗留问题

- [ ] Linux Docker/Podman/Windows 实机证据 — 影响：当前无法宣称跨平台验证 — 计划：按发布目标提供 runner 后执行。

## 续接指引

先在本机 Docker Desktop 运行十项测试并保存 supplemental 原始记录；随后运行所有离线门禁，
检查 CI YAML/JUnit 计数和发布边界，完成两轮自审，再执行 Comet verify、归档及主线合并。
