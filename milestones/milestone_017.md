# 里程碑 M17: Context Engineering

- 状态: 已完成
- 起止: 2026-07-22 ~ 2026-07-23
- 对应 ACTION_PLAN 行: M17（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_016](milestone_016.md)
- 最终实现 commit: `a9c14cd`
- 验证状态 commit: `c50ae9e`
- OpenSpec 归档: `openspec/changes/archive/2026-07-22-runtime-context-engineering/`

## 目标与范围

为 CLI、REPL 与 HTTP 的共享 `Task -> Step` 执行链增加有界上下文工程能力：按模型
能力和输出预留构造 sliding-window request view；统一限制所有工具反馈并提供诚实的
截断与 continuation 语义；保持 prompt-cache 稳定前缀；在 provider adapter 边界归一化
prompt token 分母，并向 CLI/session 与 `llm.outcome` 审计提供一致的 cache hit rate。

M17 不实现 importance、summary、hybrid、Memory、checkpoint 或 token stop policy，不改变
HTTP endpoint、请求/响应 schema 或 M16 鉴权、取消、安全投影、审计和 allowlist 契约。

## 方案设计

- 新增独立 `context.py` 函数式核心：集中配置、近似 token estimator、最小
  `ContextPolicy` Protocol、唯一 `SlidingWindowContextPolicy` 和 feedback limiter。
- `Task` 在构造时按 `floor(context_window * utilization_ratio) - max_output_tokens`
  固化 policy；`Step` 继续唯一持有完整 conversation，只在每次 provider 调用前取得非
  破坏性 request view。
- 初始 system/goal 或不可拆分的最新 round 超预算时，在 `llm.attempt` 审计和 provider
  调用前结构化失败；不截断目标、不制造孤立 ToolCall/feedback。
- 工具反馈使用自适应单轮/单结果上限、确定性水位分配及工具自持的
  `truncation_mode`/`continuation`；完整 `ToolOutcome` 始终保留在 `RoundResult`。
- Anthropic 与 OpenAI-compatible adapter 分别计算内部 `total_prompt_tokens`；CLI 和
  audit 只消费统一口径，HTTP usage projection 不扩字段。
- 配置缺失使用有界默认值，存在但无效则 fail-closed；REPL reload 对 model registry 与
  context config 做事务化替换，HTTP 在 listener bind 前验证服务端 policy。
- 技术设计：`docs/superpowers/specs/2026-07-22-runtime-context-engineering-design.md`；实施
  计划：`docs/superpowers/plans/2026-07-22-runtime-context-engineering.md`；验证报告：
  `docs/superpowers/reports/2026-07-23-runtime-context-engineering-verify.md`。
- 经设计阶段批准，ACTION_PLAN/TECH_PATH 中“预留四策略形状”收敛为最小 Protocol +
  唯一 sliding-window 实现；没有为未实现策略增加空实现、factory、manager 或 registry。

## 子任务清单

- [x] Context 配置、近似 token estimator 与安全预算公式
- [x] Sliding-window policy、完整 round 保留与调用前 fail-fast
- [x] Task/Step/CLI/REPL/HTTP 共享 policy 装配
- [x] 全工具 feedback limiter、水位分配、head/tail 与诚实 continuation
- [x] Provider-normalized prompt denominator、CLI/session cache hit rate 与审计字段
- [x] Prompt-cache 稳定前缀、长对话 mock replay 与 M16 HTTP 回归
- [x] 配置、模型契约、HTTP、usage 与威胁模型文档
- [x] OpenSpec strict 验证、Comet full verify、分支保留和 delta spec 归档

## 交付物清单

- [x] `src/forgeagent/context.py` — 配置、估算、policy、窗口选择与 feedback limiter
- [x] `src/forgeagent/task.py` / `step.py` — policy 构造注入、request view、本地失败与统一反馈
- [x] `src/forgeagent/tools.py` — 工具截断模式和 continuation 元数据
- [x] `src/forgeagent/models.py` / 两个 provider client — 内部 normalized denominator
- [x] `src/forgeagent/cli.py` / `http_config.py` / `http_task_service.py` — 三入口装配、reload、
  cache rate 与服务端启动验证
- [x] `tests/test_context.py` 及 Task/Step/provider/CLI/HTTP/tool 测试 — 预算、滑动、截断、
  指标、入口和安全回归
- [x] `tests/test_mock_replay_e2e.py` — 超窗口长任务与稳定前缀端到端回放
- [x] `openspec/specs/runtime-context-management/spec.md` 与更新后的
  `openspec/specs/audit-logging/spec.md` — 归档后主规格

## 三次评审

### 技术方案评审

- [x] 18/18 tasks、7/7 requirements、31/31 scenarios 均有实现和自动化测试证据
- [x] proposal、OpenSpec design、Superpowers 技术设计与实现无矛盾
- [x] `openspec validate runtime-context-engineering --strict` 通过；Comet archive dry-run
  `6/6`、实际归档 `7/7 steps succeeded`

### 代码评审

- [x] 各实现任务按 TDD 经独立实现与审查回合，最终执行 whole-branch 评审
- [x] 终审发现并修复 falsey YAML 根 fail-open 和混合 feedback override 公式不一致
- [x] 最终窄范围复审确认 2/2 问题关闭，`0 Critical / 0 Important / 0 Minor`

### 验收评审

- [x] `uv run pytest -q` → `1351 passed, 11 skipped in 92.44s`（归档后最终回归）
- [x] `uv run ruff check .` → `All checks passed!`
- [x] 离线 golden runner → `20/20 passed (100.0%)`
- [x] `openspec validate runtime-context-engineering --strict` 与 `git diff --check` 通过
- [x] M16 bearer auth、严格 schema、取消、安全投影、审计降级、correlation、精确
  allowlist 和 MCP autoApprove 隔离均包含在全量回归中

## 遗留问题

- [ ] 本地 estimator 不等同 provider tokenizer — 影响：极端边界仍可能被 provider 拒绝
  — 计划：保留既有结构化 client error，不在 M17 引入厂商 tokenizer 依赖
- [ ] 未调用真实 provider API 验证 normalized denominator — 影响：当前证据来自代表性 SDK
  response fixture — 计划：后续真实模型验收时观察 provider usage 口径变化
- [ ] Sliding window 不提供语义摘要 — 影响：被淘汰的旧细节不会自动凝练 — 计划：仅在
  长任务实证需要时另立 change，不为 summary/importance/hybrid 预建占位

## 续接指引

M17 已在分支 `codex/m17-runtime-context-engineering` 完成验证并归档为
`openspec/changes/archive/2026-07-22-runtime-context-engineering/`，分支按推荐方案保留，
未 push。下一阶段是 M18 Memory 运行时：先读取 `TECH_PATH.md` §三 M18 与本文件遗留，
通过 `/comet` 创建新的 full change。M18 应复用 M15 的 MEMORY.md 文件层与 M17 的有界
上下文行为，重点裁决提取触发时机、准入规则、会话/项目两级作用域、冲突替换和记忆投毒
边界；不得顺带引入向量检索、置信度模型或团队级作用域。
