# M22 Triad Mode 验证报告

- Change: `triad-mode`
- 基线提交: `a3b28674a1ccb6db7d0da70a42fc987bac240df8`
- 验证实现提交: `111d60a`
- 归档状态提交: `489999a`
- 验证模式: full
- 结论: PASS；实现、逐任务审查、完整 diff 审查与全部完成门禁通过，可以归档

## 结果总览

| 维度 | 当前证据 |
| --- | --- |
| 协作基础 | 严格 state/report、原子 store、结构化工具和确定性路由已实现 |
| Duo | Generator 提交验收、独立 Evaluator、证据打回与 rejection limit 已实现 |
| Triad | Planner WHAT-only 计划、确认门、冻结 digest 与三角色隔离已实现 |
| 入口 | CLI/REPL/HTTP/Loop 与安全报告/审计已接入；普通 single 路径保持兼容 |
| 审查 | Task 1-4 均经独立 reviewer；Critical/Important 已在进入下一任务前修复 |
| 完成门禁 | 协作专项 281 passed；全量 2069 passed / 11 skipped；golden 20/20；Ruff/build/OpenSpec strict/diff 全部通过 |

## Task 1-4 实现证据

- Task 1（`f288e86` 至 `b8f9c1b`）：`CollaborationState`/`CollaborationReport`、
  `CollaborationStore`、`SubmitPlan`/`SubmitEvaluation`、角色 registry 和编程任务路由。
  架构修复后 gate re-review 通过；Task 1 suite `211 passed`。
- Task 2（`bdc381f`、`cd8602b`）：Duo fresh Generator/Evaluator、提交验收、逐项 verdict、
  reject/fix/pass、取消、稳定失败与 usage 聚合。修复 1 个 Important 后 reviewer 通过；
  focused runner `18 passed`，collaboration regression `229 passed`。
- Task 3（`5396b3b`、`41f05e4`）：Planner 提交 + standalone completion、交互/headless
  确认、冻结计划完整性、Triad 流转和上下文隔离。修复 3 个 Important 后 reviewer 通过；
  recovery/confirmation/cancel targeted `20 passed`，related regression `365 passed`。
- Task 4（`6f3a133`、`89c533e`）：`run --mode`、`/duo`、`/triad`、HTTP strict schema、
  server-owned policy、安全公共投影、Loop collaboration freeze/resume 与 audit。修复 3 个
  Important 后 reviewer 通过；targeted `18 passed`，Task 4 regression
  `584 passed, 10 skipped`。

上述数字来自各任务提交前的协调记录；最终报告将在完成门禁后用同一 HEAD 的新鲜命令结果
替换/补充，不把旧的 focused 结果冒充最终全量证据。

## 文档与静态合同 TDD

初始 RED：

```text
UV_CACHE_DIR=/tmp/forgeagent-m22-docs-uv-cache uv run pytest -q \
  tests/test_collaboration_docs.py
5 failed, 1 passed in 0.02s
```

失败分别证明 README、文本协议、HTTP、威胁模型和收尾产物尚未描述 M22；依赖不变合同已
通过。补齐文档后的 GREEN：

```text
UV_CACHE_DIR=/tmp/forgeagent-m22-docs-uv-cache uv run pytest -q \
  tests/test_collaboration_docs.py
6 passed in 0.01s
```

## 基线与验证环境说明

M22 开始时，在受限 sandbox 中运行完整 suite 得到：

```text
1734 passed, 23 skipped, 12 failed
```

其中 11 项为 M16 真实 loopback socket blackbox 因 sandbox 禁止绑定端口而失败，1 项为
`tests/test_packaging.py` 内嵌 `uv build` 的 sandbox 权限失败。相同代码的 M21 归档 HEAD
在允许这些操作的环境已记录 `1758 passed, 11 skipped`。这些基线只说明环境差异；M22
最终结论必须以当前 HEAD 重跑结果为准，不能沿用 M21 数字。

## 最终完成门禁

```text
UV_CACHE_DIR=/tmp/forgeagent-m22-final2-uv-cache uv run pytest -q \
  tests/test_collaboration_models.py tests/test_collaboration_store.py \
  tests/test_collaboration_tools.py tests/test_collaboration_routing.py \
  tests/test_collaboration_runner.py tests/test_collaboration_planner.py \
  tests/test_collaboration_integrations.py tests/test_collaboration_docs.py
# 281 passed in 0.63s

UV_CACHE_DIR=/tmp/forgeagent-m22-final2-uv-cache uv run pytest -q
# 2069 passed, 11 skipped in 86.56s

UV_CACHE_DIR=/tmp/forgeagent-m22-final2-uv-cache uv run python -m tests.golden.runner \
  --output-dir /tmp/forgeagent-m22-golden-final2
# report.md: 20/20 passed (100.0%)

UV_CACHE_DIR=/tmp/forgeagent-m22-final2-uv-cache uv run ruff format --check .
# 100 files already formatted
UV_CACHE_DIR=/tmp/forgeagent-m22-final2-uv-cache uv run ruff check .
# All checks passed!
UV_CACHE_DIR=/tmp/forgeagent-m22-final2-uv-cache uv build \
  --out-dir /tmp/forgeagent-m22-dist-final2
# sdist and wheel built successfully
openspec validate --all --strict
# 17 passed, 0 failed
git diff --check a3b28674a1ccb6db7d0da70a42fc987bac240df8..HEAD
# exit 0
```

