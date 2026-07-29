# 里程碑 M27: 协作路由校准

- 状态: 已完成并归档
- 起止: 2026-07-29 ~ 2026-07-29
- 对应 ACTION_PLAN 行: M27（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_026](milestone_026.md)
- 技术设计: [2026-07-29-m27-collaboration-routing-calibration-design](../docs/superpowers/specs/2026-07-29-m27-collaboration-routing-calibration-design.md)
- 实施计划: [2026-07-29-m27-collaboration-routing-calibration](../docs/superpowers/plans/2026-07-29-m27-collaboration-routing-calibration.md)
- OpenSpec change: [`2026-07-29-calibrate-collaboration-routing`](../openspec/changes/archive/2026-07-29-calibrate-collaboration-routing/)
- 验证报告: [2026-07-29-m27-collaboration-routing-calibration-verify](../docs/superpowers/reports/2026-07-29-m27-collaboration-routing-calibration-verify.md)
- 独立审查: [2026-07-29-m27-task4-independent-review](../docs/superpowers/reports/2026-07-29-m27-task4-independent-review.md)
- 最终整分支审查: [2026-07-29-m27-final-independent-review](../docs/superpowers/reports/2026-07-29-m27-final-independent-review.md)

## 目标与范围

把无显式模式、无宿主冻结检查证据的任务统一默认到 Single；继续直接尊重显式 Single、Duo、
Triad；只允许可信宿主在本次任务已绑定非空冻结检查时自动选择 Triad。使用 M25 冻结协议派生
误完成率、终止原因、质量、延迟和调用成本，并据此决定是否恢复某类自动 Triad。

同时修正 README 中 M18 Memory 的可写行为、当前测试基线和 Linux verified claim。范围不包括
修改 M18 Memory runtime、M26 check runner、M25 冻结输入、新配置面、新依赖或重新运行 M25。

## 方案设计

- 路由顺序固定为显式模式 → `has_bound_checks` → Single；不再解析任务文本中的编程特征。
- `goal`、`allow_weaker_override` 和 `override_required` 仅为兼容保留；新决策的
  `override_required` 始终为 false。
- `has_bound_checks` 是可信宿主内部事实，不能由 HTTP、普通 task options、服务器 YAML 或任务
  文本提供；candidate file requirements 不是 evidence。
- M25 派生脚本先验证冻结 summary，再计算两个误完成分母、原样 `runtime_reason`、model/mode 与
  family/mode 的质量和成本指标，并把输出写入独立派生目录。
- 裁决 M27-1（2026-07-29）：只有 Triad solved rate 严格高于 Single 的类别才进入恢复评估。
  baseline 持平，bugfix/feature/refactor 更低，因此不恢复任何自动 Triad 类别。
- Linux verified 只覆盖 Pipeline 50 / Job 249 已记录 runner topology，不推断架构。

## 子任务清单

- [x] 简化 resolver 并更新 CLI、REPL、HTTP、Loop 路由合同
- [x] 建立只读 M25 派生分析和不可变输入验证
- [x] 修正 Memory、Linux、路由和 HTTP 公开文档合同
- [x] 完成全量可执行验证、两轮最终自审、验证报告与里程碑记录
- [x] 完成 build-stage preparation/handoff：归档输入就绪，`milestones/latest` 当前指向 M27，分支收尾选择留给后续 gate
- [x] 完成最终路由审计一致性修复：生产 CLI 默认 JSONL audit、注入 sink 优先、`/single`、Loop default/explicit checkpoint 来源与 legacy 迁移
- [x] Comet delta spec 已合并主 specs，change 已归档，分支已合并到 `main`

## 交付物清单

