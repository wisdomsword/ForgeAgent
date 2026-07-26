---
comet_change: m23-collaboration-mode-evaluation
role: technical-design
canonical_spec: openspec
---

# M23 Single/Duo/Triad 质量—成本评估技术设计

## 1. 目标与边界

M23 交付一个只存在于仓库评估层的可复现 harness。它在相同条件下多轮运行 Single、Duo、Triad，保存逐次机器记录并生成描述性聚合报告。OpenSpec delta spec 是需求事实源；本文细化实现接口、数据结构、运行顺序、错误处理和测试。

严格不修改：

- `src/forgeagent/collaboration.py` 的状态机、角色提示词和报告合同；
- `src/forgeagent/cli.py` 的产品命令或参数；
- model registry 的 credential 解析、配置回退和密钥来源；
- memory、identity、skills、MCP 或 evaluator 能力。

## 2. 文件与职责

### `docs/evaluation/m23/protocol.json`

唯一的运行协议，使用 `schema: forgeagent.m23.mode-evaluation/v1`。它固定模型、生成参数、运行限制、重复次数、轮换顺序和任务。任务项包括：

- 稳定 `id` 和英文 `goal`；
- 初始文件映射；
- `required_candidate_files`；
- 外部检查的参数数组；
- 被检查产物列表。

检查器不接受任意 shell 字符串。v1 只支持参数数组形式的 `command`，以工作区为 `cwd`，固定超时，`shell=False`。协议解析拒绝绝对路径、`..`、控制字符、未知键、重复任务 ID、少于三次重复、非三模式排列和不完整 schedule。

### `scripts/m23_mode_evaluation.py`

单文件脚本保持评估逻辑与产品包隔离，但内部按职责分成纯函数：

1. `load_protocol` / `validate_protocol`：加载、严格校验并计算 canonical JSON SHA-256。
2. `build_schedule`：按 task → repeat → 对应轮换顺序生成 27 个稳定 `RunSpec`。
3. `environment_manifest`：记录 git commit、dirty flag、Python、平台、ForgeAgent 版本、模型 ID、内置 registry 哈希和固定运行设置。
4. `prepare_workspace`：创建新的临时目录并写入协议夹具；拒绝任何逃逸路径。
5. `run_single` / `run_collaboration`：仅负责组装公开对象和返回模式投影。
6. `project_audit_metrics`：从内存 audit 事件计算调用和 usage。
7. `run_checks` / `hash_artifacts`：执行同一模式外检查并记录有界输出和 SHA-256。
8. `write_raw_record`：同目录临时文件 + `os.replace` 原子写入。
9. `aggregate_records` / `render_report`：只从 raw JSON 复算汇总，不读取运行时状态或模型输出。

CLI 仅提供 `run` 和 `aggregate`：

```text
python scripts/m23_mode_evaluation.py run \
  --protocol docs/evaluation/m23/protocol.json \
  --output docs/evaluation/m23/runs/2026-07-27-haiku-4-5

python scripts/m23_mode_evaluation.py aggregate \
  --protocol docs/evaluation/m23/protocol.json \
  --output docs/evaluation/m23/runs/2026-07-27-haiku-4-5
```

`run` 支持检测已存在且协议/RunSpec 哈希一致的 raw 文件并跳过，便于安全续跑；不提供改变模型、参数、任务或重复次数的命令行覆盖。

## 3. 固定运行组装

### 公共设置

- `model_id`: `claude-haiku-4-5`，所有角色相同；该字面值直接作为 provider model 字段。
- `GenerationParams(max_output_tokens=4096, temperature=0.0, thinking="off", effort=None, timeout_seconds=120.0)`。
- `tier="restricted"`、`max_rounds=10`、`max_rejections=2`。
- `ApprovedIdentity(soul=None, user=None, project_agents=None, memory=None)`；不创建 MemoryManager、SkillRegistry 或 MCPManager。
- 每个 Task 使用新的 real client 和同一 `CollectingAuditSink`；任务结束后始终 `close()`。
- 文件确认器仅返回 `True`；实际可写边界仍由 restricted backend 和临时 `allowed_root` 强制。

### Single

创建一个 `Task`，传入固定 params、临时根目录、零内容 identity、audit sink 和稳定 task ID，调用 `Task.run(goal)`。运行状态取 `outcome.status.completed`，round 数取 `len(outcome.rounds)`。

### Duo/Triad

`role_task_builder(role, attempt, registry, system_prompt)` 每次创建新的 client 和 Task，并原样使用 runner 提供的 registry/system prompt。`CollaborationRunner.create` 接收：

- mode、goal、allowed_root 和 role builder；
- Triad 使用 `headless_plan_confirmer("preauthorize")`；
- 三个 role model 字段均为固定 model ID；
- `required_candidate_files` 来自任务协议；
- `execution_tier="restricted"`、`evaluator_tier="restricted"`、固定 max_rejections；
- 不传 `evaluator_checks`，避免只给协作模式额外验证能力。

