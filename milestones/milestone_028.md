# 里程碑 M28: v0.1 Release Candidate

- 状态: 已完成并归档（RC 工程冻结，非正式发布）
- 起止: 2026-07-29 ~ 2026-07-29
- 对应 ACTION_PLAN 行: M28（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_027](milestone_027.md)
- 技术设计: [2026-07-29-m28-v0-1-release-candidate-design](../docs/superpowers/specs/2026-07-29-m28-v0-1-release-candidate-design.md)
- 实施计划: [2026-07-29-m28-v0-1-release-candidate](../docs/superpowers/plans/2026-07-29-m28-v0-1-release-candidate.md)
- OpenSpec change: [2026-07-29-m28-v0-1-release-candidate](../openspec/changes/archive/2026-07-29-m28-v0-1-release-candidate/)
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
- 裁决 M28-1（2026-07-29）：本地 Docker 与首次完整 pytest 缺口不冒充通过；允许冻结 RC。随后
  `af543ec` 仅修正依赖宿主调度的测试合同，生产 MCP 代码不变，完整 pytest 门禁已关闭；M28 已按
  “定义并接入 required job” 的工程范围归档。归档后 Pipeline 55 发现 offline job 未路由到唯一
  项目 runner，`73af78e` 修正标签；Pipeline 56 进一步暴露 root、缺少 `curl`/`jq` 和测试启动竞态，
  `fa3ae5c` 以非 root CI 与 tests-only 同步修正关闭。Pipeline 57 两项 required job 均通过，正式
  发布只剩另行授权的 tag/上传动作。

## 关键提交

- Task 1：`1fca7ee`（installed-wheel smoke）、`f92e330`、`07ef59d`、`5c3e96c`（隔离与报告合同加固）。
- Task 2：`55e0ed5`（Linux gate）、`71ae94e`、`d3b7837`（CI fail-closed 与证据合同加固）。
- Task 3：`bc82c95`（RC 文档）、`6a39117`、`e2ed024`（公开证据边界加固）。
- Task 4：`e35332b`（分层验证、验证报告与里程碑草案）；后续 review fix 保持 M28 lifecycle gate 开放。
- 完整 pytest：`af543ec`（tests-only MCP 调度可移植性合同修正；生产代码不变）。
- Linux CI 收口：`73af78e`（offline runner 路由）、`fa3ae5c`（非 root/依赖与 tests-only 稳定性）。

## 子任务清单

- [x] 实现并加固 clean-wheel/CLI/HTTP/Single/Duo/Triad harness
- [x] 将真实 wheel packaging 合同与 required Linux Docker CI 接入同一 harness
- [x] 冻结 RC 发布说明、平台矩阵和五类已知限制
- [x] 运行本机可执行的分层验证并保存实际失败/未验证项
- [x] required Linux job 配置、失败关闭与 runner 实跑完成 — Pipeline 57 / Job 263 十项零 skip及六项 RC smoke 全绿
- [x] 完整 pytest 门禁关闭 — 保留首次 `2 failed, 2401 passed, 10 skipped` 历史；`af543ec` 修正 tests-only 合同后为 `2403 passed, 10 skipped`，全部新增回归后的最终基线为 `2409 passed, 10 skipped`

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
- [x] 最终整分支 review 与两轮一致性复审 — hostile proxy Important 已用 RED/GREEN 修复并由原审查者确认；无未解决 Critical/Important

### 验收评审

- [x] focused RC 合同 `47 passed`；唯一 wheel Python 3.11.15 六项全通过
- [x] Ruff、Golden `20/20`、OpenSpec strict `22/22`、wheel/sdist build 通过
- [x] 完整 pytest 全绿 — 首次 `2 failed, 2401 passed, 10 skipped`；全部修正与新增回归后最终为 `2409 passed, 10 skipped`
- [x] M28 Linux Docker CI 合同 — Pipeline 57 / Job 263 通过 daemon/image preflight、十项零 skip、唯一 wheel、六项 JSON，并发布 JUnit/JSON；offline Job 262 同时通过

## 遗留问题

- [ ] 正式发布未执行 — 影响：无 tag/PyPI 上传证据 — 计划：仅在最终候选 required pipeline 与审查通过后另行授权

## 续接指引

M28 已完成 Comet verify/archive，delta spec 已同步到主 specs，`milestones/latest` 已切换到 M28；
这是 RC 工程冻结，不是正式发布。Pipeline 57 已保留 offline Job 262、Linux Job 263、十项 JUnit
与六项 `rc-smoke.json` 证据；后续候选提交仍须通过自身 required pipeline。下一步仅在另行授权后
执行 tag/PyPI 正式发布动作。用户原有未跟踪文件继续保留，不纳入提交。
