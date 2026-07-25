# 协作角色结构化提交验证报告

## 结论

`fix-collaboration-role-protocol` 验证通过。实现覆盖 9/9 tasks、3/3 requirements 和
8/8 scenarios；完整自动测试、静态检查、严格 OpenSpec 校验以及两次真实模型 Triad 验收均通过。
独立审查发现的 1 个 IMPORTANT 并发 CAS 问题已修复并复审关闭；当前未发现阻止归档的
CRITICAL 或 IMPORTANT 问题。

## 验证记分卡

| 维度 | 结果 | 证据 |
| --- | --- | --- |
| Completeness | PASS | 9/9 tasks，3/3 requirements 已实现 |
| Correctness | PASS | 8/8 scenarios 有实现与自动测试覆盖 |
| Coherence | PASS | 实现遵循 OpenSpec design 与技术 Design Doc，无 spec 漂移 |
| Security | PASS | 无新依赖、密钥、状态字段或权限扩大；Evaluator registry 保持只读 |
| Compatibility | PASS | single、Loop single、Duo、Triad、Loop duo/triad 回归通过 |

## 自动验证

2026-07-25 在仓库根目录执行：

```text
UV_CACHE_DIR=/tmp/forgeagent-final-uv-cache uv run ruff check src tests
All checks passed!

UV_CACHE_DIR=/tmp/forgeagent-final-uv-cache uv run ruff format --check src tests
102 files already formatted

UV_CACHE_DIR=/tmp/forgeagent-final-uv-cache uv run pytest -q
2151 passed, 10 skipped in 85.20s

UV_CACHE_DIR=/tmp/forgeagent-final-uv-cache uv run openspec validate fix-collaboration-role-protocol --strict
Change 'fix-collaboration-role-protocol' is valid

git diff --check
exit 0
```

沙箱内首次完整测试有 12 项环境性失败：11 项 M16 黑盒测试无法绑定 loopback 端口，1 项打包
测试无法访问用户级 uv 缓存；其余 2122 项通过。随后在宿主权限下以相同代码和独立 `/tmp` uv
缓存重跑完整命令。独立审查修复后又增加 5 个并发/锁边界用例，并以最终代码重跑得到上述
2151 项通过结果。未为沙箱环境限制修改生产代码或测试。

## Requirement 与 Scenario 映射

### 1. 协作角色使用结构化提交门完成工作

- `ToolOutcome.completes_task` 和 `ToolRegistry.required_completion_tool` 提供通用协议元数据。
- Step 按 parser 顺序执行，成功 Submit 后立即终止并截断后续工具，不生成虚假审计。
- 缺失 required Submit 首次得到精确结构化恢复提示，重复违规映射为
  `invalid_role_submission`。
- 未配置 required completion tool 的 single 与 Loop single 保持既有完成语义。
- 自动覆盖：`tests/test_tools.py`、`tests/test_step.py`、`tests/test_cli.py`、
  `tests/test_loop_runner.py`。

### 2. Generator Candidate 与当前 attempt 原子绑定

- 零载荷 `SubmitCandidate` 在 revision CAS 中同时切换 evaluator phase、递增
  `generator_attempts` 并清空旧 verdict。
- 错误 phase、stale revision 和重复提交不改变持久状态。
- Runner 只在成功 Candidate 后启动 Evaluator，并避免 attempt 双计。
- 自动覆盖：`tests/test_collaboration_tools.py`、`tests/test_collaboration_runner.py`、
  `tests/test_collaboration_integrations.py`。

### 3. Verdict 只属于当前已提交 Candidate

- `SubmitEvaluation` 原子保存完整有序 verdict 并递增 `evaluator_attempts`，终态仍由 Runner 判定。
- generator phase 保留旧 verdict 用于恢复反馈；下一 Candidate 提交时清空。
- evaluator phase 的空 verdict 重跑 Evaluator，非空 verdict 直接判定且不重复调用模型。
- 自动覆盖：`tests/test_collaboration_tools.py`、`tests/test_collaboration_runner.py`、
  `tests/test_collaboration_planner.py`。

## 设计一致性

