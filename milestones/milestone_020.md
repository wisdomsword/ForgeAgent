# 里程碑 M20: Eval 体系与独立 Evaluator

- 状态: 已完成并归档
- 起止: 2026-07-24 ~ 2026-07-24
- 对应 ACTION_PLAN 行: M20（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_019](milestone_019.md)
- 技术设计: [2026-07-24-eval-evaluator-design](../docs/superpowers/specs/2026-07-24-eval-evaluator-design.md)
- 验证报告: [2026-07-24-eval-evaluator-verify](../docs/superpowers/reports/2026-07-24-eval-evaluator-verify.md)
- OpenSpec change: [`2026-07-24-eval-evaluator`](../openspec/changes/archive/2026-07-24-eval-evaluator/)

## 目标与范围

交付确定性的 `forgeagent.evaluation.v1` 指标与有界本地趋势、保护原 20 项可信 golden
core 的 canonical manifest baseline，以及显式 opt-in 的独立真实模型 Evaluator。普通
Task、REPL、serve 和 offline golden 不调用 Evaluator；缺失指标保持 `null`，不伪造
0/100；不增加服务、数据库、依赖、HTTP endpoint 或 M22 的打回编排。

## 方案设计

- 评估记录只聚合 golden、固定 `llm.outcome` 和 `task.outcome` 机器证据；严格限制 schema、
  数值范围、diagnostics、run ID 和趋势 index。
- Golden manifest baseline 覆盖有序 ID、标题与真实模型 eligibility，runner 在报告前拒绝
  任何删除、替换、降标或顺序漂移，且没有自动更新路径。
- Evaluator 先完成 model credential preflight，再校验并复制声明 artifact 到一次性 snapshot；
  独立 Task 只有 FileRead/FileList，不带 Generator conversation、Memory、Skills、MCP 或 audit sink。
- 专用 YAML 结果必须满足状态不变量：passed 有观察证据且无 unmet，failed 必须有 unmet；
  所有公开文本有界、脱敏并转义控制字符。

## 子任务清单

- [x] 固定 20 项 trusted-core manifest baseline 与漂移守卫
- [x] 实现安全指标聚合、record、趋势比较和原子持久化
- [x] 实现显式 opt-in CLI 与独立 artifact Evaluator
- [x] 更新 README、文本协议、威胁模型和 ACTION_PLAN
- [x] 完成专项/全量/golden/静态/构建/OpenSpec 门禁
- [x] 修复独立评审发现的 9 项边界缺陷并通过最终复审

## 交付物清单

- [x] `src/forgeagent/evaluation.py` — typed metrics、safe projection、record/trend
- [x] `src/forgeagent/evaluator.py` — artifact validation、snapshot、独立 Task facade
- [x] `src/forgeagent/cli.py`、`src/forgeagent/task.py` — opt-in 入口与 bounded task outcome audit
- [x] `tests/golden/manifest_baseline.json` 与 runner baseline preflight
- [x] evaluation/evaluator/CLI/Task/golden 的表驱动、隔离、安全和真实反馈链测试
- [x] README、文本协议、威胁模型、OpenSpec、验证报告与本里程碑记录

## 三次评审

### 技术方案评审

- [x] 对照 ACTION_PLAN M20、OpenSpec proposal/design/specs 与 Superpowers Design Doc 复核范围。
- [x] 未偏离既定目标；implementer 失败后按用户指示切换为主 agent inline execution，未扩大能力。
- [x] 未引入 M21 loop、M22 Duo/Triad、常驻服务、HTTP endpoint、新依赖或自动真实模型调用。

### 代码评审

- [x] 已委派独立 code-reviewer subagent 审查本里程碑完整 diff。
- [x] 初审 7 项均已修复：趋势路径穿越、未声明文件可读、round metrics 不可达、无证据通过、
  unsafe schema/path 和普通 CLI 顶层依赖。
- [x] 复审追加 2 项均已修复：真实 `task.outcome` emitter 与趋势 limit/无界扫描。
- [x] 最终复审结论为 no findings，批准当前实现。

### 验收评审

- [x] ACTION_PLAN 验证满足：专项 `466 passed`；完整回归 `1617 passed, 11 skipped`；
  trusted golden `20/20 passed (100.0%)`。
- [x] ACTION_PLAN 门禁满足：Ruff format/check、package build、OpenSpec strict、diff check 全部通过。
- [x] 普通 run/REPL/serve/offline golden 不加载或调用 Evaluator，原 20 项 baseline 保持不变。

## 遗留问题

- [ ] 未执行 credentialed real-model Evaluator — 影响：缺少真实 provider 语义样本；计划：保持
  显式 opt-in，由有凭证的用户按需运行，不作为离线完成门禁。
- [ ] Evaluator 判断非确定且 snapshot 前存在同机修改窗口 — 影响：意见可能波动，复制时内容
  可能变化；计划：保留现有大小复核、只读 snapshot 和非 CI 定位，若出现实证问题另立 change。

## 续接指引

M20 实现、验证与 `eval-evaluator` change 归档均已完成，已合入 `main`。下一计划里程碑为
M21 Loop Engineering：在不把 M20 Evaluator 自动接入普通 Task 的前提下，设计
trigger、checkpoint/resume、stop conditions 和收敛反馈环；M22 才讨论 Generator/Evaluator
打回与 Planner 清单语义。继续保持 offline CI、20 项 trusted core 和显式真实模型成本边界。
