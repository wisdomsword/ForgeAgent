# 已取代的中间批次

该批次已通过严格 schema 与篡改测试，但只记录 `tracked_dirty=true`，没有把产生结果的两份 M26
运行时源码 hash 写入 environment。它不能充分证明 dirty worktree 中的具体实现版本，按最终
独立 code review 结论降级保留；权威批次为 `../2026-07-28-final-v4/`。
