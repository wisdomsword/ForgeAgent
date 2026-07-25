---
comet_change: fix-collaboration-role-protocol
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-25-fix-collaboration-role-protocol
status: final
---

# 协作角色结构化提交设计

## 目标与根因

真实模型 M22 Triad 验收证明，提示模型在 Submit 后再发送 standalone completion 不是可靠协议：
Planner 会漏交计划，Generator 会在正确写入产物后因 restricted Exec 文件视图差异重复验证，
Evaluator 也可能跳过 verdict 提交。设计把结构化 Submit 从“工具副作用”提升为角色完成的唯一
确定性边界，同时保留现有 collaboration state schema、角色隔离和 Evaluator 独立验收。

## 状态机与提交协议

Planner 的 `SubmitPlan` 保存冻结计划并进入 `needs_confirmation`。确认后 Generator 开始工作；
零载荷 `SubmitCandidate` 通过 revision CAS 原子执行 `phase=evaluator`、
`generator_attempts+1` 和清空 `last_evaluation`。Evaluator 的 `SubmitEvaluation` 原子写入覆盖
冻结计划的 verdict、执行 `evaluator_attempts+1`，但保持 evaluator phase。Runner 随后独立决定
completed、rejection、rejection limit 或失败终态。

拒绝回到 Generator 时暂时保留旧 verdict，确保崩溃恢复仍能构造拒绝反馈。新 Candidate 成功提交
才清空旧 verdict。因此恢复状态无歧义：generator phase 的 verdict 仅是反馈；evaluator phase 的
空 verdict 表示待验收，非空 verdict 表示当前 Candidate 已有结果并应直接判定。

不增加 Candidate 对象、attempt 关联字段或 schema 版本。phase、attempt 和 verdict 已能完整表达
当前协议。Submit 保存成功但 rounds/usage 边界尚未保存时崩溃，允许丢失未持久化统计，不进行
不可靠推断。

revision CAS 的 load/compare/replace 窗口由每 collaboration ID 的稳定私有 lock file 和 POSIX
`flock(LOCK_EX)` 串行化。create 的存在性检查也位于同一临界区，防止两个 Store/恢复进程同时
创建或提交同一旧 revision。锁文件通过 collaborations directory fd、`O_NOFOLLOW`、regular-file
校验和 `0o600` 保护；锁能力缺失或失败时 fail closed。

## Step 与工具层契约

`ToolOutcome` 增加默认 false 的通用 `completes_task` 信号，沿用 `needs_info` 的既有模式。
Submit 工具只有在状态校验和 CAS 保存成功后才返回 `success=true` 与
`completes_task=true`。Tool 基类接口不变，现有工具无需修改。

Step 按 parser 的确定性输出顺序分派工具：现有双通道协议先追加文本 ToolCall，再追加 provider
原生 tool_calls。Submit 前的调用正常执行；第一个成功的 completion outcome
立即设置 `Termination.COMPLETED` 并停止后续分派。被截断工具没有执行结果，也不生成虚假审计
事件。成功提交优先于同一响应中的 task_status 和非致命解析错误，因为持久提交不能被响应局部
格式问题回滚。Submit 自身失败不终止 Step，具体错误进入反馈供剩余轮次修正。

`ToolRegistry` 显式保存至多一个 required completion tool。Step 从 registry 元数据获取缺失工具
名称，不硬编码 Submit 工具、角色或 collaboration phase。角色第一次声明 completed 但未成功
Submit 时，Step 返回精确恢复提示；同一 Step 第二次违规时终止为 FAILED。该恢复计数属于单个
角色 attempt 的 Step 生命周期，Runner 只把最终结果映射为 `invalid_role_submission`。普通 single
registry 没有 required completion tool，既有完成和 prose recovery 语义不变。

## Runner 边界与恢复

