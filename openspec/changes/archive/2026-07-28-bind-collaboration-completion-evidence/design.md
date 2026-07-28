## Context

当前 Evaluator registry 会为一次待验收 Candidate 同时注册 `RunCheck` 和 `SubmitEvaluation`，但两者没有共享的可信状态。`RunCheck` 只把检查输出反馈给模型，`SubmitEvaluation` 只验证冻结计划 ID，因此模型可以不运行检查、忽略失败检查或复用旧检查描述后提交全通过 verdict。协作状态可以在 evaluator phase 恢复，这要求证据语义既能绑定当前 Generator attempt，又不能把不可验证的进程内执行结果错误复用到恢复后的 Task。

约束包括：检查命令和参数继续由宿主冻结；Evaluator 不获得写工具；检查仍在临时项目副本中运行；输出必须有界且脱敏；无检查配置保持兼容；不新增依赖或通用命令面。

## Goals / Non-Goals

**Goals:**

- 只有当前 Candidate 的全部宿主冻结检查通过且全部冻结验收项通过时，才允许提交全通过 verdict。
- 检查证据同时绑定当前 Generator attempt 与实际被检查的项目快照。
- Candidate 在检查后变化时使旧证据失效，并给 Evaluator 可恢复的结构化反馈。
- 恢复时 fail closed：不持久化或复用无法证明仍对应当前执行环境的旧检查证据。
- 保持提前拒绝、无检查兼容、隔离执行和脱敏审计语义。

**Non-Goals:**

- 不调整编程任务的 single/duo/triad 默认路由，该项留给 M27。
- 不重写 M23/M25 历史评测或把旧结果重新分类。
- 不引入任意命令执行、Evaluator 写能力、新依赖或通用证据框架。
- 不保证对拥有宿主文件系统写权限的恶意并发进程提供事务级文件快照；本变更保证检测正常的 Candidate 变更并 fail closed。

## Decisions

### 1. 在单次 Evaluator registry 内共享最小检查证据表

`build_evaluator_registry` 为当前待验收 Candidate 创建一份仅宿主持有的内存证据表，并将同一实例交给 `RunCheckTool` 与 `SubmitEvaluationTool`。`RunCheckTool` 只按冻结 ID 执行检查并覆盖该 ID 的最新结果；模型不能提交状态、摘要、命令或证据字段。

证据表的生命周期等于当前 Evaluator Task。新的 Generator attempt、进程恢复或重新构造 registry 都从空证据开始，因此旧 attempt 的结果不能被复用。

备选方案是把证据写入 `CollaborationState`。该方案会增加 schema、迁移、并发保存和恢复时环境一致性问题，而恢复后仍需要重新确认代码与解释器环境，持久化并不能安全省略重跑，因此不采用。

### 2. 用项目快照摘要绑定检查实际输入

检查 runner 在临时副本创建后，对与复制规则一致的非忽略文件树计算确定性 SHA-256 摘要，并把摘要作为仅供宿主门禁使用的结果元数据返回；Evaluator 反馈不展示摘要。一次全通过提交前，`SubmitEvaluationTool` 重新计算当前 allowed root 的同规则摘要。

所有要求检查的最新结果必须为 `passed`，必须具有同一摘要，且该摘要必须等于提交时的当前摘要。检查之间或检查后发生文件变化时，旧结果会因摘要不一致而失效，Evaluator 必须在当前快照上重新运行全部检查。

备选方案是在检查前后各计算宿主目录摘要而不绑定临时副本。该方案存在检查复制发生在两个摘要之间的歧义，不能证明实际执行输入，故不采用。另一个备选方案是让所有检查共享一个长期临时副本，会扩大 runner 生命周期和清理复杂度，M26 不需要。

### 3. 证据门只约束全通过 verdict

当 Evaluator 提交的任一冻结计划项为失败时，`SubmitEvaluation` 继续允许保存拒绝 verdict，不要求先运行所有检查。这保留了通过只读观察即可提前拒绝明显缺失或错误 Candidate 的能力。

当所有计划项均为通过时，存在冻结检查配置就必须通过证据门；缺失、失败、超时、取消、复制错误、启动错误、摘要缺失或摘要过期均返回结构化失败，且不保存 verdict、不递增 Evaluator attempt。没有冻结检查时沿用当前行为。

备选方案是在 `SubmitEvaluation` 内自动运行全部检查。该方案会隐藏检查成本，弱化模型根据检查反馈定位问题的能力，并把提交工具变成不可控的长操作，因此不采用。

### 4. 恢复时重新取得证据，不持久化执行结果

协作状态继续只持久化 Candidate attempt 和最终 verdict。若从 evaluator phase 且 verdict 为空恢复，Runner 构造新的空证据 registry，Evaluator 必须重新运行检查。若 verdict 已经成功保存，现有恢复逻辑直接处理 verdict；因为保存前已通过证据门，不需要重复运行模型或检查。

该选择保持状态 schema 兼容，也明确避免把旧进程、旧环境或中断前的部分检查误当作当前证据。

### 5. 审计只记录安全的检查元数据

每次合法冻结检查执行额外发出结构化协作检查事件，仅记录 check ID、当前 Generator attempt、稳定状态和耗时；不记录 argv、绝对路径、文件内容、完整输出或快照摘要。现有 `tool.operation` 事件继续记录工具级成功/失败。

## Risks / Trade-offs

- **[大型项目摘要增加 I/O]** → 检查本身已经复制完整非忽略项目树；摘要复用相同范围，仅在检查和全通过提交时计算，不引入后台扫描或缓存。
- **[正常外部写入使已通过检查失效]** → 这是预期的 fail-closed 行为；反馈明确要求在稳定的当前快照上重跑检查。
- **[宿主级恶意并发写仍可能制造 TOCTOU]** → M26 不把应用层摘要升级为文件系统事务或安全边界；检查隔离和 allowed root 约束保持不变，并通过前后快照一致性覆盖正常变更。
- **[恢复后重复检查增加成本]** → 以可证明的完成完整性优先于复用不可靠证据；现有检查有冻结超时，成本有界。

## Migration Plan

1. 先增加快照摘要和证据门的失败测试，再实现最小运行时改动。
2. 保持 `CollaborationState` schema 和无检查路径不变，因此无需数据迁移。
3. 通过单元、恢复、并发、完整测试和 M26 小规模真实协作验证后归档 delta spec。
4. 如需回滚，可回退 M26 运行时改动；既有持久状态仍可由旧版本读取。

## Open Questions

无。M27 的模式路由校准和未来是否持久化可验证执行证明均不属于本变更。
