# 里程碑 M28: v0.1 Release Candidate

- 状态: 已完成（RC 冻结，非正式发布）
- 起止: 2026-07-29 ~ 2026-07-29
- 对应 ACTION_PLAN 行: M28（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_027](milestone_027.md)
- 技术设计: [2026-07-29-m28-v0-1-release-candidate-design](../docs/superpowers/specs/2026-07-29-m28-v0-1-release-candidate-design.md)
- 实施计划: [2026-07-29-m28-v0-1-release-candidate](../docs/superpowers/plans/2026-07-29-m28-v0-1-release-candidate.md)
- 验证报告: [2026-07-29-m28-v0-1-release-candidate-verify](../docs/superpowers/reports/2026-07-29-m28-v0-1-release-candidate-verify.md)

## 目标与范围

从唯一 `0.1.0` wheel 的 Python 3.11 干净安装出发，离线验证 CLI、真实 loopback HTTP、显式
Single/Duo/Triad，输出机器可读 RC JSON；把同一门禁接入 required Linux Docker job，并冻结安装、
能力、正式发布阻塞条件及平台、真实模型、sandbox、HTTP、协作 v1 五类已知限制。范围不含 PyPI、
tag/push、真实 provider 请求或新平台支持。

## 方案设计

- 使用仓库级标准库 harness，不扩大产品 CLI 或新增依赖。
- 父进程复制 wheel snapshot、清洗环境、创建 venv；子进程只运行安装后代码。
- CLI 使用 console script，HTTP 使用真实 loopback，协作使用真实 runtime + MockClient。
- JSON 只保存固定 schema、版本、Python、wheel digest 与六项状态，失败关闭且原子发布。
- Linux job 复用 M24 Docker topology，并将 RC JSON 与 JUnit 一起设为 required artifact。
- 裁决 M28-1（2026-07-29）：本地 Docker 与完整 pytest 缺口不冒充通过；允许冻结 RC，但正式发布
  继续被这些证据阻塞。

## 子任务清单

- [x] 实现并加固 clean-wheel/CLI/HTTP/Single/Duo/Triad harness
- [x] 将真实 wheel packaging 合同与 required Linux Docker CI 接入同一 harness
- [x] 冻结 RC 发布说明、平台矩阵和五类已知限制
- [x] 运行本机可执行的分层验证并保存实际失败/未验证项
- [ ] 当前 M28 required Linux job 实际通过 — 本机 daemon 不可用且尚无新 pipeline/job；正式发布前补证
- [ ] 完整 pytest 全绿 — 当前两个既有 MCP 墙钟预算测试稳定失败；稳定 runner 复验后处理

## 交付物清单

- [x] `scripts/m28_release_candidate_smoke.py` — 唯一 RC harness 与版本化 JSON
- [x] `tests/test_m28_release_candidate_smoke.py` — 环境、入口、失败关闭和脱敏合同
- [x] `.gitlab-ci.yml`、`tests/test_m28_release_ci.py` — required Linux wheel gate 与 artifact 合同
- [x] `tests/test_packaging.py` — 真实唯一 wheel 安装运行
- [x] `docs/releases/0.1.0-rc.md`、`tests/test_m28_release_docs.py` — RC 冻结与反夸大合同
- [x] `docs/superpowers/reports/2026-07-29-m28-v0-1-release-candidate-verify.md` — 实际验证证据

## 三次评审

### 技术方案评审

- [x] 达成单一 harness、安装后入口、JSON 证据与 CI 复用目标
- [x] 未新增产品子命令、依赖、配置面或运行时抽象
- [x] 未把 MockClient、本地 macOS 或历史 M24 证据外推为 provider/Linux M28 证明

### 代码评审

- [x] Task 1-3 已完成独立 task-level review，并修复 report 信任、环境清洗、wheel snapshot、CI fail-closed 和文档证据绑定问题
- [ ] 最终整分支 review 与两轮一致性复审 — 由后续 Comet verify gate 执行，未提前宣称通过

### 验收评审

- [x] focused RC 合同 `42 passed`；唯一 wheel Python 3.11.15 六项全通过
- [x] Ruff、Golden `20/20`、OpenSpec strict `22/22`、wheel/sdist build 通过
- [ ] 完整 pytest 全绿 — 实际为 `2 failed, 2401 passed, 10 skipped`，失败已隔离复现并记录
- [ ] M28 Linux Docker 运行证据 — daemon 不可连接，CI 仅 configured/pending

## 遗留问题

- [ ] M28 required Linux job 未运行 — 影响：候选不能表示为 release-ready — 计划：在现有 privileged Linux runner 运行并保存 pipeline/job ID、JUnit 与 RC JSON
- [ ] 两个 MCP 墙钟测试失败 — 影响：完整 pytest 门禁不绿 — 计划：稳定 runner 复验，若仍失败则以独立 change 修复实现或可移植性合同
- [ ] 正式发布未执行 — 影响：无 tag/PyPI 上传证据 — 计划：仅在上述门禁与最终审查通过后另行授权

## 续接指引

M28 已冻结为 `0.1.0` RC，不是正式发布。下一步先完成 Comet 最终整分支 review、两轮一致性复审、
delta spec 同步与 change 归档；随后在 required Linux runner 运行当前候选，保留 pipeline/job ID、十项
JUnit 与六项 `rc-smoke.json`。完整 pytest 的两个 MCP 墙钟失败必须在稳定 runner 复验并关闭，才可
开启 tag/PyPI 正式发布动作。用户原有未跟踪文件继续保留，不纳入提交。
