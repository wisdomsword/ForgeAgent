## Context

`SubmitCandidate` 是 Generator 的零载荷原子提交边界：成功时切换到 evaluator phase、递增 attempt 并清空旧 verdict。它当前不知道工作目录里是否存在任何候选产物，因此真实模型可以把“没有执行任何 `FileWrite`”的空目录提交给 Evaluator。Evaluator 能准确拒绝，但无法让一个持续忽略提示词的 Generator 改变行为，最终会耗尽拒绝预算。

该问题已经经过三层实证：协作状态显示 `generator_attempts=3`、`evaluator_attempts=3`、`rejections=2`；Evaluator 三次只观察到 `.forgeagent`；Generator rejection prompt 加固后问题仍复现。因此修复必须落在成功提交的宿主边界，而不是继续依赖提示词。

## Goals / Non-Goals

**Goals:**

- 让宿主可选地冻结一组 Candidate 必须具备的顶层普通文件名。
- 在 `SubmitCandidate` 原子状态变更前安全检查这些文件；缺失或不安全时返回可恢复工具失败。
- 保持零载荷 Submit 协议、Evaluator 内容验收独占权、人工确认与默认兼容性。
- 让 M22 人类冒烟的固定任务声明 `calc.py` 和 `test_calc.py`，阻断真实模型空候选提交。

**Non-Goals:**

- 不检查文件内容、大小、语法、测试结果或验收正确性。
- 不新增 manifest、SubmitCandidate 参数、持久状态字段、公开 CLI 参数或通用产物推断。
- 不保证 Submit 后文件不可修改；Evaluator 仍验收当时可观察的实际产物。
- 不改变普通 single、未配置门禁的 Duo/Triad/Loop/HTTP 行为。

## Decisions

### 1. 使用宿主冻结的文件名列表，而不是提示词或 manifest

`required_candidate_files` 是一次 Runner 的宿主配置，默认空元组。它只表达“Candidate 具备最小外部载体”，不携带模型生成的证据，也不进入协作持久状态。M22 脚本通过私有子进程环境 JSON 传入固定列表，CLI 严格解析后装配到本次 Runner；不暴露新的用户命令面。

排除继续加固提示词：真实模型已多次无视同类约束。排除 Generator manifest：它会改变零载荷协议、增加非权威路径数据，并模糊 Evaluator 独占验收职责。排除运行时自动推断文件活动：无法可靠区分部分写入、目标文件和无关副作用。

### 2. 门禁属于 `SubmitCandidateTool`，失败不触碰持久状态

`CollaborationRunner` 把已规范化的文件名传给 generator registry，registry 构造配置化 `SubmitCandidateTool`。工具先验证当前 phase/revision，再检查要求文件；只有全部通过才执行现有 CAS 保存。检查失败返回 `ToolOutcome(success=False)`，Step 会把精确缺失文件反馈给同一个 Generator conversation；phase、attempt、verdict 和 rejection count 均不变。

这保留现有职责边界：Step 仍只理解通用 ToolOutcome，Runner 不识别文件系统细节，Evaluator 仍决定 Candidate 是否满足冻结计划。

### 3. 文件名和文件对象均采用 fail-closed 安全校验

配置最多 16 项，每项是 1-128 字符的 ASCII 顶层安全文件名，只允许字母、数字、点、下划线和连字符；拒绝重复、绝对路径、分隔符、`.`、`..` 与控制字符。CLI 对私有 JSON 使用稳定、无回显的配置错误；Runner/工具边界再次规范化，避免嵌入调用绕过。

提交检查以 allowed root 的目录描述符为锚，使用 `O_NOFOLLOW` 打开每个顶层目标并以 `fstat` 确认普通文件，同时在检查前后验证 root 的 device/inode 绑定。符号链接、目录、缺失、不可安全打开或 root 重绑定均按未就绪处理。反馈只列出已冻结的安全相对文件名，不包含绝对路径或文件内容。

### 4. M22 私有接线不改变人工确认

`scripts/m22-triad-human-smoke.py` 在已有 context-budget 私有环境旁增加候选文件 JSON。Planner 计划仍由终端人工批准；restricted `FileWrite` 仍走现有 confirmer。Generator 若先提交，会在同一 Task 收到“必须先创建 calc.py/test_calc.py”的工具反馈，随后正常调用 FileWrite 时仍会逐项请求人工确认。

## Risks / Trade-offs

- **[模型可能创建空文件再提交]** → 门禁只承诺载体存在；Evaluator 会拒绝内容错误。继续扩大到内容/大小检查会侵占 Evaluator 职责，本 change 不做。
- **[检查与 Evaluator 之间文件可能变化]** → 这是既有共享工作目录语义；门禁不是快照或冻结机制，Evaluator 以实际观察为准。
- **[私有环境被外部设置]** → 该配置只能收紧 Candidate 提交，不扩大权限；严格有界解析且不回显原值。
- **[平台缺少安全 open flags]** → 门禁 fail closed，SubmitCandidate 返回结构化失败；未配置门禁的现有路径不受影响。
- **[额外文件系统检查增加少量延迟]** → 仅配置时执行，最多 16 个顶层 metadata/open 操作，可忽略不计。

## Migration Plan

1. 先增加 RED 测试，证明空候选目前可成功提交及 M22 子进程未注入要求。
2. 实现内部规范化、SubmitCandidate 安全检查与 Runner/CLI 接线。
3. 更新 M22 脚本、文档和 delta specs，运行定向与全量验证。
4. 真实模型验证继续由人工执行一键脚本；本地自动验证不消耗凭证。

回滚只需移除 M22 私有环境注入和可选参数接线；默认空配置本身不改变状态 schema 或持久数据，无迁移步骤。

## Open Questions

无。文件集合、失败语义、兼容边界与验收职责均已在两轮自审中确定。
