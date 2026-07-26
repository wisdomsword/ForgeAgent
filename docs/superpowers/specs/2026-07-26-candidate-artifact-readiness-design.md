---
comet_change: enforce-candidate-artifact-readiness
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-26-enforce-candidate-artifact-readiness
status: final
---

# Candidate Artifact Readiness 技术设计

## 1. 问题与事实

M22 真实 Triad 人类冒烟在提示词加固后仍出现同一失败：Generator 连续三次在工作目录只有 `.forgeagent` 时成功调用零载荷 `SubmitCandidate`，Evaluator 三次独立确认 `calc.py` 和 `test_calc.py` 不存在，最终 `rejection_limit`。持久状态的 `generator_attempts=3`、`evaluator_attempts=3` 和 `rejections=2` 证明问题不是解析、Evaluator 可见性或状态恢复，而是 Candidate 提交边界允许“无候选产物”的合法状态。

`SubmitCandidate` 现有原子语义必须保留：成功调用才将 phase 切到 evaluator、递增 Generator attempt 并清空旧 verdict。修复需要在该成功边界前加入默认关闭、宿主可验证的最小就绪条件，而不是继续依赖模型遵循提示词。

## 2. 目标与边界

目标：宿主可为一次 Runner 冻结零个或多个顶层 Candidate 文件名。配置非空时，所有文件必须在 allowed root 下成为非符号链接普通文件，`SubmitCandidate` 才能执行现有原子状态变更。失败留在同一个 Generator Task，模型可以根据工具反馈执行 `FileWrite` 后重试。

明确不做：不改变零载荷协议；不让 Generator提交 manifest、路径证据或验收结果；不读取文件内容、检查非空、解析 Python、运行 pytest 或判断正确性；不新增持久字段、公开 CLI 参数、Evaluator 权限或快照机制；不改变默认 single、Duo、Triad、Loop、HTTP 行为。

## 3. 方案选择

### 3.1 采用宿主冻结文件名列表

新增内部配置 `required_candidate_files: tuple[str, ...] = ()`，沿 `run_collaboration_once` → `CollaborationRunner` → `build_generator_registry` → `SubmitCandidateTool` 传递。空元组直接跳过文件检查。

未采用方案：

1. 继续加固提示词。真实模型已在三次运行中证明这不是可靠边界。
2. 给 `SubmitCandidate` 增加 manifest/证据。它破坏零载荷合同，使 Generator 生成非权威验收输入，并与 Evaluator 职责重叠。
3. 根据 FileWrite 历史或目录变化自动推断 Candidate。活动记录不能可靠表达目标产物，且部分写入、回滚和 Exec 写入都会产生歧义。

### 3.2 配置规范化

内部规范化函数接受 list/tuple，输出 tuple。约束：最多 16 项；每项必须是 1-128 字符 ASCII 名字，首字符为字母或数字，其余仅允许字母、数字、`.`、`_`、`-`；拒绝重复、`.`、`..`、路径分隔符、绝对路径和控制字符。该范围足以覆盖人类冒烟的固定顶层文件，并避免引入递归路径安全复杂度。

CLI 私有环境 `FORGEAGENT_INTERNAL_CANDIDATE_REQUIRED_FILES_JSON` 仅接受 JSON array。解析、递归深度或结构错误统一为稳定配置错误，不回显原始值。Runner/工具边界再次规范化，防止嵌入调用绕过 CLI。

### 3.3 安全文件就绪检查

当要求非空时，工具从 `ctx.allowed_root` 的物理路径打开目录描述符：

1. 要求平台提供 `O_NOFOLLOW` 和 `O_DIRECTORY`，以 `O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC` 打开 root。
2. 保存 root `fstat` 的 device/inode；每个顶层名字使用 `os.open(..., dir_fd=root_fd, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)`。
3. 对目标描述符执行 `fstat`，只有 `stat.S_ISREG` 才算就绪；符号链接、目录、缺失、权限失败与其他 `OSError` 都算未就绪。
4. 检查前后用 root 路径 `stat(follow_symlinks=False)` 对比 device/inode，防止 project root 重绑定。
5. 关闭所有描述符；返回按冻结顺序排列的未就绪安全相对名。

