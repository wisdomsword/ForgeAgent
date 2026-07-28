# M27 Task 4 Report: 全量验证、基线定稿与里程碑收尾

## 状态

`DONE_WITH_ENVIRONMENT_EXCEPTIONS`

M27 产品实现、规格、派生证据与验证收尾均完成。OpenSpec change 保持 active，等待协调器进入
Comet archive；本轮修复 Task 4 独立 review 的 2 项 Important 与 1 项 Minor，没有提前归档。

## 当前基线

- 当前沙箱可执行 pytest：`2309 passed, 22 skipped`。
- 未排除完整尝试：`12 failed, 2312 passed, 22 skipped`；11 项 loopback 权限失败，1 项隔离构建
  DNS/依赖解析失败。
- Ruff：check 通过；`115 files already formatted`。
- OpenSpec strict：`21 passed, 0 failed`。
- Golden：`20/20 passed`。
- 构建：复用 M26 已下载官方缓存，`UV_OFFLINE=1 uv build --offline` 生成 wheel 与 sdist。
- packaging 单测：`2 passed, 1 failed`；失败停在新 venv 全依赖安装，内容断言已通过。

## 文件

- `ACTION_PLAN.md`
- `openspec/changes/calibrate-collaboration-routing/tasks.md`
- `docs/superpowers/reports/2026-07-29-m27-collaboration-routing-calibration-verify.md`
- `milestones/milestone_027.md`
- `.superpowers/sdd/task-4-report.md`

## 两轮自审

第一轮逐项映射三份 delta/new specs，确认自动恢复列表为空、candidate files 不构成 evidence、M25
冻结 tree 无 diff、Memory 与 Linux claim 精确。

第二轮搜索旧路由和过期文案。剩余 `needs_confirmation` 是 Planner 合法状态；
`override_required` 是兼容投影；架构/只读旧文字仅在历史设计或负向测试中。显式模式、
`bound_checks` audit、HTTP 拒绝和 Loop checkpoint 均有可执行覆盖。

## 独立 Review Findings 与修复

- Important：`ACTION_PLAN.md` 仍将 M27 标为进行中，且权威状态未记录实际沙箱基线、完整 12 项
  环境失败、OpenSpec `21/21`、Golden `20/20` 与离线 build。已改为“已完成，待 Comet 归档”并
  补齐证据。
- Important：OpenSpec 4.3/4.4 提前混合了 review 修复、验证收尾与后续 Comet archive/branch
  gate。4.3 在本轮 review fix 后完成；4.4 改为“准备 M27 归档、更新 milestones/latest 与分支
  收尾”并保持未勾选。
- Minor：本报告原先把已经存在的 Task 4 提交写成“待执行”。现按 Git 实际状态记录，并明确
  active change 尚未归档。

## 风险信号

- 非沙箱审批基础设施返回 403，无法在本轮补跑 loopback 与联网依赖安装。
- M25 早于 M26，不可用来证明当前 evidence-bound Triad 的绝对质量。
- 用户原有未跟踪文件和协调器进度文件未纳入 Task 4 范围。

## 提交

- Task 4 原提交：`09ceb10 chore: complete m27 collaboration routing calibration`。
- Review fix：`fix: align m27 closeout state`（本提交）。
