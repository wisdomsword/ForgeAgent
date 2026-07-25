## MODIFIED Requirements

### Requirement: 项目记忆原子持久化与冲突替换
项目级记忆 MUST 以稳定的 Markdown 条目格式写入 MEMORY.md，并 MUST 通过同目录临时文件加 `os.replace` 原子替换；写入失败 MUST 保留旧文件并返回结构化错误。项目级 read-modify-write MUST 由同目录稳定 lock file 的跨进程排他锁串行化，并 MUST 在锁内重新加载最新合法条目后再应用候选。相同 key 的新候选 SHALL 由后获得锁的写入替换旧条目，不同 key 的重叠写入 SHALL 合并而不得互相丢失；替换和拒绝都 MUST 可由审计记录追踪。加载时畸形条目 MUST 被忽略并输出脱敏诊断，不得执行其内容。

#### Scenario: 相同 key 冲突替换
- **WHEN** 两个进程基于相同旧快照依次获得锁，并分别为同一 key 写入 `vim` 与 `nvim`
- **THEN** MEMORY.md 只保留后获得锁的 `nvim` 条目，并记录相应 replaced 结果

#### Scenario: 不同 key 并发写入合并
- **WHEN** 两个进程基于相同旧快照分别写入不同 project key
- **THEN** 后获得锁的进程在锁内重读前一提交，最终 MEMORY.md 同时包含两个 key

#### Scenario: 原子写入失败
- **WHEN** lock file 打开、加锁、临时文件创建或替换失败
- **THEN** 旧 MEMORY.md 保持字节不变，任务继续运行并返回 persistence_error

#### Scenario: 畸形条目隔离
- **WHEN** MEMORY.md 包含不符合受控条目格式的 Markdown 或注入文本
- **THEN** 该条目不注入模型上下文，其余合法条目仍可加载

#### Scenario: Memory lock path is unsafe
- **WHEN** 稳定 lock file 是 symlink 或不能以安全私有文件打开
- **THEN** 项目候选返回 persistence_error，MEMORY.md 和当前 manager 的 project 快照均不改变
