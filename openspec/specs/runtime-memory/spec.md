# runtime-memory Specification

## Purpose
Define bounded runtime Memory discovery, trust, candidate writes, correction, persistence, and recovery behavior.
## Requirements
### Requirement: 记忆候选提取协议
系统 SHALL 支持从模型响应中的 `<!-- Memory: {...} -->` 标记提取结构化候选，并 SHALL 支持 CLI `/remember` 将用户输入转换为同一候选类型。候选 MUST 包含非空 `content`、稳定 `key`、`scope`（`session` 或 `project`）和 `kind`（`fact`、`preference`、`decision` 或 `procedure`）；标记 SHALL 从展示给用户的正文中移除，格式错误 SHALL 生成可回馈的解析错误而不是写盘。

#### Scenario: 提取合法模型候选
- **WHEN** 模型响应包含合法的 Memory JSON 标记
- **THEN** 解析结果包含一个候选，且正文不再包含该标记

#### Scenario: 用户显式提交候选
- **WHEN** 用户在 REPL 输入 `/remember project preferred-editor=vim`
- **THEN** 运行时创建项目级事实候选并执行与模型候选相同的准入和冲突流程

#### Scenario: 非法标记不写入
- **WHEN** Memory 标记 JSON 缺少 key、scope 或 content，或字段类型不正确
- **THEN** 解析结果包含结构化错误，MEMORY.md 与会话状态均不发生变化

### Requirement: 确定性准入与程序性分流
系统 SHALL 只准入陈述性事实、用户偏好和已确认决策；`kind=procedure` 的候选 MUST 被拒绝并反馈“请沉淀为 Skill”。候选内容 MUST 经过长度、控制字符、敏感环境值和明显提示注入指令检查；任一检查失败 MUST 拒绝候选。系统 MUST NOT 使用向量相似度、置信度模型或额外 LLM 调用决定准入。Task MUST 暴露每个逻辑模型候选的结构化准入结果，CLI SHALL 在任务输出中展示该权威结果且不得回显候选原文；同一 Task 内某个 scope/key 的 kind 和 content 自上次候选后均未变化时，重复候选 MUST 只应用、审计和反馈一次；值发生变化后再改回原值 MUST 继续按出现顺序处理。

#### Scenario: 陈述性事实准入
- **WHEN** 候选 kind 为 fact、内容通过边界检查且 key 有效
- **THEN** 候选进入目标作用域并生成 accepted 审计事件

#### Scenario: 程序性记忆拒绝
- **WHEN** 候选描述“每次先运行某命令再修改文件”等做事步骤且 kind 为 procedure
- **THEN** 候选不进入任何作用域，并返回应沉淀为 Skill 的结构化拒绝原因

#### Scenario: 提示注入候选拒绝
- **WHEN** 候选内容包含要求忽略系统协议、泄露 secret 或执行越权动作的指令
- **THEN** 候选被拒绝且拒绝反馈不回显敏感原文

#### Scenario: 禁用记忆时纠正模型声明
- **WHEN** `--no-memory` 模式下模型响应包含合法 Memory 候选并声称已记住
- **THEN** Task 返回 disabled 结果，CLI 展示 `memory disabled`，且 session 与 project 存储不变

#### Scenario: 多轮未变化候选幂等
- **WHEN** 同一 Task 的多个模型 round 对同一 scope/key 重复发出未发生变化的 kind 和 content
- **THEN** Task 只应用该候选一次，并只返回一个准入结果和一条对应审计事件

#### Scenario: 候选值变化后回退
- **WHEN** 同一 Task 对一个 scope/key 依次发出内容 A、内容 B、再发出内容 A
- **THEN** Task 按顺序处理三次候选，最终值为 A

### Requirement: 会话与项目两级作用域
系统 SHALL 维护两个互不混淆的作用域：session 记忆仅在当前 REPL 进程内跨 Task 生效且不得落盘，project 记忆写入当前 `allowed_root/.forgeagent/MEMORY.md` 并在后续任务的身份组合中整体注入。HTTP/headless 每个任务只加载项目级记忆，不得共享其他任务的会话级状态。`--no-memory` MUST 同时阻止两级记忆的加载、注入和候选写入。

#### Scenario: 会话记忆跨任务可见
- **WHEN** 一个 REPL Task 接受 session 候选，随后启动第二个 Task
- **THEN** 第二个 Task 的 system prompt 包含该候选，且磁盘 MEMORY.md 不增加内容

#### Scenario: 项目记忆跨进程可见
- **WHEN** 一个 Task 接受 project 候选并结束，新的进程在同一 allowed_root 启动
- **THEN** 新进程加载 MEMORY.md 中的候选并将其注入 system prompt

