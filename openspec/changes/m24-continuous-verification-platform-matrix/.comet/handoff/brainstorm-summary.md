# Brainstorm Summary

- Change: m24-continuous-verification-platform-matrix
- Date: 2026-07-27

## 确认的技术方案

采用直接 GitLab CI 配置，不新增验证 orchestrator 或 Makefile。`offline-verification` 固定 Python 3.11、uv 0.11.1 和 OpenSpec 1.4.1，执行 Ruff lint/format、完整离线 pytest、Golden 20/20、OpenSpec strict、wheel/sdist build，并发布 Golden 与 dist artifacts。`linux-docker-container` 固定 Docker 29.2.1 CLI/DinD，要求 privileged runner，先运行 daemon 和镜像预检，再用 `container_integration` marker 选择 10 项真实测试。

Docker job 生成 JUnit XML，并用 Python 标准库解析所有 testsuite，强制总数为 10、skipped 为 0；job 不设置 `allow_failure`。平台矩阵以明确状态记录 Linux Docker、Linux Podman、Windows 和 macOS Docker Desktop 补充证据，无完整证据不得升级为 verified。

## 关键取舍与风险

- 直接 YAML 比新增 Python orchestrator 或任务运行器更小、更透明，代价是本地需要按文档执行同一组命令。
- privileged DinD 是 GitLab Runner 外部前置条件；缺失时 job 应失败或不可调度，不能以 `allow_failure` 掩盖。
- 固定工具 patch 版本减少漂移，但版本升级必须重新验证。
- 本机 macOS + Linux Docker Desktop daemon 的 10/10 只作为补充证据，不替代原生 Linux runner。
- Podman rootless 语义和 Windows 路径/rlimit/locking 差异留给后续独立 change。

## 测试策略

- 新增 CI 合同测试，用 PyYAML 结构化读取 `.gitlab-ci.yml`，断言两个必需 jobs、固定版本、全部门禁命令、Docker preflight、JUnit 校验和无 `allow_failure`。
- 反射 `tests.test_container_backend`，断言 14 项测试中恰好 10 项带 `container_integration` marker。
- 文档合同断言平台状态、证据限制及 README/ACTION_PLAN/milestone 链接。
- 本地真实运行 marker 选择的 10 项 Docker 测试，并执行完整仓库门禁。

## Spec Patch

无。现有 delta spec 已明确要求 10 项测试、daemon/image 不可用失败、skip/fail 不得成功和平台证据升级规则。