- [x] `src/forgeagent/collaboration.py` — 默认 Single、显式模式优先、`bound_checks` 路由
- [x] `src/forgeagent/cli.py` — CLI/REPL 移除编程文本自动 Triad 与弱模式确认
- [x] `src/forgeagent/http_config.py`、`src/forgeagent/http_task_service.py` — 拒绝客户端伪造宿主证据
- [x] `scripts/m27_m25_routing_analysis.py` — M25 冻结证据派生与显式事务发布/恢复证据
- [x] `docs/evaluation/m25/derived/m27-collaboration-routing/` — 机器投影和人类报告
- [x] `README.md`、`docs/http-task-service.md`、`docs/threat-model.md`、`docs/platform-support.md` — 公开合同
- [x] `tests/test_collaboration_routing.py`、入口/HTTP/文档与派生分析测试 — 可执行回归合同
- [x] `src/forgeagent/loop.py` 与 Loop/入口测试 — default/explicit 来源持久化、恢复和旧 checkpoint 兼容合同
- [x] `docs/superpowers/reports/2026-07-29-m27-collaboration-routing-calibration-verify.md` — 完整验证证据

## 三次评审

### 技术方案评审

- [x] 达成默认 Single、显式模式优先、宿主证据 Triad 的既定设计目标
- [x] 未增加意图分类器、依赖、配置面或第二套 check registry
- [x] M25 派生与 M26 完成证据边界保持分离，未把历史结果冒充当前 Triad 证明

### 代码评审

- [x] Task 1-3 均完成 thorough review 和修复轮
- [x] 修复派生裁决一致性、配对发布回滚、公开宿主边界与 HTTP/YAML 拒绝语义
- [x] Task 4 独立 review 的 2 项 Important 与 1 项 Minor 收尾问题已修复：ACTION_PLAN 权威状态与完整验证证据、OpenSpec 4.3/4.4 生命周期边界、Task 4 实际提交记录
- [x] Task 4 复审发现的状态机死锁与审查证据缺口已修复，证据见独立审查工件；未虚构 reviewer agent ID 或重测结果
- [x] Task 5 最终评审修复 CLI/REPL Single 审计缺口，以及 M25 派生输出 backup/restore 不确定状态的破坏风险
- [x] Task 6 复核修复默认 CLI audit 目的地、实际 audit sink 复用、`/single` 帮助/补全和 Loop create/resume 来源冻结；legacy Duo/Triad 迁移为 explicit
- [x] 修复后独立复审均为 Approved；强制终止、文件系统损坏和外部并发改写不被误写为跨文件原子保证
- [x] 两轮最终自审未发现剩余 Critical 或 Important 产品问题；归档状态与 Git 实际一致

### 验收评审

- [x] 路由、派生分析和文档专项验证通过，证据见验证报告
- [x] 当前沙箱可执行基线 `2336 passed, 22 skipped`；完整尝试 `12 failed, 2339 passed, 22 skipped`，环境失败原样记录
- [x] Ruff check/format、OpenSpec `21/21`、Golden `20/20`、离线 wheel/sdist build 和 diff check 通过
- [x] Task 6 受影响回归 `532 passed, 10 skipped`，定向 Ruff 与 diff check 通过
- [x] M25 冻结 protocol 与正式 run tree 无 diff；自动 Triad 恢复列表为空

## 遗留问题

- [ ] M16 loopback 黑盒未在当前沙箱重跑 — 影响：本轮不能为这 11 项生成新通过证据 — 计划：保留历史/CI 证据，在允许 loopback 的 runner 复验
- [ ] packaging 全依赖 wheel 安装受离线解析限制 — 影响：本轮只证明构建和内容阶段 — 计划：由联网离线门禁或已有 CI 缓存补证

## 续接指引

M27 已验证、合并到 `main` 并归档为
`openspec/changes/archive/2026-07-29-calibrate-collaboration-routing`。后续不要修改 M25 冻结输入，
也不要恢复任何自动 Triad 类别；未来策略变化必须基于新的冻结协议和版本化 change。用户原有未
跟踪文件继续保留且不纳入提交。
