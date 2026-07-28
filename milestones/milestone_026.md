# 里程碑 M26: 协作完成证据绑定

- 状态: 已完成并归档
- 起止: 2026-07-28 ~ 2026-07-29
- 对应 ACTION_PLAN 行: M26（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_025](milestone_025.md)
- 技术设计: [2026-07-28-bind-collaboration-completion-evidence-design](../docs/superpowers/specs/2026-07-28-bind-collaboration-completion-evidence-design.md)
- 实施计划: [2026-07-28-bind-collaboration-completion-evidence](../docs/superpowers/plans/2026-07-28-bind-collaboration-completion-evidence.md)
- OpenSpec change: [`2026-07-28-bind-collaboration-completion-evidence`](../openspec/changes/archive/2026-07-28-bind-collaboration-completion-evidence/)
- 验证报告: [2026-07-28-bind-collaboration-completion-evidence-verify](../docs/superpowers/reports/2026-07-28-bind-collaboration-completion-evidence-verify.md)

## 目标与范围

修复 M25 暴露的 false completion：当可信宿主为 Duo/Triad Evaluator 注册冻结检查时，全部
验收项自报通过不再足以完成协作。全部检查必须在当前 Evaluator Task 内真实通过，并同时绑定
当前 Generator attempt 与同一当前 Candidate 快照。恢复、新 attempt、检查后修改、失败或过期
证据均 fail closed；提前拒绝和未配置检查的既有行为保持兼容。

范围只覆盖完成证据绑定、安全审计、测试与独立 M26 证据。未调整 M27 协作模式路由，未修改
M23/M25 历史 evidence，未新增依赖、状态 schema、公开配置面或通用证据框架。

## 方案设计

- `CheckResult` 增加只供宿主使用的 Candidate snapshot digest；摘要范围与临时副本复制规则一致。
- 单次 evaluator registry 创建私有 `_CheckEvidence` 表，由 `RunCheckTool` 与
  `SubmitEvaluationTool` 共享；新 Task/恢复/新 attempt 自然得到空表。
- 全通过提交要求所有冻结检查最新状态为 passed、attempt 相同、摘要一致且仍匹配当前 Candidate；
  失败 verdict 不要求先运行全部检查。
- 证据不写入 `CollaborationState`，避免 schema/migration 和跨进程环境错误复用。
- `collaboration.check` 审计仅保留稳定安全元数据；命令、路径、输出、内容和 digest 不外泄。
- 独立 M26 harness 固定 Duo/Triad x skip-check-first/all-pass 四场景，输出根与 M23/M25 隔离。

## 子任务清单

- [x] 计算并验证与实际检查副本一致的 Candidate snapshot digest
- [x] 建立当前 Evaluator Task 私有的可信检查证据表
- [x] 将全通过 `SubmitEvaluation` 绑定全部当前检查证据
- [x] 覆盖提前拒绝、无检查兼容、恢复和新 attempt 语义
- [x] 增加不泄露执行内容的 `collaboration.check` 审计
- [x] 建立并冻结 M26 独立四场景受控端到端证据
- [x] 完成目标回归、沙箱可执行全套、Ruff 与 OpenSpec strict
- [x] 完成产品实现与证据提交 `354592f`
- [x] 完成 Comet full verify、分支处理和 change 归档，delta spec 已同步到主规格

## 交付物清单

