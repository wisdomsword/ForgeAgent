# 里程碑 M27: 协作路由校准

- 状态: 已完成，待 Comet 归档
- 起止: 2026-07-29 ~ 2026-07-29
- 对应 ACTION_PLAN 行: M27（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_026](milestone_026.md)
- 技术设计: [2026-07-29-m27-collaboration-routing-calibration-design](../docs/superpowers/specs/2026-07-29-m27-collaboration-routing-calibration-design.md)
- 实施计划: [2026-07-29-m27-collaboration-routing-calibration](../docs/superpowers/plans/2026-07-29-m27-collaboration-routing-calibration.md)
- OpenSpec change: [`calibrate-collaboration-routing`](../openspec/changes/calibrate-collaboration-routing/)
- 验证报告: [2026-07-29-m27-collaboration-routing-calibration-verify](../docs/superpowers/reports/2026-07-29-m27-collaboration-routing-calibration-verify.md)
- 独立审查: [2026-07-29-m27-task4-independent-review](../docs/superpowers/reports/2026-07-29-m27-task4-independent-review.md)

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
- [ ] Comet delta spec 归档和分支收尾 — 后续 archive 阶段执行，不在 active change 内提前完成

## 交付物清单

- [x] `src/forgeagent/collaboration.py` — 默认 Single、显式模式优先、`bound_checks` 路由
- [x] `src/forgeagent/cli.py` — CLI/REPL 移除编程文本自动 Triad 与弱模式确认
- [x] `src/forgeagent/http_config.py`、`src/forgeagent/http_task_service.py` — 拒绝客户端伪造宿主证据
- [x] `scripts/m27_m25_routing_analysis.py` — M25 冻结证据派生与原子配对发布
- [x] `docs/evaluation/m25/derived/m27-collaboration-routing/` — 机器投影和人类报告
- [x] `README.md`、`docs/http-task-service.md`、`docs/threat-model.md`、`docs/platform-support.md` — 公开合同
- [x] `tests/test_collaboration_routing.py`、入口/HTTP/文档与派生分析测试 — 可执行回归合同
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
- [x] 两轮最终自审未发现剩余 Critical 或 Important 产品问题；active change 未被误写为已归档

### 验收评审

- [x] 路由、派生分析和文档专项验证通过，证据见验证报告
- [x] 当前沙箱可执行基线 `2309 passed, 22 skipped`；完整尝试的 12 项环境失败原样记录
- [x] Ruff check/format、OpenSpec `21/21`、Golden `20/20`、离线 wheel/sdist build 和 diff check 通过
- [x] M25 冻结 protocol 与正式 run tree 无 diff；自动 Triad 恢复列表为空

## 遗留问题

- [ ] M16 loopback 黑盒未在当前沙箱重跑 — 影响：本轮不能为这 11 项生成新通过证据 — 计划：保留历史/CI 证据，在允许 loopback 的 runner 复验
- [ ] packaging 全依赖 wheel 安装受离线解析限制 — 影响：本轮只证明构建和内容阶段 — 计划：由联网离线门禁或已有 CI 缓存补证
- [ ] active OpenSpec change 尚未归档 — 影响：主 specs 尚未同步本次 delta — 计划：立即进入 Comet archive 阶段

## 续接指引

M27 build-stage 实现、验证与 preparation/handoff 已经完成。下一步按 Comet archive 门处理
`openspec/changes/calibrate-collaboration-routing`：同步 delta specs、归档 change、把里程碑状态改为
“已完成并归档”，再进入 branch gate 由用户选择并执行分支收尾；本轮没有预选或执行合并/push。
不要修改 M25 冻结输入，也不要恢复任何自动
Triad 类别；未来策略变化必须基于新的冻结协议和版本化 change。用户原有未跟踪文件继续保留且不
纳入提交。
