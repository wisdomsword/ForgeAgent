## 1. 多进程准入

- [x] 1.1 增加 CollaborationStore 同 revision 进程竞争测试。
- [x] 1.2 增加 Memory 不同 key 并发更新测试。
- [x] 1.3 增加两种真实持锁 SIGKILL 恢复和固定 seed writer kill 测试。

## 2. 耐久性步骤

- [x] 2.1 写 RED：Memory replace 后必须 fsync 父目录。
- [x] 2.2 实现父目录同步并运行 memory/collaboration 全组回归。

## 3. 验证

- [x] 3.1 运行最终全量验证并记录 POSIX/NFS/断电边界。
