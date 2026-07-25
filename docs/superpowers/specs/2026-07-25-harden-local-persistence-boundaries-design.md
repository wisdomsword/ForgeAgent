---
comet_change: harden-local-persistence-boundaries
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-25-harden-local-persistence-boundaries
status: final
---

# 本地持久化边界加固设计

## 目标

在不改变公共 API、文件 schema 或运行入口的前提下，关闭 FileWrite 校验后 symlink 竞态，
并让项目 Memory 与 Loop checkpoint 的 read-modify-write 在多个本地 ForgeAgent 进程之间
保持一致。

## FileWrite

### 数据流

1. 使用现有 containment 逻辑把模型路径转换为 canonical project-relative components。
2. 打开 canonical root，要求 `O_DIRECTORY|O_NOFOLLOW`。
3. 保存 root 的 `(st_dev, st_ino)`；逐个父目录通过当前 directory fd 和
   `O_RDONLY|O_DIRECTORY|O_NOFOLLOW` 打开。
4. 最终目标通过父 directory fd 和 `O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW` 打开，验证是
   regular file 后在 descriptor 上写入。
5. 写入后重新核对 root pathname 与原 descriptor binding；不一致则返回固定失败。由于写入
   可能已经落在原目录 inode，本设计只承诺不写到 symlink 指向的外部目标，不承诺 hostile
   host 删除/移动原目录时回滚已写入的不可见 inode。

### 兼容性

- 不自动创建父目录；不存在父目录仍失败。
- 成功文本仍为 `wrote <project-relative-path>`，失败文本保持固定。
- root 自身不是合法 FileWrite 文件目标。

## Project Memory

### 锁身份与权限

`.forgeagent/.MEMORY.lock` 是固定、空、私有的 lock file。使用 `O_RDWR|O_CREAT|O_NOFOLLOW`
和 `0o600` 打开，验证 regular file 并 `fchmod(0o600)`；`fcntl.flock(LOCK_EX)` 在单候选项目
更新期间持有。稳定文件不删除，避免进程分别锁住不同 inode。

### 锁内更新

锁内重新安全读取 MEMORY.md，复用同一解析与准入规则得到最新 project map，再应用当前
候选。不同 key 合并；相同 key 的状态由锁内最新 map 判断 accepted/replaced，后获得锁者覆盖。
限额针对锁内最新 session+project 组合计算。写盘继续使用同目录临时文件、flush、fsync、
`os.replace`，成功后才替换 manager 内存快照。

读锁内最新文件失败、lock file 不安全或锁失败均返回现有 persistence_error；不得用旧快照
覆盖磁盘。

## Loop Checkpoint

### 每 ID 锁

lock 名称为 `.<loop_id>.lock`，位于已绑定的 loops directory fd 下。使用
`O_RDWR|O_CREAT|O_NOFOLLOW`、`0o600` 打开并验证 regular file，持有 `LOCK_EX`。不同 ID 的
锁互不影响。

### 原子 create/CAS

- `create`：锁内检查 checkpoint 不存在并写 revision 0；重叠 create 只有一个成功。
- `save`：锁内 load 当前 JSON、比较 `expected_revision`、构造 N+1 并原子替换；第二个基于 N
  的提交在获得锁后读取 N+1，返回 stale。
- 内部需要避免在已持有跨进程锁时再次获取同一 lock；用私有 unlocked load helper，而不是
  让 public `load()` 隐式加排他锁。

## 错误处理

所有底层路径、锁和 descriptor 异常映射到现有固定公共错误。descriptor 通过 context manager
或 `finally` 关闭；临时文件继续尽力清理。不得把 lock path、绝对 root 或异常文本写入工具
反馈。安全能力缺失时 fail closed，不静默退回原 pathname/进程内锁实现。

## 测试

- FileWrite：在 validation 之后注入目标/父目录 symlink 替换；根 pathname replacement；最终
  目标目录/非 regular file；外部文件字节不变；固定输出。
- Memory：用两个独立 manager 和受控 barrier 证明旧实现会丢不同 key；相同 key 后锁者胜；
  symlink lock、flock/open/replace 失败；失败后磁盘与内存不变。
- Loop：两个独立 store/process 对相同 revision/create 竞争；断言一个成功一个 stale/already
  exists；不同 ID 能同时进入临界区；symlink lock 和 flock 失败。
- 回归：既有 File tools、Memory/CLI/identity/audit、Loop/HTTP/collaboration、golden、全量门禁。

## 两轮设计自审

第一轮检查安全闭环，确认没有用重复 `realpath/lstat` 代替 descriptor final open，也没有把
`threading.RLock` 误当跨进程锁。第二轮检查范围与兼容性，删除了通用 lock/store abstraction、
锁超时、分布式/Windows 扩展和 CollaborationStore 顺带修改；三项均保持现有公开错误与 schema。

