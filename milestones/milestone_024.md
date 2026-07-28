# 里程碑 M24: 持续验证与平台矩阵

- 状态: 已完成并归档
- 起止: 2026-07-27 ~ 2026-07-27
- 对应 ACTION_PLAN 行: M24（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_023](milestone_023.md)
- 技术设计: [2026-07-27-m24-continuous-verification-platform-matrix-design](../docs/superpowers/specs/2026-07-27-m24-continuous-verification-platform-matrix-design.md)
- 实施计划: [2026-07-27-m24-continuous-verification-platform-matrix](../docs/superpowers/plans/2026-07-27-m24-continuous-verification-platform-matrix.md)
- OpenSpec 归档: [`2026-07-27-m24-continuous-verification-platform-matrix`](../openspec/changes/archive/2026-07-27-m24-continuous-verification-platform-matrix/)
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
- Linux Docker 为 P0 verified（手工 runner 10/10；GitLab Pipeline 50 / Job 249 10/10）；Podman 为 P1 scheduled；Windows 为 P2 deferred；macOS
  arm64 Docker Desktop 仅 supplemental。详细矩阵见 [`docs/platform-support.md`](../docs/platform-support.md)。

## 子任务清单

- [x] 添加 CI、平台与容器测试合同
- [x] 标记十项真实容器测试并注册 pytest marker
- [x] 编写离线验证 job
- [x] 编写 Linux Docker job 与 JUnit 零 skip 合同
- [x] 更新 README、ACTION_PLAN 与平台矩阵
- [x] 手工 Linux Docker runner 证据 — 2026-07-28，10 passed、0 skipped、JUnit 非空
- [x] 完成 Comet verify、main fast-forward 合并与 OpenSpec 归档

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
- [x] macOS Docker Desktop supplemental JUnit：tests=10、failures/errors/skipped=0；镜像 digest
  `sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93`
- [x] GitLab Linux Docker 十项 tests=10 且零 skip — Pipeline 50 / Job 249：10 passed、0 skipped、0 failures、0 errors

## 遗留问题

- [ ] Podman/Windows 实机证据 — 影响：当前无法宣称这些平台已验证 — 计划：按发布目标提供 runner 后执行。

## 续接指引

M24 已归档并合并 main。Linux Docker 已有手工 dated runner 10/10 证据及 GitLab Pipeline 50 /
Job 249 的 10/10 证据，状态为 verified；该结论仅适用于记录的 runner 拓扑。Job 245 的 root
bootstrap 失败保留为审计记录。Podman 升为发布目标时
新建独立兼容性 change；Windows 仍 deferred，不在本里程碑扩展运行时。
