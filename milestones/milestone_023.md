# 里程碑 M23: Single/Duo/Triad 质量—成本评估

- 状态: 进行中（v2 harness 已修复，等待重新执行正式评估）
- 起止: 2026-07-27 ~ 2026-07-27
- 对应 ACTION_PLAN 行: M23（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_022](milestone_022.md)
- 技术设计: [2026-07-27-m23-collaboration-mode-evaluation-design](../docs/superpowers/specs/2026-07-27-m23-collaboration-mode-evaluation-design.md)
- 实施计划: [2026-07-27-m23-collaboration-mode-evaluation](../docs/superpowers/plans/2026-07-27-m23-collaboration-mode-evaluation.md)
- 固定协议: [`docs/evaluation/m23/protocol.json`](../docs/evaluation/m23/protocol.json)
- 无效批次审计: [`INVALID.md`](../docs/evaluation/m23/runs/2026-07-27-haiku-4-5-invalid-8dbebff/INVALID.md)

## 目标与范围

在不修改 ForgeAgent 协作运行时的前提下，对相同任务的 Single、Duo、Triad 进行独立、可复算的
质量—成本评估。固定任务、模型 ID、生成参数、restricted 环境、重复次数、轮换顺序和外部
产物检查；记录任务完成率、首次验收通过率、rejection/correction 次数、四类 token、逻辑模型
调用、provider attempts、端到端延迟和 usage 缺失率。

本里程碑不包含 credential 多来源功能，不修改产品 CLI、模型注册、协作状态或角色行为。真实
请求是显式授权的 opt-in 评估，不成为离线 CI 门禁。Single 没有协作验收循环，对应指标保持
`N/A`。报告只给描述性证据，不自动宣称 Triad 优于 Single，也不据此作产品决策。

## 方案设计

- v2 版本化 JSON 协议固定 3 个任务、每种模式 3 次重复，并使用三种轮换次序平衡运行顺序。
- 每次 run 使用全新临时工作区；任务完成定义为 runtime completed 且全部外部检查通过。
- 候选 CLI 在 restricted check worker 同一进程内执行；每个任务另做 immutable fixture 字节检查。
- 复用公开 `Task` 和 `CollaborationRunner`，每个协作角色使用 fresh client/Task 并完整关闭；
  harness 不向 Evaluator 注入额外检查，不改变产品运行时。
- audit 只投影调用、attempt 和 usage；raw 不保存 goal、prompt、reply、credential、输出正文或
  绝对路径，检查输出只保存 UTF-8 字节数和 SHA-256。
- 27 份 raw 是汇总的唯一输入；聚合器拒绝缺失、重复、协议/环境混杂或 run identity 不一致，
  不提供不完整聚合开关。

## 子任务清单

- [x] 固定协议、严格 schema、路径边界和 27 次平衡排程
- [x] 实现隔离工作区、公开运行 API 组装、audit 投影、外部检查与原子 raw
- [x] 实现严格完整性校验、按调用加权 usage 和中立 summary/report
- [ ] 使用 v2 协议执行 27 次真实模型评估并独立复算
- [ ] 完成 v2 公平性/统计口径与安全性/可复现性两轮证据自审
- [ ] 完成最终仓库门禁、Comet verify 与归档 — 本文件收尾后执行

## 交付物清单

- [x] `scripts/m23_mode_evaluation.py` — 独立 run/aggregate harness
- [x] `tests/test_m23_mode_evaluation.py` — 53 项协议、运行、聚合、CLI、安全和文档合同
- [x] `docs/evaluation/m23/protocol.json` — 唯一固定评估协议
- [ ] v2 `environment.json`、27 份 raw、`summary.json` 和中立 `report.md`
- [x] `2026-07-27-haiku-4-5-invalid-8dbebff/` — v1 无效批次与失效说明，仅供审计
- [x] `openspec/changes/m23-collaboration-mode-evaluation/` — proposal/design/spec/tasks

## 三次评审

### 技术方案评审

- [x] 7 项 OpenSpec requirement 均有 v2 实现和离线合同；真实 v2 证据待运行
- [x] 固定协议、相同检查、3×3×3 重复与轮换顺序未在执行中修改
- [x] 不包含 credential 功能，受保护 runtime/CLI/model registry/dependency 文件与基线一致

### 代码评审

- [x] code-reviewer 发现 environment↔protocol 未交叉绑定和 raw `run_id` 未绑定文件名；均先加
  RED 回归后修复
- [x] 第一次真实证据自审发现 collaboration ID 不满足公开 API 的 32 位十六进制合同；新增
  RED 回归并改为 canonical hash ID，未修改协作运行时
- [x] 最终 reviewer 发现 restricted worker 嵌套进程、fixture 完整性缺口和输出根逃逸；均先加
  RED 回归，再升级 v2 协议并修复
- [x] 修复后 M23 离线合同 `53 passed`

### 验收评审

- [x] v1 批次经 reviewer 判定无效并移出正式目录：CSV/events 检查必然触发 process-spawn denial，
  且 fixture 不变性无法事后证明；旧完成率不得引用
- [ ] v2 27/27 terminal raw、完整性/安全性复算和最终模式指标
- [ ] 全量 pytest、golden、build、OpenSpec strict、Comet verify 与归档 — v2 证据完成后重跑

## 遗留问题

- [ ] 样本仅 3 个文件/代码任务、每组合 3 次 — 影响：任务效应明显，统计功效有限 — 计划：
  后续评估扩大任务族和重复数，但不回写本次固定协议
- [ ] 仅覆盖 `claude-haiku-4-5`、一个 provider 路由和本机环境 — 影响：不能外推到其他模型或平台
  — 计划：M24 候选补平台矩阵；模型扩展必须建立独立协议
- [ ] provider 侧权重版本无法由本地独立固定 — 影响：同一 model ID 的长期复测可能受服务端变化影响
  — 计划：保留时间、commit、路由 hash 和原始记录，报告中持续声明限制
- [x] 本次 usage 缺失率为 0/304 — 该结果只描述本次 provider 响应，不承诺后续调用始终提供 usage

## 续接指引

M23 v2 harness 修复已完成，但尚无有效正式证据。下一步需要重新授权并执行完整 27 次 v2 评估，
随后复算、完成仓库门禁、Comet verify、归档并合并 main。M24 候选是持续验证 CI 与
container/platform 矩阵。credential 多来源功能保持独立，
不得塞回 M23；任何新质量对照都必须新建固定协议，不修改或混入本次 27 份证据。
