---
comet_change: calibrate-collaboration-routing
role: technical-design
canonical_spec: openspec
---

# M27 协作路由校准技术设计

## 1. 设计结论

ForgeAgent 的内置路由从“编程文本自动 Triad”改为三段式确定性规则：用户显式模式优先；可信
宿主绑定非空冻结检查时选择 Triad；其余情况默认 Single。此变化不增加意图分类器或配置面，
并删除不再服务任何决策的私有编程分类器。

M27 另建只读派生管线复算 M25 冻结证据。派生结果增加误完成率与精确终止原因，并比较
Single/Triad 的 solved rate、延迟、逻辑模型调用、provider attempts 和 token。由于冻结 M25 中
没有任务类别的 Triad solved rate 严格高于 Single，M27 不恢复任何类别的自动 Triad。

## 2. 路由设计

### 2.1 数据流

路由输入被限制为：任务 goal、可选显式 mode，以及可信宿主提供的 `has_bound_checks` 布尔事实。
解析顺序为：

```text
explicit mode? ---- yes ---> explicit single/duo/triad
      |
      no
      v
bound checks? ----- yes ---> triad (reason=bound_checks)
      |
      no
      v
single (reason=default)
```

goal 为兼容继续保留，但不再被解析或写入审计。`allow_weaker_override` 同样保留为兼容参数且无
行为作用。这样旧调用方无需同步删除参数，显式 Single/Duo 也不再出现确认分支。

### 2.2 模型与审计

`ModeDecision.reason` 删除 `programming` 与 `override_required` 可生成路径，增加 `bound_checks`。
`override_required` 字段继续保留以维持公开投影与旧 checkpoint 形状，但所有新解析结果均为 false。
路由审计只记录 mode、reason、requested_mode、override_required 和已有 loop/task 标识，不记录
goal 或冻结检查细节。

### 2.3 入口接线

- CLI `run`：显式模式直接执行；无模式编程目标走普通 `run_once`。
- REPL：普通输入不再显示 “programming task” 或自动启动 Planner/Evaluator；`/duo`、`/triad`
  原样执行且不读取覆盖确认。
- HTTP：普通提交不再自动把 options.mode 改成 triad；显式 task/duo/triad 保持原义。
- Loop：未指定协作模式时使用 Single；显式 Duo/Triad 仍由已有 checkpoint 冻结与恢复。
- 可信 library/harness：只有它们掌握并向 runner 注册 CheckDefinition 时，才可把
  `has_bound_checks=True` 交给 resolver。该布尔值不得来自普通任务 options。

## 3. M25 派生分析设计

### 3.1 输入边界

脚本接收冻结 protocol、M25 run 根目录和独立 M27 输出目录。它先调用已有
`m25_independent_recompute.verify_summary` 验证固定调度、270 个唯一 terminal raw、protocol 与
environment hash、solved 推导和 summary 加法总数，再独立读取同一 raw 计算新增指标。

冻结输入集合包括 protocol、environment、summary、原 report 和 270 个 raw JSON。脚本计算由
相对路径与文件 SHA-256 组成的单一 manifest digest，写入派生 JSON。输出路径必须位于冻结 M25
run 根之外；脚本不提供覆盖或重写输入的参数。

### 3.2 指标模型

每个 model/mode 和 family/mode bucket 输出：

- `scheduled_runs`、`runtime_completed_runs`、`solved_runs`；
- `solved_rate`；
- `false_completions`，定义为 runtime completed 且 solved false；
- `false_completion_rate_scheduled` 与 `false_completion_rate_runtime_completed`；
- 按原值排序的 `termination_reasons`；
- logical model calls、provider attempts、端到端延迟与各 token 字段的 sum/mean。

所有 rate 都输出 numerator、denominator 和 value，零分母时 value 为 null。数值字段必须为有限、
非负值；reason 必须是非空字符串；布尔字段必须是严格 bool。失败时脚本非零退出且不先写半成品。
成功时先在内存构造完整结果，再通过临时文件 + replace 原子写 JSON 与 Markdown。

### 3.3 策略裁决

报告逐类别比较 Single 与 Triad 的 solved rate。只有 Triad 严格更高的类别才可列为
`quality_eligible`；M25 的 baseline 持平，其余类别更低，因此
`automatic_triad_restored_for` 为空。调用与延迟结果用于解释成本，不设置任意倍率阈值。

报告必须明确 M25 早于 M26 的 Candidate-bound checks。误完成率反映旧 runtime completion 与
外部 solved 的偏差，不能当作当前 evidence-bound Triad 的验证结果。

## 4. Memory 与平台文档

M27 不改变 Memory 代码。README 应说明项目 `.forgeagent/MEMORY.md` 在 M18 后既可由用户编辑，
也可由 runtime 在准入后原子持久化；`--no-memory` 只关闭 Memory，`--no-identity` 按身份合同同时
关闭 SOUL、USER、AGENTS 与 MEMORY。

Linux 表格不得写成未经证据同时覆盖的 `amd64/arm64`。Pipeline 50 / Job 249 继续证明已记录的
Linux Docker runner topology 为 verified；macOS arm64 + Linux arm64 daemon 仍单列为
supplemental；文末不再称 Linux “仍 configured”。当前基线只在最终命令跑完后写入 README 与
platform-support，并通过合同测试保证一致。

## 5. TDD 与验证矩阵

### 5.1 RED

- 把旧分类器大表测试替换为小型策略矩阵，先断言无模式编程目标为 Single、绑定检查为 Triad、
  显式模式优先且兼容开关无效。
- 修改 REPL/CLI/HTTP/Loop 集成测试，先观察现有自动 Triad 与确认路径失败。
- 新增派生脚本测试，以合成完整证据加入一条 runtime-completed/unsolved 记录，断言双分母与 reason；
  篡改 raw、summary 或输出路径时必须拒绝。
- 扩展文档合同，先断言 Memory 可写语义、Linux tuple 收窄与当前基线一致。

### 5.2 GREEN

只实现使上述合同通过的最小改动：删除分类器、简化 resolver 与确认 helper、添加派生脚本并生成
产物、修正文档。不得顺手重构 collaboration runner、Memory runtime、check runner 或评估 harness。

### 5.3 完成验证

依次运行定向 pytest、全量 pytest、OpenSpec strict、Golden 20/20、Ruff check/format、wheel/sdist
和 `git diff --check`。最终数字写入文档后再次运行文档合同。两轮自审分别检查需求覆盖/证据边界
与行为兼容/遗漏，再执行独立代码评审；确认问题必须修复并复验。

## 6. 失败与回滚

- 路由测试失败：只在 resolver 与对应入口定位，禁止恢复文本分类器作为临时补丁。
- 派生验证失败：不生成报告，先修复输入校验或统计逻辑；冻结 M25 不得为适配脚本而修改。
- 平台证据不充分：进一步收窄公开 claim，不猜测架构。
- 回滚：普通 revert M27 提交即可；M25/M26 冻结树没有迁移步骤。
