# 里程碑 M25: 编程模式质量—成本证据

- 状态: 实现与真实证据完成，待 Comet verify/归档
- 起止: 2026-07-27 ~ 2026-07-28
- 对应 ACTION_PLAN 行: M25（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_024](milestone_024.md)
- 技术设计: [2026-07-27-m25-programming-mode-evaluation-design](../docs/superpowers/specs/2026-07-27-m25-programming-mode-evaluation-design.md)
- 实施计划: [2026-07-27-m25-programming-mode-evaluation](../docs/superpowers/plans/2026-07-27-m25-programming-mode-evaluation.md)
- OpenSpec change: [`m25-programming-mode-evaluation`](../openspec/changes/m25-programming-mode-evaluation/)

## 目标与范围

在不修改 M23 历史证据和产品运行时的前提下，新建独立 M25 评估协议：3 个 M23 基线任务加
6 个真实编程 fixture，`claude-haiku-4-5` 与 `gpt-5.4-mini` 两条模型路由，Single/Duo/Triad
三种模式，每组合重复 5 次，共 270 次真实串行评估。协议见
[`docs/evaluation/m25/protocol.json`](../docs/evaluation/m25/protocol.json)，报告见
[`docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/report.md`](../docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/report.md)，独立复算脚本见
[`scripts/m25_independent_recompute.py`](../scripts/m25_independent_recompute.py)。

## 方案设计

- M23 v2 类型和 62 个 tracked 历史文件保持字节不变；M25 使用独立 v1 schema 和证据根。
- 固定 9 x 2 x 3 x 5 排程、全局模式位置平衡、终态续跑和 route hash 绑定。
- raw/environment/summary 只保存安全投影，不保存 prompt、回复、credential、base URL 或绝对路径。
- 汇总按模型、模式、任务族和任务保留完成率、首次通过率、rejection/correction、tokens、调用、
  provider 尝试、延迟和 usage 缺失率；Single 的协作字段保持 N/A。
- 报告不自动排名模式或模型，不形成产品推荐。

## 子任务清单

- [x] M23 历史证据字节锁定与 M25 独立 schema
- [x] 双模型固定排程、身份绑定与安全续跑
- [x] 两个 bugfix、两个 feature、两个 refactor 自包含 fixture
- [x] 固定 M25 协议与 fixture 强度验证
- [x] 分层质量—成本聚合与中立报告
- [x] 独立标准库复算器与篡改检测
- [x] 离线门禁和实现冻结
- [x] 双 route preflight 与 route 配置纠错
- [x] 270 次真实模型评估及完整 evidence commit
- [x] 公共文档、里程碑与 Comet 验证准备

## 交付物清单

- [x] [`scripts/m23_mode_evaluation.py`](../scripts/m23_mode_evaluation.py) — 保留 M23 并新增 M25 分派
- [x] [`scripts/m25_independent_recompute.py`](../scripts/m25_independent_recompute.py) — 独立复算
- [x] [`tests/test_m25_mode_evaluation.py`](../tests/test_m25_mode_evaluation.py) — 协议、fixture、聚合、安全和文档合同
- [x] [`tests/test_m25_independent_recompute.py`](../tests/test_m25_independent_recompute.py) — 独立复算篡改检测
- [x] [`docs/evaluation/m25/protocol.json`](../docs/evaluation/m25/protocol.json) — 固定协议
- [x] [`docs/evaluation/m25/README.md`](../docs/evaluation/m25/README.md) — 命令、证据边界和限制
- [x] [`summary.json`](../docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/summary.json) — 270/270 机器汇总
- [x] [`report.md`](../docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/report.md) — 中立报告

## 三次评审

### 技术方案评审

- [x] 9 个任务、2 个模型、3 个模式、5 次重复的 270-run 合同全部实现。
- [x] 真实运行发现多文件候选路径与协作合同不兼容后，以失败优先测试将 fixture 收敛为顶层文件，
  未扩张产品 collaboration 合同；修复后 30 条任务族回归无配置错误。
- [x] 未增加依赖、产品配置面或运行时抽象；M23 历史证据保持隔离。

### 代码评审

- [x] build 阶段已完成逐任务本地 review；最终标准 review 在 Comet verify 记录。
- [x] 两轮证据自审已修正状态口径与验证脚本假设，未发现需要改写 raw 的数据问题。
- [x] 未发现未处理的 Critical/Important 正确性、安全或边界问题。

### 验收评审

- [x] 270/270 唯一 terminal raw；两个模型各 135，三种模式各 90，五次重复全平衡。
- [x] 116/270 solved、154/270 failed；2413 次逻辑调用与 2413 次 provider 尝试；usage 缺失
  1/2413。分模型、模式、任务族及任务口径见中立报告，不合成为无标签综合分数。
- [x] 两条安全 route hash 为
  `e0a593403fc01adc57d97f860709bf09ef6979eab0f5bcdd0414842523c0e221` 和
  `d39d7e0c5d4b76a24da1be3244b97ab925f95e1b2096bc72ec8a2da43a968430`；未保存 URL 或 credential。
- [x] `uv run python scripts/m25_independent_recompute.py --protocol docs/evaluation/m25/protocol.json --output docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini` 输出
  `INDEPENDENT_RECOMPUTE_OK runs=270`。
- [x] M23/M25 专项 `121 passed`；沙箱可执行离线回归 `2350 passed, 22 skipped`；packaging
  `3 passed`；Golden `20/20`；Ruff check/format、离线 wheel/sdist build、OpenSpec strict
  `21 passed, 0 failed`、M23 byte lock 和 `git diff --check` 通过。
- [x] 未把受限环境全量运行误报为通过：原命令为 `2353 passed, 22 skipped, 12 failed`；其中
  11 项均因沙箱禁止 loopback socket，1 项因沙箱 DNS 阻断 Hatchling。沙箱外重跑请求又因
  自动审批服务 403 无法执行；已用上述聚焦、排除环境限制的全套回归及离线 packaging 补证。

## 遗留问题

- [ ] 样本外推广 — 影响：九个固定任务、五次重复和记录日期的本机结果不能代表其他任务、平台或
  provider 版本 — 计划：新增模型或任务时建立新的版本化 change 和证据根，不修改 M25。
- [ ] provider 权重不可固定 — 影响：同名模型未来可能漂移 — 计划：报告持续保留日期与 route hash，
  不把本次结果表述为稳定排名。

## 续接指引

M25 的实现与 270-run 真实证据已完成，下一步由 Comet verify 运行完整门禁、写验证报告并处理
分支；归档成功后把本文件和 ACTION_PLAN 状态更新为“已完成并归档”。任何新增任务、模型、
provider 路由或重复次数都必须新建版本化评估 change，不能修改 M25 或 M23 历史 evidence。