受限 sandbox 的完整 suite 为 `2042 passed, 23 skipped, 12 failed`，失败仍是 11 个 M16
loopback blackbox 无法绑定端口与 1 个嵌套 `uv build` 权限限制。相同 HEAD 获准在非沙箱运行后
为 `2069 passed, 11 skipped`，证明这些失败均为验证环境限制。

## 安全与兼容性核对

- 无新 HTTP endpoint；仍只有 submit/query/cancel 三个 `/tasks` 路由。
- 无新 runtime dependency；`pyproject.toml` 的项目依赖集合保持不变。
- Evaluator registry 只有 `FileRead`、`FileList`、`SubmitEvaluation`，默认 restricted。
- HTTP 客户端不能设置 role model/tier、rejection limit、Planner approval、override、root、
  credentials 或 checkpoint path；这些由服务端拥有。
- 公开协作报告不包含完整 goal、计划/verdict 正文、prompt、模型回复、tool args、文件内容、
  credential 或绝对路径。
- 普通 single Task、single Loop 和 M20 opt-in `evaluate` 保持独立完成语义。

## Opt-in 与已知限制

- 同一编程任务的 single/Triad 真实模型质量比较需要 provider key、会产生费用，未纳入离线
  CI；最终报告须明确“未验证”，不得用 mock replay 代替真实判别力结论。
- v1 角色严格串行；Evaluator 没有 Exec，只能读取产物或 Generator 预先生成的测试报告。
- headless Triad 默认 deny；`preauthorize` 是明确的服务端策略，不代表计划经过人工判断。
- cooperative cancel 不能强杀正在进行的 provider/tool call，只在下一安全边界收敛。
- Duo/Triad 和每次 rejection 都会增加模型调用、延迟和费用；usage 缺失明确投影为 unavailable。

## Review 收口

- [x] 完整 M22 diff 独立 code review：发现协作 Loop 可恢复角色失败被终态化，提交
  `111d60a` 修复；定向复核 APPROVED。
- [x] 最终自审 1（OpenSpec/设计/实现/文档一致性）：12 个 requirements、43 个 scenarios
  均有实现/测试映射；Task 1-5 与 plan/OpenSpec 全部勾选，无设计漂移。
- [x] 最终自审 2（状态机/权限/持久化/成本/兼容性）：确认 standalone 与 Loop 恢复策略分离、
  Evaluator read-only、HTTP server-owned authority、计划冻结、增量 rounds/usage 记账、single 路径兼容。
- [x] 独立复核：`/tmp/m22-sdd/final-rereview-report.md` 结论 APPROVED；无剩余
  Critical/Important。

## OpenSpec 完整验证

| 维度 | 结果 |
| --- | --- |
| Completeness | 20/20 OpenSpec tasks 完成；12/12 requirements 已实现 |
| Correctness | 43/43 scenarios 有代码路径与 focused/integration tests；最终门禁全绿 |
| Coherence | 实现遵循 OpenSpec design 与技术设计；仅增加 Loop-owned recover policy 以满足既有可恢复失败场景 |

最终评估：All checks passed. Ready for archive.

## 归档结果

- 本地 `main` 已 fast-forward 到 M22 验证提交，并在合并结果上复验：`2069 passed, 11 skipped`。
- Comet verify guard 通过，OpenSpec archive `7/7` 步骤成功。
- delta specs 已合并到主 specs：`+9` requirements、`~3` requirements；新建
  `openspec/specs/runtime-collaboration/spec.md`。
- change 已移动到 `openspec/changes/archive/2026-07-24-triad-mode/`，其中
  `.comet.yaml` 记录 `archived: true`。
- 归档后 OpenSpec strict `17 passed, 0 failed`；文档/集成/Loop 定向回归 `44 passed`。

## 归档后复核

2026-07-25 的独立复核发现 Planner HOW 校验只覆盖 `acceptance`、协作审计未完整实现
route 与角色异常 lifecycle。后续 hotfix `collaboration-contract-hotfix` 补齐双字段校验、
`collaboration.route` 和角色 start/outcome 安全字段；最终证据以该 hotfix 验证报告为准。
修复后的全量结果为 `2073 passed, 11 skipped`，golden `20/20`，OpenSpec strict
`18/18`。