#### Scenario: HTTP 不共享会话记忆
- **WHEN** 两个 HTTP 任务先后运行且第一个任务产生 session 候选
- **THEN** 第二个任务看不到该 session 候选，只能看到已存在的 project 记忆

#### Scenario: no-memory 禁用
- **WHEN** CLI 以 `--no-memory` 启动或 REPL reload 后记忆被禁用
- **THEN** 两级记忆均不进入 prompt，且任何候选都不会改变会话或项目存储

### Requirement: 项目记忆原子持久化与冲突替换
项目级 read-modify-write MUST 由稳定 lock file 的跨进程排他锁串行化；不同 key 的独立进程并发写入 MUST 全部保留。临时文件内容 MUST 在替换前 fsync，`os.replace` 后 MUST fsync 父目录。持锁进程被 SIGKILL 后，内核释放锁且后续正常写 MUST 可完成。该契约不声明 NFS、分布式锁或断电耐久已经由 SIGKILL 测试证明。

#### Scenario: 不同 key 的独立进程并发写入
- **WHEN** 多个 spawn 子进程同时写入不同 project key
- **THEN** 所有成功返回且新 manager 加载到全部 key

#### Scenario: 持锁进程被杀后恢复
- **WHEN** 独立进程持有 `.MEMORY.lock` 时被 SIGKILL
- **THEN** 后续正常 apply 在有界时间内完成，MEMORY.md 可解析并可继续写入

#### Scenario: 替换后同步目录
- **WHEN** Memory 原子替换成功
- **THEN** 系统在返回成功前同步父目录描述符

### Requirement: 用户可见的查看与纠正
REPL SHALL 提供 `/memory` 查看当前有效 session/project 条目（内容经过既有 secret 掩码且限制总量），并 SHALL 允许用户通过直接编辑项目 MEMORY.md 纠正事实；下一次任务或 `/reload` 必须读取纠正后的文件。查看输出 MUST 标明作用域和 key，但不得展示内部审计路径或 secret。

#### Scenario: 查看记忆
- **WHEN** 用户输入 `/memory`
- **THEN** CLI 分别列出 session 与 project 条目，并对敏感值显示掩码

#### Scenario: 手工纠正后 reload
- **WHEN** 用户编辑 MEMORY.md 的条目并输入 `/reload`
- **THEN** 后续任务使用纠正后的内容，旧 session 状态不被静默转换为 project 条目

### Requirement: 记忆生命周期审计与最小披露
系统 SHALL 在核心层为 accepted、rejected、replaced、persistence_error 和 disabled 记忆操作写入既有 JSONL 审计 sink；事件 MUST 包含 task correlation、scope、kind、key 的脱敏摘要和结果状态，但 MUST NOT 包含候选原文、完整 MEMORY.md、token、secret 或宿主绝对路径。审计 sink 不可用时 SHALL 遵循既有 audit-degraded 语义，不得阻止无关任务完成。

#### Scenario: 准入审计
- **WHEN** 项目候选成功写入
- **THEN** 产生一个 memory.accepted 事件，包含 scope、kind、key 和 task id，不包含 content

#### Scenario: 拒绝审计
- **WHEN** 程序性或注入候选被拒绝
- **THEN** 产生一个 memory.rejected 事件，reason 可诊断但不泄露原文

#### Scenario: 审计降级
- **WHEN** 记忆审计写入失败
- **THEN** 任务仍按既有 fail-open 规则继续，且系统标记 audit_degraded 而不虚报已持久化

### Requirement: 可执行回归验证
系统 MUST 提供准入规则表驱动测试、协议解析测试、跨 Task mock replay、project 持久化重启测试、`/memory`/`--no-memory` CLI 测试和记忆投毒回归。新增 golden 候选 SHALL 维持既有类别配比，且离线 runner MUST 能在无 API key 环境验证记忆命中与拒绝场景。

#### Scenario: 跨任务记忆回放
- **WHEN** mock replay 的第一个 Task 写入事实，第二个 Task 请求该事实并仅提供含记忆即可完成的响应
- **THEN** 第二个 Task 的请求消息包含第一任务写入的记忆且 runner 断言通过

#### Scenario: 投毒回归
- **WHEN** mock replay 试图写入忽略协议或泄露环境值的候选
- **THEN** 候选被拒绝、后续 Task 的 prompt 不包含该内容且测试退出码为零

