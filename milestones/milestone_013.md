# 里程碑 M13: 核心正确性加固

- 状态: 已完成（以所有验收证据槽位均为 APPROVED 为生效条件）
- 起止: 2026-07-13 ~ 2026-07-17
- 对应 ACTION_PLAN 行: M13（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_009](milestone_009.md)（M9 是在 M10 完成后补做的最后一个既有里程碑；M9/M10 均已完成，M11/M12 仍是后续规划，因此本次加固按批准编号记录为 M13）
- 已验证实现 HEAD: `77663b0b974b48fa124d63788f4ce3cf2acd1165`

## 目标与范围

摘自 ACTION_PLAN.md §四 M13 行：

- 交付物：环境代理显式禁用与逐跳 SSRF；统一工具确认与最小披露；严格两阶段完成；MCP required、generation-safe 生命周期与有界关闭；20 项可执行离线黄金核心（5 项真实模型 opt-in）；协议、威胁模型与 README 同步。
- 验证：Ruff；完整 pytest；20 项离线黄金核心 20/20；CodeGraph 调用面复审。
- 门禁：三道独立评审：技术一致性、全分支代码、验收证据。

范围坚持最小化：未增加代理转发实现、新依赖、通用安全策略框架、并发 golden runner 或无关产品功能；`spec.md` 仍是最高约束。

## 方案设计

设计依据：

- `docs/superpowers/specs/2026-07-13-hardening-core-correctness-design.md`
- `docs/superpowers/plans/2026-07-13-hardening-core-correctness.md`
- `openspec/changes/hardening-core-correctness/` 下 proposal、design、tasks 和五份 capability delta spec

关键裁决：

1. 受保护网络请求固定使用 `ProxyHandler({})`，显式忽略环境代理；301/302/303/307/308 共享 guard-owned 路径，先按绝对 10 跳上限判断，再解析相对 URL、限制 HTTP(S) scheme，并由 guarded connection 在每跳 DNS/connect 前复检地址。
2. MCP、restricted/container WebFetch 和 FileWrite 共用类型安全 confirmer；非 TTY 无确认通道时默认拒绝。展示只保留完成决策所需字段，处理已知 secret、显示键碰撞、控制字符、malformed URL 和路径披露。
3. `completed: true` 只有在无工具调用、无解析错误的独立响应中生效；工具结果先反馈，显式 `completed: false` terminal status 保持原语义。
4. MCP holder/session 使用 `(name, generation, task, stop)` 和 `(name, generation, session)` 精确归属；enable/disable/call/close 的共享状态由 loop-owned reconcile 管理。关闭使用绝对 deadline、唯一 drain task、可重试完成事件和精确资源保留。
5. holder 取消按嵌套 async-context ownership 捕获：ready 先于对应 teardown 发布，保存的原始 `CancelledError` 覆盖 teardown `BaseException`、第二次取消和 suppression；generation cleanup 不误删 replacement。
6. 20 项黄金核心是唯一可执行可信集；其余 360 项仍为候选。离线 runner 隔离 HOME/USERPROFILE/XDG_CONFIG_HOME，5 项真实模型仅显式 opt-in，不作为 CI 门禁。

## 子任务清单

- [x] 隔离测试 HOME/配置根目录，收敛本地 bind、进程和真实资源清理 fixture
- [x] 显式禁用环境代理，实施逐跳 SSRF、相对重定向、scheme 和 10 跳上限验证
- [x] 统一 MCP/WebFetch/FileWrite confirmer，固定安全 outcome 与最小披露
- [x] 实施严格两阶段完成门控并锁定显式非完成终态
- [x] 实施 MCP required、并发启动、generation-safe lifecycle 和绝对 deadline close
- [x] 建立 20 项离线黄金核心、5 项 real opt-in、同源 JSON/Markdown 报告和退出码
- [x] 同步协议、威胁模型、README、ACTION_PLAN、OpenSpec 和 Superpowers 文档
- [x] 完成 Ruff、专项/全量 pytest、黄金 runner、CodeGraph 和两道实现评审

## 交付物清单

- [x] `src/forgeagent/ssrf_guard.py` / `src/forgeagent/web_search.py` / `src/forgeagent/tools.py` - 直连、逐跳边界、消费端异常收敛和固定安全结果
- [x] `src/forgeagent/cli.py` / `src/forgeagent/step.py` / `src/forgeagent/task.py` - TTY confirmer 接线、最小披露和严格完成状态转换
- [x] `src/forgeagent/mcp_manager.py` - required 服务、公开身份脱敏、generation-safe reconcile、启动事务和有界关闭
- [x] `tests/test_ssrf_guard.py` / `tests/test_web_search.py` / `tests/test_web_file_tools.py` / `tests/test_cli.py` / `tests/test_step.py` / `tests/test_task.py` - 网络、确认、反馈和完成门控回归
- [x] `tests/test_mcp_manager.py` / `tests/mcp_fixture_server.py` - MCP 并发、generation、取消、控制异常、PID 和 hard-stuck 回归
- [x] `tests/golden/` / `tests/test_golden_runner.py` - 20 项 manifest、离线/real 入口、隔离、报告、证据类型和有界子进程测试
- [x] `README.md` / `docs/` / `openspec/changes/hardening-core-correctness/` - 当前协议、安全边界、代理迁移和验证口径
- [x] `ACTION_PLAN.md` - M13 交付物、验证和三评审门禁；M11/M12 用户规划原样保留

## 三次评审

### 技术方案评审

