## Decisions

1. 测试固定使用 `multiprocessing.get_context("spawn")`，worker 为模块顶层函数。
2. 协作同 revision 竞争重复三次，每轮四个进程且恰有一个提交 revision 1。
3. SIGKILL 只杀测试自己的专用持锁子进程；所有 join 有上限并清理残留进程。
4. 随机杀 writer 使用固定 seed，只验证存储可解析和后续写可恢复，不要求被杀写入保留。
5. Memory 在文件 fsync、replace 后打开并 fsync 父目录；该顺序不等同于断电模拟。