### Requirement: 项目 Memory 宿主拥有的治理元数据
系统 SHALL 以单一 `MEMORY.md` v2 文件持久化项目 Memory 正文及其治理元数据。每条记录的元数据 MUST 包含为什么保留、候选来源、实际写入者、谁可写、真相来源、可见性、写入时间、到期/复核条件、恢复来源以及删除/纠错策略；候选来源表示记录来自哪个受控入口，真相来源表示内容的权威边界，两者 MUST NOT 混写。元数据 MUST 由宿主从可信调用上下文生成和校验，模型提交的 `MemoryCandidate` MUST NOT 能设置或覆盖这些字段。文件写入 MUST 继续使用同一项目锁、私有临时文件和原子替换，且存储大小与注入上下文大小 MUST 分别受有界限制。

#### Scenario: 模型候选不能伪造元数据
- **WHEN** Task 接受一个合法的 project `MemoryCandidate`
- **THEN** 宿主使用固定的模型候选 source/writer 策略生成元数据，候选正文不能声明自己是用户或权威工具写入

#### Scenario: 用户显式写入具有独立来源
- **WHEN** 用户通过 `/remember` 提交合法 project 候选
- **THEN** 宿主将来源记录为用户命令路径，并保持治理字段不进入模型可控制协议

#### Scenario: v2 原子持久化
- **WHEN** 新项目在没有 MEMORY.md 时接受首条 project 候选
- **THEN** 系统原子创建可重新加载的 v2 文件，正文和完整元数据属于同一次提交

### Requirement: Memory 迁移 readiness 与旧格式兼容
系统 SHALL 提供不写盘的 readiness 检查，至少区分无数据、可读 v1、缺迁移元数据、有效 v2、需修复和不安全存储。readiness 结果 MUST 只包含固定状态、格式版本、条目计数和固定原因码，不得包含正文、secret、绝对路径、raw exception 或由正文直接导出的公开摘要。旧 v1 文件 SHALL 继续加载和渲染；普通 project 写入遇到 v1 时 MUST 返回 `migration_required`，不得静默迁移或继续产生无元数据记录。

#### Scenario: 当前仓库无历史数据
- **WHEN** 项目 `.forgeagent/` 中不存在 MEMORY.md
- **THEN** readiness 返回 `no_data`、零条目且不创建文件或备份

#### Scenario: 旧 v1 继续可读
- **WHEN** 项目包含合法 v1 MEMORY.md
- **THEN** load 和 render 仍可使用其合法条目，readiness 将其识别为 legacy 且不修改原文件

#### Scenario: 旧 v1 阻止普通写入
- **WHEN** v1 文件存在且普通 Task 或 `/remember` 尝试写入 project Memory
- **THEN** 系统返回 `rejected/migration_required`，磁盘字节和 manager 的项目快照均不改变

#### Scenario: 不安全或损坏存储最小披露
- **WHEN** MEMORY.md、lock 或备份路径为 symlink、越界、不可读或格式不完整
- **THEN** readiness 返回固定的 `unsafe` 或 `repair_required` 原因，不泄漏宿主路径和底层异常文本

### Requirement: 显式 Memory 迁移、验证与恢复副本
系统 SHALL 只在调用方为每个 v1 条目提供完整且有效的治理 manifest 后执行显式迁移，并 MUST 在项目锁内重读源文件和验证 key 集合。系统 MUST NOT 从旧正文推断来源、写入者或真相；manifest 可以显式标记未知历史值，但未知 truth source 的记录 MUST 在迁移后立即处于待复核状态且不得进入有效上下文。写入 v2 前 MUST 创建项目内私有、不可覆盖且 symlink-safe 的恢复副本；写入后 MUST 重新解析并验证 key/content 语义等价、元数据完整、revision 一致以及大小边界。替换前的失败 MUST 保持原 v1 字节；替换后的验证失败 MUST 尝试从恢复副本自动恢复并验证。若恢复无法确认，系统 MUST 返回 `recovery_failed`、保留恢复副本且不得报告迁移成功。迁移结果和审计 MUST NOT 包含 Memory 正文、secret 或绝对路径。

#### Scenario: 缺失 manifest 不迁移
- **WHEN** v1 有两个条目而 manifest 缺少、增加或错误映射任一 key
- **THEN** 迁移在写盘前失败，v1 字节不变且不创建虚假的成功结果

#### Scenario: 未知历史来源不被推断
- **WHEN** 操作者无法证明某条 v1 Memory 的原始写入者或 truth source，并在完整 manifest 中显式标记 unknown
- **THEN** 系统保留该正文但将记录标记为待复核，迁移后不把它注入模型上下文，且宿主时钟回拨不会使它重新生效

#### Scenario: 成功迁移并验证语义等价
- **WHEN** 合法 v1 的每个 key 都有完整治理 manifest 且存储路径安全
- **THEN** 系统先创建 `0600` 恢复副本，再原子写入 v2，并由 verifier 证明 key/content 等价和元数据完整

