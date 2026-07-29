## ADDED Requirements

### Requirement: M25 派生分析保持冻结输入不可变
M27 派生分析 MUST 只读取冻结的 M25 protocol、terminal raw、environment、summary 和原报告，MUST 将新结果写入独立的 M27 派生目录，且 MUST NOT 修改、覆盖或重跑任何 M25 冻结输入。

#### Scenario: 生成 M27 派生报告
- **WHEN** 分析脚本针对冻结 M25 证据成功运行
- **THEN** 它生成新的机器可读投影和 Markdown 报告，而 M25 原 protocol、raw、environment、summary 与报告保持不变

#### Scenario: 冻结输入不完整或不一致
- **WHEN** M25 记录缺失、身份重复、字段类型无效或与冻结 summary 不一致
- **THEN** 派生分析非零退出且不得发布看似完整的结果

### Requirement: 误完成率与终止原因可复算
派生分析 MUST 将 `runtime_completed == true` 且 `solved == false` 定义为误完成，并 MUST 同时以全部调度运行和 runtime-completed 运行作为分母报告误完成率。终止原因 MUST 按原始稳定 `runtime_reason` 精确分类，不得主观合并不同原因。

#### Scenario: runtime 完成但任务未解决
- **WHEN** terminal raw 记录的 `runtime_completed` 为 true 且 `solved` 为 false
- **THEN** 该记录计入一次误完成，并进入两个明确标注分母的比率

#### Scenario: runtime 未完成
- **WHEN** terminal raw 记录的 `runtime_completed` 为 false
- **THEN** 该记录不计为误完成，但其 `runtime_reason` 仍进入终止原因分类

### Requirement: 路由决策比较质量、延迟与调用成本
派生分析 MUST 至少按 model/mode 与 task-family/mode 汇总 scheduled、runtime-completed、solved、误完成、`runtime_reason`、逻辑模型调用、provider attempts、延迟和 token 指标。自动 Triad 任务类别只有在冻结证据中 Triad solved rate 严格高于 Single 时才可进入恢复评估；未满足该质量门时 MUST 保持 Single 默认，并报告延迟和调用成本差异。

#### Scenario: 没有任务类别提高 solved rate
- **WHEN** 每个任务类别的 Triad solved rate 均低于或等于 Single
- **THEN** M27 不恢复任何任务类别的自动 Triad，并保留显式 Triad 与宿主冻结检查 Triad

#### Scenario: 历史证据早于 M26 绑定
- **WHEN** 报告解释 M25 的误完成与终止数据
- **THEN** 它明确标注 M25 早于 M26 冻结检查绑定，不把该结果表述为当前 evidence-bound Triad 的质量证明
