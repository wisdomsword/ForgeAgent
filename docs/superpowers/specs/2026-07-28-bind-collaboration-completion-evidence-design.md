---
comet_change: bind-collaboration-completion-evidence
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-28-bind-collaboration-completion-evidence
status: final
---

# M26 协作完成证据绑定技术设计

## 1. 设计目标

M26 修复 Duo/Triad 的 false completion 路径：当宿主注册冻结检查时，Evaluator 不能仅凭模型自报的逐项 `pass` 让协作进入 `completed`。全通过 verdict 必须同时具备当前 Candidate 的全部冻结检查通过证据。

设计保持以下边界：

- 检查 ID、Python argv、环境、超时和输出上限继续由宿主冻结。
- Evaluator 仍只有只读文件工具、`RunCheck` 和 `SubmitEvaluation`，没有写工具或普通 `Exec`。
- `CollaborationState` schema 不变；恢复时重新检查，不持久化进程内证据。
- 未注册检查的协作与 single 模式保持兼容。
- 不调整 M27 负责的协作模式路由。

## 2. 当前失败路径

当前一次 Evaluator Task 的数据流是：

```text
Candidate submitted
        |
        v
build_evaluator_registry
  | RunCheckTool --------> run_check --------> ToolOutcome feedback only
  |
  ` SubmitEvaluationTool -> validate frozen plan IDs -> persist verdict
```

`RunCheckTool` 和 `SubmitEvaluationTool` 没有可信共享状态。模型可以跳过 `RunCheck`、忽略失败结果，或根据旧轮次描述提交所有项目通过；`SubmitEvaluationTool` 只验证计划 ID 覆盖，因此会保存全通过 verdict。

## 3. 选定架构

### 3.1 单次 Evaluator 私有证据表

`build_evaluator_registry` 为每次待验收 Candidate 创建一个普通私有映射，并将同一实例传给两个工具：

```text
build_evaluator_registry(state.generator_attempts, checks)
        |
        +--> RunCheckTool --------+
        |                         |
        |                    evidence[check_id]
        |                         |
        `--> SubmitEvaluationTool-+
```

每条记录只需要：

- `status`：宿主 `run_check` 的稳定状态；
- `snapshot_digest`：实际临时项目副本的摘要；
- `generator_attempt`：构造 registry 时冻结的当前 attempt。

模型的 `RunCheckArgs` 仍只有 `check_id`，`SubmitEvaluationArgs` 仍只有逐项结果。证据表没有协议字段，模型不能伪造或覆盖。

证据表生命周期与 Evaluator Task 相同：

- 同一 Task 内重复运行同一检查，最新宿主结果覆盖旧结果；
- 新 Generator attempt 构造新 registry，证据为空；
- evaluator phase 空 verdict 恢复时构造新 registry，证据为空；
- verdict 成功保存后沿用现有恢复逻辑，不重复模型或检查。

### 3.2 Candidate 快照摘要

检查 runner 在 `shutil.copytree` 完成后、创建 `.check-tmp` 和启动 worker 前，对临时项目副本计算 SHA-256。摘要算法与复制规则共享 `_ignored` 判定，按相对 POSIX 路径排序并编码：

```text
directory marker + relative path + permission mode
file marker      + relative path + permission mode + byte length + bytes
```

摘要包含空目录、文件名、目录名、权限模式和文件内容；忽略 `.git`、`.forgeagent`、虚拟环境、构建/缓存目录和 `*.pyc`。mtime 不属于 Candidate 语义，不纳入摘要。

`CheckResult` 增加默认排除序列化的宿主字段 `snapshot_digest`。`RunCheckTool` 的模型反馈继续只包含 check ID、状态、退出码、耗时、stdout 和 stderr，不展示摘要。为提交时复核，check runner 提供同域函数对当前 allowed root 计算相同摘要；异常统一使全通过门失败。

计算临时副本而不是复制前宿主目录摘要，可确保记录的是实际检查输入。提交前再计算当前目录摘要，可检测检查之间或检查后的正常 Candidate 变化。

### 3.3 全通过门算法

`SubmitEvaluationTool` 先沿用当前的模型校验、脱敏和冻结计划 ID 排序。若任一验收项失败，直接走现有保存路径，不要求检查证据。

若全部验收项通过且宿主注册了检查，则按以下顺序验证：

1. 当前 `ToolContext` 可用，allowed root 可安全计算摘要；
2. 每个冻结检查 ID 都有证据；
3. 每条证据的 attempt 等于当前 state 的 `generator_attempts`；
4. 每条证据状态都是 `passed` 且摘要非空；
5. 全部检查摘要完全相同；
6. 该摘要等于提交时当前 Candidate 摘要。