#### Scenario: 写后验证失败自动恢复
- **WHEN** v2 写入后重新解析或语义验证失败
- **THEN** 系统在锁内恢复迁移前字节，返回固定失败码且不报告迁移成功

#### Scenario: 自动恢复无法确认
- **WHEN** 写后验证失败且恢复写入或恢复后验证也失败
- **THEN** 系统返回 `recovery_failed`、保留私有恢复副本并将当前状态视为未知，不得报告迁移或回滚成功

#### Scenario: 迁移报告最小披露
- **WHEN** readiness、migrate 或 verify 返回公开结果并写审计
- **THEN** 结果只包含固定状态、计数和 opaque migration/revision 标识，不包含正文、secret、完整 key 集、原始 manifest 或绝对路径

### Requirement: Memory 回滚的 revision 冲突保护
系统 SHALL 只允许恢复与当前迁移标识匹配的私有副本，且当前 v2 revision MUST 仍等于迁移完成时的 revision。迁移后发生任何写入、纠错、删除或复核时，回滚 MUST 返回 `rollback_conflict`，不得提供无条件覆盖或 force 路径。成功回滚后 MUST 验证恢复字节可按 v1 重新解析。

#### Scenario: 未变化的迁移可回滚
- **WHEN** v2 自迁移完成后未发生变化，且 migration id、revision 和恢复副本均匹配
- **THEN** 系统原子恢复 v1，重新解析成功并返回固定的 rolled_back 结果

#### Scenario: 后续写入阻止回滚
- **WHEN** 迁移后任一记录被新增、替换、删除或复核
- **THEN** 旧迁移的 rollback 返回 `rollback_conflict`，当前 v2 文件保持不变

#### Scenario: 不安全备份拒绝回滚
- **WHEN** recovery 副本缺失、为 symlink、不是 regular file 或不属于项目备份目录
- **THEN** rollback 返回固定失败码且不读取项目外内容

### Requirement: Memory 到期复核、纠错与删除
系统 SHALL 保留完整项目记录用于治理，但 `render()` MUST 排除已到 `expires_at` 或 `review_after` 的记录。日期为空时元数据 MUST 提供明确的 `revalidate_on` 条件。宿主 SHALL 提供受控的纠错、删除和复核操作；每次成功操作 MUST 原子写入新 revision，并使旧迁移 rollback 失效。时间判断 MUST 支持可注入时钟，诊断和审计不得回显正文。

#### Scenario: 到期记录停止注入
- **WHEN** 可注入时钟达到一条记录的 expires_at
- **THEN** 记录仍可治理和纠错，但不出现在模型上下文中，并产生固定的 expired 诊断/审计

#### Scenario: 待复核记录停止注入
- **WHEN** 可注入时钟达到 review_after 且记录尚未复核
- **THEN** 记录不再进入模型上下文，直到宿主显式复核或纠正

#### Scenario: 纠错生成新 revision
- **WHEN** 宿主纠正 v2 记录正文或治理元数据且输入通过校验
- **THEN** 系统原子替换该记录、生成新 revision，并保持其余记录不变

#### Scenario: 删除记录
- **WHEN** 宿主按 key 删除一条 v2 项目 Memory
- **THEN** 该条目从持久化文件和后续上下文中移除，并产生不含正文的删除审计

#### Scenario: 复核恢复有效状态
- **WHEN** 宿主对待复核记录执行有效复核并给出新的复核条件
- **THEN** truth source、生命周期元数据和 revision 原子更新，原始 source/writer 保持不变，记录在新条件有效时重新进入上下文

### Requirement: Memory 迁移回归与离线 verifier
系统 MUST 提供 v1/v2 解析、readiness、元数据宿主所有权、到期过滤、迁移备份、写后恢复、revision 冲突回滚、symlink 边界和公开结果脱敏的可执行测试。项目内 verifier MUST 离线运行，只访问指定项目根目录，并 MUST 在当前仓库无 MEMORY.md 时验证 `no_data` 且跳过 migrate。

#### Scenario: 离线 readiness verifier
- **WHEN** verifier 在无 API key、无网络且当前仓库没有 MEMORY.md 的环境运行
- **THEN** 它以零退出码报告 `no_data` 和迁移已跳过，不创建 MEMORY.md 或恢复副本

#### Scenario: 故障注入覆盖自动恢复
- **WHEN** 测试在备份后、原子替换后或写后验证阶段注入失败
- **THEN** 每个故障点都证明旧字节可恢复且公开错误不含正文、secret、路径或 raw exception