- [x] 独立 reviewer `Galileo`（`019f6bfb-7943-7093-aef0-cc1348d96bac`）对照 `spec.md`、ACTION_PLAN M13、Design Doc、实施计划、OpenSpec 全套产物、公开文档、实现和测试，结论 APPROVED；无 Critical/Important
- [x] 网络、确认/披露、两阶段完成、MCP lifecycle/cancellation 和黄金核心五类契约在设计、spec、代码和测试之间一致
- [x] 唯一 Minor 是 M13 前已有 README “API key 不存配置”绝对表述与可选用户 literal key 能力不够精确；判定为非阻塞基线债务，本 change 不扩大范围

### 代码评审

- [x] 独立 whole-branch reviewer `Euclid`（`019f6c12-dfea-77a3-a7bc-fbc35112f7ef`）审查 base `a453c82d15dde32064d262fc45dd8300033dd9ad` 到 verified HEAD 的 8 个生产模块及映射测试，覆盖正确性、安全、并发、资源生命周期、泄漏和测试可信度
- [x] 唯一 Important 是并发 holder barrier 与 3 个 standalone golden 子进程可能无限等待；已由 `77663b0` 改为 1 秒并发断言和 30 秒子进程超时
- [x] 顺序启动 mutation 在 `1.29s` 内以 `holders did not begin waiting concurrently` 失败；修复后 reviewer 对当前候选重新给出 APPROVED，无 Critical/Important/Minor

### 验收评审

- [x] ACTION_PLAN M13 “Ruff”要求：`uv run ruff check src tests` 输出 `All checks passed!`
- [x] 26 个相对 base-ref 新增/修改 Python 文件通过 `ruff format --check`；全仓诊断仅有 8 个未被本 change 修改的历史格式文件
- [x] 专项矩阵：`603 passed, 3 skipped in 17.00s`；skip 为本地 bind、外网能力和明确标记的慢 MCP hang spike
- [x] 完整 pytest：`886 passed, 13 skipped in 26.37s`；10 个 Docker/image、1 个慢 hang、1 个本地 bind、1 个外网能力均有明确理由；`RuntimeWarning` 和 `PytestUnraisableExceptionWarning` 提升为失败
- [x] 离线黄金核心：runner 退出 `0`；JSON schema `forgeagent.golden.v1` 和 Markdown 均报告 `20/20`、失败 `0`、`100.0%`
- [x] CodeGraph 报告索引属于主 checkout；按计划记录警告后，用当前 worktree 直接复核 WebFetch/search、run/REPL/Task/Step、MCP CLI 和 golden runner/pytest 调用面
- [x] `openspec validate hardening-core-correctness --strict` 和 `git diff --check` 通过；`ACTION_PLAN.md` SHA-256 为 `64ab3ca0b0b12e341233332481a5c83189d840f9bdf5b3a1ee0a8ed741bc5a15`
- [x] Comet build guard dry-run 全部通过；该 guard 只原生推断 npm/Maven/Cargo，本 uv/Python 项目使用其显式 `COMET_SKIP_BUILD=1` 分支，实际 Ruff、专项、全量和黄金验证仍由上述原始日志承担
- [x] 验收证据独立评审: APPROVED by reviewer `Kuhn` (`019f6c3d-9adf-7151-9aa4-3cfc5fb423fc`)
- [x] Build guard 证据修正复评: APPROVED by reviewer `Kuhn` (`019f6c3d-9adf-7151-9aa4-3cfc5fb423fc`)

## 遗留问题

- [ ] README 的旧表述称 API key 不存配置，但可选用户配置支持 literal key - 影响：可能误导凭证静态存储判断 - 计划：作为 M13 前既有文档债务，在后续文档清理中精确区分 shipped config 与 user config
- [ ] MCP loop thread 完全 hard-stuck 时 Python 无法安全强杀线程 - 影响：公开 close 按 deadline 返回但保留资源引用并记录脱敏 warning - 计划：维持已批准 residual threat 和 repeated-close retry，不伪造清理完成
- [ ] 5 项真实模型黄金场景未运行 - 影响：不影响离线 CI 门禁 - 计划：仅在显式模型和凭证可用时 opt-in 运行并生成独立报告
- [ ] 全仓仍有 8 个历史 Ruff format 差异文件 - 影响：不属于本 change，变更文件格式门禁已通过 - 计划：后续独立格式清理，不在安全加固中制造无关 churn

## 续接指引

M13 的已验证实现固定为 `77663b0b974b48fa124d63788f4ce3cf2acd1165`。网络、工具确认/最小披露、两阶段完成、MCP required/generation/close/cancellation 和 20 项离线黄金核心均已实现，Ruff、专项/全量 pytest、黄金 runner、CodeGraph 调用面、技术一致性和 whole-branch 代码评审均通过。

下一步只允许独立验收证据 reviewer 对照原始命令输出审查本文件、tasks、`.comet/subagent-progress.md` 和 Task 11 plan checklist，并把尚未完成的验收证据槽位改为自己的 APPROVED verdict/identity。若发现 evidence-only 转录错误，仅修正证据并重复验收评审；若发现源码、测试、spec 或公开文档问题，必须取消本 verified HEAD 并从 Task 11 Step 1 重跑。验收通过后提交 evidence-only 文件，确认 verified HEAD 到最终 HEAD 仅含 tasks/progress/milestone 和 plan checklist 证据；ACTION_PLAN M13 已在 verified HEAD 中，用户 M11/M12 差异继续不提交。随后运行 build guard 并进入 Comet verify。M11/M12 仍是后续规划，不属于 M13 实现。
