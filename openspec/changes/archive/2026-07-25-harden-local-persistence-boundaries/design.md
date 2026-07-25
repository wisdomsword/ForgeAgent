## Context

三个边界都已使用同目录临时文件加 `os.replace`，但原子替换只保证单次写入不撕裂，并不
保证前置决策与写入之间的原子性：FileWrite 的 containment 检查与 pathname open 分离；
Memory 基于进程启动时的快照重写整个文件；Loop 的 revision 比较只受对象内
`threading.RLock` 保护。目标平台已有 POSIX descriptor 和 `fcntl.flock`，项目也已有
descriptor-relative、`O_NOFOLLOW`、`fsync` 的 store 模式。

## Goals / Non-Goals

**Goals:**

- FileWrite 的最终写入不得跟随校验后新出现的 symlink，父目录替换也必须失败关闭。
- 项目 Memory 的跨进程更新必须在锁内重读并合并最新磁盘状态。
- Loop create/save 的存在性或 revision 校验与替换必须在同一跨进程锁内完成。
- 保持现有公共 API、固定错误文本、文件格式和原子替换语义。

**Non-Goals:**

- 不提供分布式锁、网络文件系统强一致、Windows 新平台支持或锁超时配置。
- 不解决 Loop 外部副作用 exactly-once，也不扩展 CollaborationStore。
- 不新增依赖、通用 storage/lock abstraction、数据库或后台守护进程。

## Decisions

### 1. FileWrite 使用逐组件 descriptor-relative open

从 canonical `allowed_root` 以 `O_DIRECTORY|O_NOFOLLOW` 打开根目录 descriptor；规范化相对
路径并拒绝 `..`、空目标和 root 本身。逐级用 `dir_fd` 打开既有父目录，缺失父目录保持
当前“不自动 mkdir”的行为；最终文件用 `O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW` 打开并在
descriptor 上写入。写入前后验证 root directory binding，任何 symlink、非目录、目录替换
或最终目标非普通文件均返回现有固定失败结果。

未采用“再次 realpath/lstat”，因为检查与最终 open 之间仍有竞态；未采用临时文件替换，
因为 FileWrite 当前公开语义允许覆盖目标，而 descriptor-relative final open 已足够封闭本次
竞态且 diff 更小。

### 2. Memory 使用稳定 lock file 串行化 read-modify-write

项目 Memory 写入前打开 `.forgeagent/.MEMORY.lock`，使用 `fcntl.flock(LOCK_EX)`。锁内从磁盘
重新解析最新合法 project entries，再应用单个候选并检查条目/字节上限，最后沿用同目录临时
文件加 `os.replace`。不同 key 因重读而合并；同 key 由后获得锁的候选覆盖。成功后更新当前
manager 的 `_project`；锁/open/read/write 失败继续返回 `persistence_error`，不修改内存快照。

采用 advisory lock 而不是 revision 字段，避免改变人类可编辑的 MEMORY.md 格式。锁文件固定、
私有权限、拒绝 symlink，并只在写入临界区持有。

### 3. Loop 使用每 ID lock file 实现跨进程 CAS

在既有 `.forgeagent/loops` directory fd 下为每个 Loop ID 使用 `.<id>.lock`，以
`O_CREAT|O_NOFOLLOW` 和私有权限打开并获取 `LOCK_EX`。`create` 的“不存在检查+写入”和
`save` 的“load current+expected_revision 比较+写入”全部在该锁内执行。锁文件不删除，避免
unlink 后不同进程锁住不同 inode；checkpoint JSON schema 和 revision 字段不变。

采用每 ID 锁而不是全目录锁，使不同 Loop 仍可并行；不依赖 `threading.RLock` 提供跨进程
保证，后者只继续保护同一 store 对象的线程安全。

### 4. 失败语义保持固定且 fail closed

FileWrite 不披露路径或异常。Memory 锁/重读/替换失败映射为现有
`persistence_error/project_write_failed`。Loop 锁或 CAS 失败映射为
`LoopCheckpointError`，Checkpoint tool 继续返回 `Checkpoint save failed`。所有 descriptor
在异常路径关闭，临时文件继续尽力清理。

## Risks / Trade-offs

- `flock` 是 advisory 且依赖本地 POSIX 文件系统 → 只约束 ForgeAgent 进程；文档不承诺对
  绕过协议的外部编辑器或不可靠网络文件系统提供强一致。
- FileWrite 逐组件 open 增加少量平台代码 → 直接复用现有 store 的 `O_NOFOLLOW`/directory-fd
  模式并用集中测试覆盖，不抽象通用 filesystem manager。
- 稳定 lock file 会留在 `.forgeagent` 目录 → 文件有界且不含业务内容；不删除以保证 inode
  锁身份稳定。
- Memory 锁内重读可能遇到手工写入的畸形文件 → 沿用现有“忽略畸形条目、保留合法条目”
  规则，且候选写入不会把未解析内容重新保存。

## Migration Plan

无需数据迁移。现有 MEMORY.md 和 Loop JSON 保持兼容；首次写入按需创建稳定 lock file。
回滚代码后遗留 lock file 无行为影响。实现按测试先行分别落地 FileWrite、Memory、Loop，
最后更新主规格和威胁模型并运行全量门禁。

## Open Questions

无。用户已授权在决策点经两轮自审后采用推荐方案。
