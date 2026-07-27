## 1. 持续验证合同

- [x] 1.1 为 GitLab 基础门、Docker job、10 项专用 marker 和平台矩阵编写离线失败合同
- [x] 1.2 为 10 项真实 Docker 测试注册并应用 `container_integration` marker，保持 4 项无 Docker 单测始终执行

## 2. GitLab CI 门禁

- [x] 2.1 新增必需的 `offline-verification` job，固定工具版本并执行 Ruff、完整离线 pytest、Golden、OpenSpec strict、build 和发布内容边界
- [x] 2.2 新增必需的 `linux-docker-container` job，固定 Docker CLI/DinD、强制 daemon/镜像预检并执行 10 项 container 测试

## 3. 平台矩阵与公开文档

- [x] 3.1 新增证据驱动的平台矩阵，明确 Linux Docker、Linux Podman、Windows 和 macOS Docker 的状态、优先级、限制与后续触发点
- [x] 3.2 更新 README、ACTION_PLAN 和 milestone_024，保持历史验证数字不变并链接 CI/平台证据

## 4. 真实验证与收尾

- [x] 4.1 在本机 Docker daemon + `python:3.11-slim` 环境运行 10 项 container 测试并记录 host/daemon 架构和结果
- [x] 4.2 执行 Ruff、完整离线 pytest、Golden 20/20、OpenSpec strict、wheel/sdist 与内容边界，并完成两轮自审；Comet verify 作为 change 阶段门禁随后执行
