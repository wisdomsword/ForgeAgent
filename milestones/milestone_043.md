# 里程碑 M43: Rewrite/依赖基线测量

- 状态: 已完成并归档
- 起止: 2026-07-31 ~ 2026-07-31
- 对应 ACTION_PLAN 行: M43（见该文件 §四里程碑表）
- 前置里程碑: [milestone_042](milestone_042.md)
- 分发边界: 不执行 PyPI、tag 或发布自动化；普通开发分支 push 仅按明确授权作为版本控制交接

## 目标与范围

只测量 Python 执行路径的性能、可靠性、维护成本、兼容性、团队能力和迁移/回滚风险，固定每项
baseline、threshold、evidence、migration 与 rollback trigger。M43 不实现 Rust backend、不新增依赖、
不修改运行时、协议、配置或数据；只有真实指标持续越阈且可行性门全部 ready 时，未来才可另立
可回滚的单模块试验。

## 方案设计

- 单一标准库脚本调用现有 `TrustedBackend`、`RestrictedBackend` 和条件可用的 `ContainerBackend`。
- 绝对计时只作为同机证据，不作为跨平台 SLA 或抖动 CI 门禁；越阈还需同机干净复测和真实需求。
- restricted crash/timeout 各写一次临时哨兵，宿主验证精确一个字节并执行新 block，证明恢复且未重放。
- backend 使用 `measured/not_available/failed`；metric status 使用固定词表，未知值 fail closed。
- JSON 不含绝对路径、环境值、代码正文、raw exception、stdout/stderr 或主机名。
- 技术设计与基线见
  `docs/superpowers/specs/2026-07-31-executor-rewrite-baseline-design.md` 和
  `docs/evaluation/m43/rewrite-dependency-baseline.md`。

## 子任务清单

- [x] 建立六项 versioned evidence 与三态 verdict 契约。
- [x] 实现 trusted/restricted 真实测量、container 离线可用性检查和维护/兼容采集。
- [x] 完成两次同提交测量并得到 `keep_python`。
- [x] 完成两轮自审并修复状态词表、no-replay、profiling 和流程循环问题。
- [x] 完成零排除全量验证与归档前 OpenSpec strict。
- [x] 完成 Comet verify、主规格同步和 change 归档。

## 交付物清单

- [x] `scripts/m43_executor_rewrite_baseline.py`：标准库离线测量与纯 verdict。
- [x] `tests/test_m43_executor_rewrite_baseline.py`：schema、判定、脱敏、原子写和真实故障证据。
- [x] `docs/evaluation/m43/executor-rewrite-baseline.json`：绑定 `178b068a` 的冻结原始证据。
- [x] `docs/evaluation/m43/rewrite-dependency-baseline.md`：六项治理表、复现和未来门禁。
- [x] `docs/superpowers/reports/2026-07-31-executor-rewrite-baseline-verify.md`：全量验证报告。
- [x] `openspec/changes/archive/2026-07-31-measure-executor-rewrite-baseline/`：归档 change 与完整 Comet 状态。

## 三次评审

### 技术方案评审

- [x] 六项指标均具备 baseline、threshold、evidence、migration 和 rollback trigger。
- [x] 当前证据没有 confirmed bottleneck；最终 verdict 为 `keep_python`，不授权重写或新依赖。
- [x] container 与团队能力缺口如实保持 `not_available/not_ready`，没有被降格为通过。

### 代码评审

- [x] 两轮 fresh diff 自审已完成，发现项均经 RED/GREEN 修复。
- [x] M43 提交区间没有 `src/`、依赖、配置、schema 或数据变化。
- [x] 当前会话规则禁止子代理；未伪造独立 reviewer，限制已记录在验证报告。

### 验收评审

- [x] 聚焦 `68 passed, 10 skipped`；零排除全量 `2653 passed, 10 skipped`。
- [x] 全库 Ruff/141 文件 format、diff check、OpenSpec strict `33/33` 与敏感公开面扫描通过。
- [x] Comet full verify 通过，archive `7/7 steps succeeded`。

## 遗留问题

M43 无未完成任务。本机 container evidence 为 `not_available`，团队维护演练为 `not_ready`；这是
未来重写试验的准入阻断条件，不是 M43 的遗漏，也不阻止“保持 Python”的已验收结论。

## 续接指引

M43 已完成全量门禁、主规格同步和 Comet 归档。后续继续使用 Python；不得从工具已安装或单次
微基准推断可以启动 Rust 重写。只有真实使用瓶颈持续越阈且六项门禁具备完整 evidence，才可另立
保留 Python fallback 的单模块 full change。HTTP 远程动作审批绑定仍是条件候选。PyPI、tag 和发布
自动化继续移除；普通开发分支 push 仅按本次明确授权执行。
