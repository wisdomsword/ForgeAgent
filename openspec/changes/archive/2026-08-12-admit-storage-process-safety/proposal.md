## Why

CollaborationStore 与 MemoryManager 的锁覆盖只由源码和线程测试支持，缺少独立解释器竞争与真实 SIGKILL 后恢复证据；Memory 原子替换后也未同步父目录。

## What Changes

- 增加 spawn 多进程同 revision 竞争、不同 memory key 并发更新和确定性持锁 SIGKILL 恢复测试。
- 增加固定 seed 的有界 writer SIGKILL 诊断，断言无死锁、无畸形状态且后续可恢复。
- Memory 在 `os.replace` 后同步父目录，与 CollaborationStore 的耐久性步骤一致。

## Capabilities

### Modified Capabilities

- `runtime-memory`：跨进程 read-modify-write 和原子替换耐久性步骤可执行验证。
- `runtime-collaboration`：revision 锁在独立进程竞争与持锁进程死亡后可恢复。

## Impact

- `src/forgeagent/memory.py` 与独立 POSIX-only 存储准入测试。
- 不声称验证断电、NFS 或分布式锁语义。