运行状态、Generator/Evaluator attempts、rejections 和 rounds 从 `CollaborationReport` 投影。`first_acceptance_passed` 定义为 completed 且 `generator_attempts == 1`、`evaluator_attempts == 1`、`rejections == 0`。`correction_count=max(0, generator_attempts-1)`；Single 三个验收循环字段均为 `null`。

## 4. 任务与顺序

协议包含三个小型、确定性、无网络任务：

1. `csv-region-summary`：读取固定 CSV，创建标准库脚本和规范 JSON 汇总；检查脚本退出码与精确 JSON。
2. `fix-range-compression`：修复已有 Python 函数的边界错误并保持公开签名；检查固定 pytest 文件。
3. `normalize-events`：读取固定事件 JSON，创建确定排序/去重输出；检查标准库验证脚本和精确产物。

每个任务重复三次。轮换顺序固定为：

```text
repeat 1: single, duo, triad
repeat 2: duo, triad, single
repeat 3: triad, single, duo
```

总运行数严格为 27。运行串行执行，保证同一时刻只有一个模式消耗模型服务和主机资源。

## 5. 原始记录合同

每个 `raw/NN-task-rN-mode.json` 包含：

- schema、run ID、sequence、task/mode/repeat；
- protocol SHA-256、environment manifest SHA-256 和开始/结束 UTC 时间；
- runtime completed/status/reason、external checks、`solved`；
- first acceptance/rejection/correction 的适用值；
- 四类 token 总计、logical model calls、provider attempts、usage present/missing calls 和 missing rate；
- end-to-end latency；
- 被检查产物的相对路径、大小和 SHA-256；
- 有界、脱敏的错误分类。

禁止字段：goal/prompt/messages/reply/body/text/api_key/base_url/environment。检查 stdout/stderr 仅保留最多 2 KiB，并再次通过现有 secret masker；成功检查默认只存退出码和 SHA-256，不保存正文。

`CollectingAuditSink` 只在内存保留 `AuditEvent` 对象。Provider attempt 只统计 `llm.provider_attempt` 的 `started` 事件，避免把同一次 attempt 的开始与终态重复计数。投影后不会把原始 audit 流写入证据目录。

## 6. 指标与聚合

每个模式都报告原始计数和明确分母：

- `task_completion_rate = solved_runs / scheduled_runs`；
- `first_acceptance_rate = first_acceptance_passed / applicable_collaboration_runs`，Single 为 N/A；
- rejection/correction：sum、mean、median、min、max，Single 为 N/A；
- 四类 token：sum、mean、median、min、max，仅对已知值累加，并并列 missing calls；
- model calls 和 provider attempts：sum、mean、median、min、max；
- end-to-end latency：sum、mean、median、min、max；
- `usage_missing_rate = missing_usage_calls / logical_model_calls`，零调用时为 null。

`summary.json` 不包含 winner、rank、recommendation 或 superiority 字段。`report.md` 固定展示协议、环境、完整性、按模式表格、逐任务表格、失败/usage 缺失清单和限制。结尾固定说明：这些是小样本描述性结果；不自动宣称 Triad 优于 Single，也不据此作产品决策。

## 7. 错误与恢复

- preflight 在首个模型调用前验证协议、输出目录、model capability、credential 可解析和环境清单；不打印 credential 或 base URL。
- 单次运行异常转成稳定错误类别并仍写 raw record，然后继续后续 RunSpec；KeyboardInterrupt 保留已完成记录并退出。
- 外部检查超时或非零退出只使该检查失败，不改变运行时原始状态。
- aggregate 拒绝重复 RunSpec、协议/环境哈希混用、schema 错误或不完整 27 记录；可用 `--allow-incomplete` 生成带醒目标记的诊断报告，但正式 M23 报告禁止该标记。

## 8. 测试与验收

离线测试使用临时协议、fake audit events 和 fake mode results，至少覆盖：

- 严格协议校验和路径逃逸拒绝；
- 27 项顺序与每种模式 9 个样本；
- Single 验收循环字段为 null；
- 内部 completed 但外部失败时 `solved=false`；
- usage 有效/缺失/无调用三种情况；
- 原子原始记录、重复/混合证据拒绝和幂等聚合；
- report 不含排名字段且含中立声明；
- 原始记录不存在禁止字段/敏感值；
- runtime/credential/CLI 文件保持未修改。

真实运行完成后验证 27 份 raw 文件、每种模式 9 份、每个任务/模式 3 次、协议和环境哈希唯一、summary 可复算、报告与 summary 一致。最后运行 ruff、全量 pytest、OpenSpec strict 和 Comet verify。