该检查只读取元数据，不读取内容。即使文件在检查后被改写或删除，Evaluator 仍对之后的实际状态负责；本设计不声称 Candidate 被快照或冻结。

### 3.4 提交和恢复语义

`SubmitCandidateTool.run` 先执行既有 args/phase/revision 检查，再执行文件门禁，最后才调用 store CAS 保存。门禁失败返回 `ToolOutcome(tool="SubmitCandidate", success=False, detail="required candidate files are missing or unsafe: ...")`。Step 已有通用行为会把失败 outcome 放入下一轮反馈，因此无需修改 Step、required completion recovery 或 Runner 失败映射。

失败时不写 state，所以 `generator_attempts`、phase、旧 `last_evaluation`、rejections 和 revision 保持原值。文件就绪后，同一工具实例重试并沿用现有原子提交。未配置要求时，代码不访问文件系统，兼容现有调用和恢复。

## 4. M22 接线与人工确认

人类冒烟脚本在构造 ForgeAgent 子进程环境时注入：

```json
["calc.py", "test_calc.py"]
```

它与已有 context-budget 私有覆盖一样仅作用于该子进程，不写用户配置。CLI `run` 路径加载后传给 `run_collaboration_once`。Planner 确认流程不变；restricted `FileWrite` 仍使用原 confirmer，所以模型在收到缺失文件反馈后创建文件时，用户仍逐项决定是否批准。脚本外普通 CLI 没有该环境时默认行为完全不变。

## 5. 错误与安全边界

- 非法私有配置在角色或模型调用前失败，使用固定错误，不泄露环境内容。
- 已冻结文件名本身是有界安全 ASCII，因此工具反馈可以列出名字；不包含绝对 root、内容或 credential。
- 无安全 open flags、root 打不开或绑定改变时 fail closed，所有要求项按未就绪处理。
- 符号链接即使指向 root 内普通文件也不满足要求；避免链接跟随和边界竞态。
- 默认空配置不执行新增检查，因此不改变未使用该能力的性能和故障面。

## 6. 测试设计

### 6.1 SubmitCandidate 单元合同

- 要求两个缺失文件时 outcome 失败，detail 精确列名，持久 state 完全相等。
- 创建第一个普通文件后只报告第二个；两者均为普通文件后成功提交，attempt 恰好增加一次。
- 同名目录、指向普通文件的符号链接均被拒绝。
- 默认工具不配置要求时，空目录仍沿用既有成功语义。
- 非法、重复、超数量和路径式配置在构造边界被拒绝。

### 6.2 CLI 与脚本接线

- 私有环境缺省返回空 tuple；合法 JSON 规范化；无效 JSON、非数组、重复/不安全名字返回同一稳定配置错误且不含原值。
- CLI `run` 将要求传到 `run_collaboration_once`，其他公开参数不变。
- M22 `run_smoke` 的 fake subprocess 观察到 context budget 和固定候选文件两个私有环境值；测试继续证明 stdin/人工确认未被脚本预填。

### 6.3 回归门

运行协作工具/Runner/CLI/M22 定向测试，随后完整 pytest、Ruff check/format check、sdist+wheel build、所有 OpenSpec strict 验证和 `git diff --check`。标准代码审查发现的问题先修复再复验。真实模型 PASS 仍需要用户执行一键脚本并批准 Planner/FileWrite，自动回归只证明空 Candidate 不能再成功提交。

## 7. 两轮自审结论

第一轮检查职责与兼容性：门禁只表达 Candidate 是否存在最小载体，没有提供或判断验收证据；Evaluator 完成权不变。默认空配置让 single、未配置协作、Loop 和 HTTP 不受影响。

第二轮检查竞态与恢复：文件可能在门禁后变化，但 Evaluator 会观察实际状态；失败 Submit 不递增 attempt、不消耗 rejection，且由现有 Step 反馈环在同一 Generator Task 恢复。方案没有依赖新的持久状态推断，也没有扩大权限。
