# Brainstorm Summary

- Change: m28-v0-1-release-candidate
- Date: 2026-07-29

## 确认的技术方案

采用单一仓库级 `scripts/m28-release-candidate-smoke.py`，不新增产品 CLI 子命令。父模式验证 wheel 元数据和摘要，创建 Python 3.11 临时 venv，仅安装该 wheel 后用 `-I` 启动子模式；子模式证明 `forgeagent` 模块与 console script 均来自 venv，然后执行 CLI、真实 loopback HTTP、Single、Duo、Triad 六类检查并原子写出版本化 JSON。

CLI 直接执行 venv console script 的 `--help` 和 `models`。HTTP 使用真实 server、bearer 请求和可取消本地任务替身。Single 使用真实 `Task`，Duo/Triad 使用真实 `CollaborationRunner`、store 和结构化 Submit registry；仅模型回复由确定性 `MockClient` 提供，Triad 计划由 harness 固定批准。

Linux GitLab job 保留现有 DinD、非 root 和十项 container JUnit 精确门禁，新增 Python 3.11 clean-wheel RC smoke 与 JSON artifact 校验。发布口径集中在 `docs/releases/0.1.0-rc.md`，README 和平台矩阵只引用并陈述实际证据。

## 关键取舍与风险

- 不采用产品 `rc-smoke` 子命令：发布工程不应扩大 public CLI。
- 不拆成多脚本：会重复 venv、环境清洗和报告逻辑。
- MockClient 只证明安装后装配，不证明 provider 连通性；发布说明必须保留该边界。
- loopback 或安装依赖解析受环境限制时如实失败，不允许 skip 或借源码树绕过。
- JSON 只保存稳定状态、版本、Python 版本和 wheel SHA-256，不保存路径、环境值、目标或模型文本。

两轮自审均推荐上述方案。第一轮检查目标/非目标、最小实现和证据真实性；第二轮检查前后一致、错误分支、安全披露和 CI 可复现性，未发现需要扩大范围的设计缺口。

## 测试策略

先为参数/环境清洗、wheel 元数据、报告原子写入和失败脱敏编写单元测试；再用真实本地 loopback 和确定性 MockClient 覆盖 CLI/HTTP/Single/Duo/Triad 子检查；最后由 packaging 测试构建真实 wheel并调用同一 harness。验证层依次为专项 pytest、Ruff、完整 pytest、Golden 20/20、OpenSpec strict、build、本机 Docker 十项和 Python 3.11 Linux 容器内 RC smoke。

## Spec Patch

无。现有 delta spec 已包含成功、失败、零 skip、敏感信息边界和文档冻结场景。
