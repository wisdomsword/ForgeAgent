## ADDED Requirements

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