- Step 仅消费通用 outcome/registry 元数据，不识别角色、phase 或 Submit 工具命名。
- 三个 Submit 的状态变更与 attempt 计数都在 revision-checked 保存中完成；Runner 不重复计数。
- 未新增 Candidate manifest、动态工具锁、持久状态字段、schema 迁移或 provider 专属协议。
- Generator registry 在原 registry 上组合 Candidate 门，保留 FileWrite、Checkpoint、MCP 和 Skill；
  Evaluator 仍只拥有只读文件工具、可选 RunCheck 与 SubmitEvaluation。
- Planner、Generator、Evaluator 提示统一要求 HTML ToolCall，禁止 prose、`task_status`、XML 或
  function_calls 替代结构化 Submit。

## 真实模型 Triad 验收

两次验收都使用真实 `claude-sonnet-5` Generator、`claude-haiku-4-5` Planner/Evaluator、
restricted tier、无 identity、无 memory，并在全新临时工作目录执行用户给定的
`calc.py`/`test_calc.py` 任务。为避免本机显式 40-token tool feedback 上限截断短源文件，验收使用
隔离临时 HOME，沿用同一 provider 路由，并仅把 round/tool feedback 上限提高到可读短文件的范围；
未修改用户配置，也未在报告中保存模型原始回复或 secret。

### 最终 Triad A

- 工作目录：`/tmp/forgeagent-m22-final-a.8R9cms`
- collaboration id：`fa701e1a0104420ba0e1d509b8ea2e6e`
- 结果：`completed`；plan `7/7`；generator `1`；evaluator `1`；rejections `0`；rounds `6`
- 独立复验：`6 passed in 0.00s`
- CLI：`[1.5, 2.5, 3.5]`

### 最终 Triad B

- 工作目录：`/tmp/forgeagent-m22-final-b.9AQSVX`
- collaboration id：`4bd72d22e25a44458582188640d9600e`
- 结果：`completed`；plan `8/8`；generator `2`；evaluator `2`；rejections `1`；rounds `13`
- 独立复验：`6 passed in 0.00s`
- CLI：`[1.5, 2.5, 3.5]`

Triad B 额外验证了真实 reject -> Generator 修正 -> 新 Candidate -> Evaluator pass 的闭环。两次运行
均未以 `invalid_role_submission` 结束，也没有重复消费已持久 verdict。

## 代码审查

标准独立审查范围为 base-ref `1ba638b7fce626908e3dfe79cc9baf4f15a705c4` 到最终 diff，
只检查正确性、安全和边界条件。首次审查发现 1 个 IMPORTANT：CollaborationStore 的 revision
CAS 仅受单 Store `threading.RLock` 保护，两个 Store/恢复进程可能同时提交同一旧 revision。

修复复用 Loop checkpoint 的 per-ID POSIX `flock`：create 存在性检查和 save 的
load/compare/replace 均处于同一跨进程临界区；锁文件使用 directory fd、`O_NOFOLLOW`、regular
file 校验与 `0o600`，锁缺失或失败时 fail closed。TDD 先稳定复现两个 Store 均成功，再得到一成功
一 stale；补充并发 create、symlink lock、flock failure 和 fcntl missing 测试。复审结论为原
IMPORTANT 已关闭，无新增 Critical/Important；残余风险仅为文档已声明的 advisory/local-filesystem
限制和忽略锁的 hostile writer。

## 已知配置边界

协作 Evaluator 需要读取候选文件。若用户显式把 `tool_result_max_tokens` 设置得极低（本机原配置为
40），即使短文件也可能被截断，真实模型可能保守拒绝正确 Candidate。运行时仍尊重用户配置，
本 change 不静默覆盖该限制；人类验收通过隔离配置验证协议本身。推荐真实 Triad 验收至少为短源文件
保留约 2K tool result tokens 和 4K round feedback tokens。

## 最终评估

当前没有未解决的 CRITICAL、IMPORTANT、WARNING 或 SUGGESTION 级实现偏差。可由 Comet guard
推进到 verify/archive。

分支收尾选择保留 `codex/feature/20260725/fix-collaboration-role-protocol`，不执行本地合并、推送
或 PR，避免扩大当前任务的外部状态变更范围。Comet 的自动 build/verify 推断不支持 uv/Python，
因此 guard 使用 `COMET_SKIP_BUILD=1` 跳过不适用的 npm/maven/cargo 推断；实际验证仍以本报告
记录的 ruff、完整 pytest、严格 OpenSpec 和真实模型 Triad 结果为准。