Runner 在角色开始前保留起始 state/revision，并验证成功提交后的 invariant：Planner 必须得到
合法 `needs_confirmation` 计划；Generator 必须进入 evaluator、attempt 恰增一次且 verdict 为空；
Evaluator 必须 attempt 恰增一次且 verdict 按冻结 plan 顺序完整覆盖。

成功 Submit 已负责 attempt 计数，Runner 只补记 rounds/usage。未成功提交而退出的
Generator/Evaluator 仍由 Runner 在失败角色边界计数，避免改变既有失败统计。Runner 始终独占
plan freeze、pass/reject、rejection count、rejection limit、取消和终态转换。

Loop 的 collaboration builder 传入含 Checkpoint 等工具的 registry。Runner 必须在该 registry 上
增加本轮 `SubmitCandidate`，不得用 default registry 覆盖 Loop 工具。普通 Duo/Triad 同理保留
Generator 的 FileWrite、Exec、MCP、Skill 等已授权工具。Evaluator registry 保持只读文件工具、
可选 RunCheck 和 SubmitEvaluation。

## 提示协议

三个角色提示都展示准确文本 ToolCall schema，并说明成功 Submit 即完成，不需要后续 standalone
task_status。Generator 明确使用
`<!-- ToolCall: {"name":"SubmitCandidate","arguments":{}} -->`，并说明它只负责实现和提交，
最终验收属于 Evaluator；不得仅因 restricted Exec 无法观察 FileWrite 宿主文件而重复验证。
任务 JSON、拒绝反馈和文件内容继续按不可信数据处理。

## 排除方案

- 隐式从文件活动判断 ready：无法区分部分写入、回滚和 clean completion。
- Candidate manifest：增加非权威路径与完整性校验，模糊职责。
- Generator 逐项证据或宿主检查：重复 Evaluator 工作并扩大权限和成本。
- Submit 唯一调用或额外 standalone completion：增加真实模型轮次压力。
- Submit 后动态锁写工具：引入新的锁、恢复和测试面。
- 新增 Candidate/evaluation 状态字段：在现有状态已足够时造成迁移负担。

## 测试与验收

Step 单测覆盖 completion signal 默认关闭、文本/原生双通道确定性顺序、成功截断、无后续审计、非致命解析错误、
一次缺失提交恢复、重复违规失败和 single 兼容。工具测试覆盖三个 Submit 的成功原子状态、错误
phase、stale revision、重复提交与完整 verdict。Runner 测试覆盖 attempt 不双计、失败计数、
pass/reject/rejection limit、三条恢复路径、冻结 plan 和稳定失败原因。模式测试覆盖 Duo、Triad、
Loop duo/triad、single、Loop single；安全回归覆盖 allowed root、Evaluator 只读、secret masking
和审计边界；存储回归覆盖两个独立 Store 的同 revision 重叠提交、重叠 create、symlink lock、
flock 失败与缺失平台锁。

自动测试、ruff 和完整 pytest 通过后，在两个全新临时目录连续运行真实模型 Triad。每次必须
completed，三个角色均结构化提交，外部 pytest 通过，且
`python calc.py '[1,2,3,4]' 2` 精确输出 `[1.5,2.5,3.5]`；不得出现
`invalid_role_submission`、Submit 后写入或重复 Evaluator。

## 两轮设计自审

第一轮检查协议闭环，确认 Submit 保存、Step 终止、Runner invariant 和恢复状态之间没有隐式
完成或双计数缺口。第二轮检查范围与兼容性，确认未增加依赖、状态字段、schema 版本、Generator
验收权限或 single 行为；删除了 manifest、动态锁和统计推断等非必要设计。

## Implementation Divergence

最终独立代码审查发现，原设计把已有 revision CAS 视为跨恢复进程原子，但实现当时只用单个
Store 实例的 `threading.RLock`，两个 Store 可同时通过同一 revision 检查。修复复用仓库 Loop
checkpoint 已验证的 per-ID `flock` 模式，把 create/save 的检查和原子替换纳入同一跨进程临界区。
该变化强化既定原子提交语义，不改变公开接口、状态字段或 schema。

