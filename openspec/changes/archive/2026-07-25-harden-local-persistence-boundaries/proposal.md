## Why

ForgeAgent 的三个本地持久化边界仍依赖“先检查、后按 pathname 打开”或仅进程内锁：
FileWrite 可在校验与写入之间遭遇 symlink 替换，项目 Memory 的并发写入可能丢失不同 key，
Loop checkpoint 的 revision 检查也不能阻止两个进程同时提交同一旧 revision。它们会削弱
既有项目根目录边界和耐久状态契约，因此需要在不扩展产品能力的前提下完成加固。

## What Changes

- FileWrite 在 canonical containment 校验后，以 descriptor-relative、`O_NOFOLLOW` 的方式逐级
  打开父目录和最终文件，拒绝校验后发生的 symlink 替换。
- 项目 Memory 使用同目录稳定 lock file 和标准库跨进程排他锁，将“重读最新磁盘状态、合并
  候选、原子替换”收敛为一个临界区；不同 key 不再互相覆盖，同 key 保持后锁获得者胜。
- Loop checkpoint 为每个 Loop ID 使用稳定 lock file，将 create/save 的存在性或 revision
  校验与原子替换放入同一跨进程临界区，使 stale revision 只能有一个提交成功。
- 补充并发、symlink 竞态、锁失败和兼容性回归测试，并更新威胁模型与公开规格。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `tool-approval`: FileWrite 的项目根目录约束从静态 symlink 防护扩展到 descriptor-relative
  最终打开，拒绝校验后的 symlink 替换。
- `runtime-memory`: 项目 Memory 的冲突替换扩展为跨进程 read-modify-write 串行化，不同 key
  并发写入必须合并而不是丢失。
- `loop-execution`: checkpoint create/save 的 revision 契约扩展为跨进程原子 CAS，拒绝同一旧
  revision 的重叠提交。

## Impact

- 主要修改 `src/forgeagent/tools.py`、`memory.py`、`loop.py` 及对应测试。
- 使用 Python 标准库和 POSIX descriptor/locking 能力，不新增依赖、配置项、公共命令或数据
  schema 字段。
- 不处理分布式锁、网络文件系统一致性、exactly-once 外部副作用、Windows 新平台支持、
  CollaborationStore 跨进程协调或通用持久化框架。
