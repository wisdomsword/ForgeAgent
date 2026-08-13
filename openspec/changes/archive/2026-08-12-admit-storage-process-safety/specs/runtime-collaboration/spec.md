## ADDED Requirements

### Requirement: Collaboration revision 锁具备进程级准入证据
CollaborationStore MUST 在独立进程对同一 revision 竞争时只提交一个 writer，其余 writer MUST 收到稳定 stale revision 错误。持有 collaboration lock 的进程被 SIGKILL 后，后续正常 save MUST 在有界时间内恢复。

#### Scenario: 同 revision 多进程竞争
- **WHEN** 四个 spawn 子进程同时以 expected revision 0 保存同一 collaboration
- **THEN** 恰有一个提交 revision 1，其余均因 stale revision 失败，最终 JSON 合法

#### Scenario: 持锁进程死亡
- **WHEN** 专用子进程持有 collaboration lock 时被 SIGKILL
- **THEN** 新 store 能获取锁并完成下一次 revision-checked save