- [x] `src/forgeagent/check_runner.py` — 检查副本 snapshot digest 与变化检测
- [x] `src/forgeagent/collaboration.py` — Task 私有证据、全通过门与安全检查审计
- [x] `tests/test_check_runner.py` — digest 稳定性、忽略、变化和错误路径
- [x] `tests/test_collaboration_tools.py` — 缺失/失败/旧 attempt/混合摘要/变化/全通过/兼容
- [x] `tests/test_collaboration_runner.py` — 恢复和新 Generator attempt 不复用证据
- [x] `scripts/m26_completion_evidence_evaluation.py` — 独立、安全、可复验的四场景 harness
- [x] `tests/test_m26_completion_evidence_evaluation.py` — 协议、路径、schema、篡改和回退测试
- [x] `docs/evaluation/m26/` — 协议、权威受控批次与中间批次审计标记
- [x] `README.md`、`docs/text-protocol-spec.md`、`docs/http-task-service.md`、`docs/threat-model.md` — 运行时合同同步
- [x] `ACTION_PLAN.md` 与本里程碑文件 — 当前状态和续接边界

## 三次评审

### 技术方案评审

- [x] proposal 的 false completion 根因已由宿主可信证据门直接收敛。
- [x] design 的五项决策全部落地：Task 私有表、实际输入摘要、只约束全通过、恢复重跑、安全审计。
- [x] 未偏离 Non-Goals；M27 路由、M23/M25 历史证据、依赖和持久 schema 均未扩大。

### 代码评审

- [x] Task 1-3 thorough review 无未解决 Critical/Important/Minor。
- [x] Task 4 review 发现并修复 fixture 路径逃逸、symlink、执行类型复用、provider 分类、严格
  schema/交叉一致性和安全临时文件问题；冻结 SHA 复审通过。
- [x] 最终两轮自审发现并修正 M23 未来全局字节锁和运行时文档遗漏。
- [x] 本地合并后复验暴露 2 个 Runner 测试未绑定 `tmp_path`；确认生产 builder 均绑定 workspace
  后，只修测试夹具且保留特殊文件 fail-closed，最终聚焦与全套复验通过。
- [x] 未发现未处理的 Critical/Important 正确性、安全或边界问题。

### 验收评审

- [x] M26 本地合并后最终聚焦回归 `274 passed in 35.98s`；harness 最终测试 `38 passed`。
- [x] 本地合并后沙箱可执行全套 `2408 passed, 22 skipped in 99.30s`；Ruff check/format 与
  `git diff --check` 通过。
- [x] OpenSpec 归档前当前 change valid、全库 strict `21 passed, 0 failed`；归档后主规格
  `20 passed, 0 failed`。
- [x] 权威批次 `2026-07-28-final-v5` 输出
  `M26_EVALUATION_OK runs=4 execution=controlled`，绑定 harness 与两份 M26 运行时源码 hash，
  4/4 completed；明确记录 `fallback_reason=provider_unavailable`，没有冒充 credentialed 真实模型结果。
- [x] M23/M25 evidence 相对 M26 planning base 无差异。
- [x] 缓存离线 `uv build --offline` 成功生成 wheel 与 sdist。
- [ ] mypy、11 个 loopback 黑盒与 packaging 全依赖安装补证 — 沙箱/离线缓存限制且审批
  基础设施 403 拒绝；未宣称通过，详见验证报告。
- [x] ACTION_PLAN 门禁“已归档” — Comet archive `7/7` steps succeeded，归档状态为 `archived: true`。

## 遗留问题

- [ ] credentialed provider 服从性 — 影响：当前 4/4 只证明真实运行时门禁链，不证明外部模型
  一定按工具顺序工作 — 计划：在具备 provider 和外发授权时新建 run，不改写 final-v5。
- [ ] hostile concurrent writer — 影响：hash 检测正常变化但不是事务级文件系统 snapshot — 计划：
  保留威胁模型限制；如需更强保证另立 capability，不在 M26 扩张。

## 续接指引

M26 已完成并归档，主 `runtime-collaboration` spec 已同步。下一步如启动 M27，必须建立新的
Comet/OpenSpec change，范围只做协作路由校准，不能改写 M26 受控证据。`.superpowers/sdd/task-1-report.md`
是用户保留审查的无关修改，继续留在现有 worktree；受环境限制的 mypy/loopback/packaging 证据
保持明确未验证。M26 分支只做本地合并，不 push。
