## MODIFIED Requirements

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