任一步失败都返回可恢复、长度有界的固定分类反馈，例如缺失检查 ID、未通过检查 ID或“Candidate changed; rerun all checks”。失败不得调用 store.save，不得递增 `evaluator_attempts`，当前 Task 可以在剩余轮次重跑检查后再次提交。

所有条件满足后才沿用当前 revision-checked 保存逻辑。Runner 仍是最终 pass/reject 与协作终态的唯一决策者。

### 3.4 审计

`RunCheckTool` 在每次已注册检查结束后发出 `collaboration.check`：

- `task_id` 和 `operation_id` 沿用当前 ToolContext；
- `attempt` 使用当前 Generator attempt；
- parameters 只包含 `check_id` 和 `generator_attempt`；
- `result_status` 使用稳定 CheckStatus；
- `duration_ms` 使用检查结果。

事件不包含 argv、allowed root、文件内容、stdout/stderr、secret 或快照摘要。Step 现有 `tool.operation` 事件继续提供工具级成功/失败视图。

## 4. 方案比较

### 方案 A：持久化检查证据

优点是恢复时可能少跑检查；缺点是必须迁移协作状态、处理部分结果与并发 revision，并且恢复后仍无法证明旧环境和当前文件树一致。复杂度增加却不能建立可靠证明，不采用。

### 方案 B：在提交工具内自动运行全部检查

优点是调用面较少；缺点是提交变成长耗时操作，模型不能先看到检查失败并形成准确拒绝证据，也不利于取消和逐项重试。不采用。

### 方案 C：单次 Task 私有证据表并绑定快照

改动集中在现有 check runner 和 evaluator registry，不改变持久状态与协议面；恢复天然 fail closed，模型仍可显式运行检查并利用反馈。采用该方案。

## 5. 错误与边界处理

- 未知检查 ID：不启动进程、不写证据，沿用现有结构化失败。
- `copy_error`/`start_error`/`failed`/`timeout`/`cancelled`：记录最新稳定状态；全通过门拒绝。
- 摘要计算失败或项目出现符号链接/特殊文件：按 Candidate 证据不可验证处理，不泄露宿主路径。
- 多个检查对应不同摘要：要求在稳定快照上重跑全部检查，不能只补跑一个。
- 检查通过后只修改忽略目录：摘要不变，不使证据失效；这些目录本来不进入检查副本。
- 检查本身修改临时副本：证据绑定检查启动前的输入摘要；临时修改在目录销毁时丢弃，不影响 Candidate。
- 外部进程持续修改项目：可能导致反复失效，这是预期 fail-closed；不把应用层摘要声明为事务安全边界。

## 6. 测试设计

### 6.1 check runner

- 相同树摘要稳定；文件内容、路径、空目录或权限变化会改变摘要；忽略项变化不影响摘要。
- 符号链接和特殊文件继续失败。
- 成功、失败、超时、取消结果在已复制时携带宿主摘要，但序列化结果不包含摘要。

### 6.2 evaluator tools

- 注册检查但未运行时拒绝全通过，列出有界缺失 ID。
- failed/timeout/cancelled/error 证据拒绝全通过，模型参数不能伪造状态或摘要。
- 多检查同一快照全部通过时允许保存；摘要不一致或提交前 Candidate 变化时拒绝且状态 revision/attempt 不变。
- 至少一个验收项失败时可不运行检查而保存拒绝 verdict。
- 未配置检查时保持现有 `SubmitEvaluation` 行为和 registry 工具集。
- 审计事件只含允许字段。

### 6.3 runner 与恢复

- evaluator phase 空 verdict 恢复后必须重新运行检查。
- 第一次 Candidate 被拒绝后，新的 Generator attempt 不复用旧证据。
- 全部检查和验收通过时 Runner 才返回 completed；失败门不会被角色完成声明绕过。

### 6.4 里程碑验证

依次运行目标测试、完整 pytest、ruff check/format、mypy、离线 build、OpenSpec strict。最后使用独立 M26 目录执行少量真实 Duo/Triad 任务，至少包含一个会被检查证据阻止的伪完成场景和一个真实通过场景；不修改 M23/M25 证据。

## 7. 实施顺序

1. 先为摘要和完成门增加失败测试。
2. 实现 check runner 摘要与非序列化宿主字段。
3. 实现私有证据记录、RunCheck 写入和安全审计。
4. 实现 SubmitEvaluation 全通过门及恢复兼容。
5. 完成 Runner 集成测试、全量验证和真实 M26 验证。

## 8. 双重设计审查结果

第一轮从验收场景反推数据流，确认未运行、失败、旧 attempt、恢复、跨检查变化和提交前变化均有明确拒绝路径。第二轮专查过度设计与兼容性，删除了持久化 schema、自动检查和通用证据框架，只保留一个领域摘要函数与私有证据记录；无检查路径、失败 verdict 和既有 Runner 责任边界保持不变。

