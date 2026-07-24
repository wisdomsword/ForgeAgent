# M22 Triad Mode 验证报告

- Change: `triad-mode`
- 基线提交: `2433b7689f275caef4e42c991317934d615aeb36`
- 当前实现提交: `3ff3f6c`
- 验证模式: full（收口中）
- 结论: Task 1-4 已实现并完成逐任务审查；最终全量验证待主流程补录

## 结果总览

| 维度 | 当前证据 |
| --- | --- |
| 协作基础 | 严格 state/report、原子 store、结构化工具和确定性路由已实现 |
| Duo | Generator 提交验收、独立 Evaluator、证据打回与 rejection limit 已实现 |
| Triad | Planner WHAT-only 计划、确认门、冻结 digest 与三角色隔离已实现 |
| 入口 | CLI/REPL/HTTP/Loop 与安全报告/审计已接入；普通 single 路径保持兼容 |
| 审查 | Task 1-4 均经独立 reviewer；Critical/Important 已在进入下一任务前修复 |
| 完成门禁 | 文档静态合同正在补齐；全量 pytest/golden/Ruff/build/OpenSpec/diff 待最终执行 |

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

## 待最终补录的完成门禁

```text
UV_CACHE_DIR=/tmp/forgeagent-m22-final-uv-cache uv run pytest -q \
  tests/test_collaboration_models.py tests/test_collaboration_store.py \
  tests/test_collaboration_tools.py tests/test_collaboration_routing.py \
  tests/test_collaboration_runner.py tests/test_collaboration_planner.py \
  tests/test_collaboration_integrations.py tests/test_collaboration_docs.py

UV_CACHE_DIR=/tmp/forgeagent-m22-final-uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/forgeagent-m22-final-uv-cache uv run python -m tests.golden.runner \
  --trusted-core --output-dir /tmp/forgeagent-m22-golden-final
UV_CACHE_DIR=/tmp/forgeagent-m22-final-uv-cache uv run ruff format --check .
UV_CACHE_DIR=/tmp/forgeagent-m22-final-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/forgeagent-m22-final-uv-cache uv build \
  --out-dir /tmp/forgeagent-m22-dist-final
openspec validate --all --strict
git diff --check 2433b7689f275caef4e42c991317934d615aeb36..HEAD
```

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

## Review 收口占位

- [ ] 完整 M22 diff 独立 code review：待主流程执行并补录结论/修复。
- [ ] 最终自审 1（OpenSpec/设计/实现/文档一致性）：待主流程执行。
- [ ] 最终自审 2（状态机/权限/持久化/成本/兼容性）：待主流程执行。
- [ ] OpenSpec archive、主分支合并与归档后复验：待主流程完成后补录。
