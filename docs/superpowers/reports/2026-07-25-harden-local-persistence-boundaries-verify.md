# 本地持久化边界加固验证报告

## 结论

`harden-local-persistence-boundaries` 已通过完整验证。FileWrite 的校验后 symlink 竞态、项目
Memory 的跨进程 lost update，以及 Loop checkpoint 的跨进程 create/save CAS 均已按 delta
spec 实现，未新增依赖、公共 API、配置项或文件 schema。

## 实现与验收映射

- FileWrite：canonical root descriptor、逐级 `O_NOFOLLOW` 父目录遍历、最终 descriptor open、
  regular-file 校验和 root binding 复核；目标/父目录/root 替换及 FIFO 均固定失败，外部目标不变。
- Project Memory：稳定 `.MEMORY.lock`、私有权限、锁内重读/合并/限额检查/原子替换；不同 key
  合并、同 key 后锁者替换，锁或写入失败不修改磁盘和 manager 快照。
- Loop checkpoint：每 ID 稳定 lock file，create 存在性检查与 save revision CAS 均在同一锁区；
  同 revision 重叠提交只有一个成功，不同 ID 不共享全局锁。
- 非 POSIX 环境保持包可导入；实际进入项目 Memory 持久化或 checkpoint create/save 时因缺少
  `flock` 明确 fail closed，不静默退回进程内锁。

## 验证证据

- `ruff format --check .`：100 files already formatted。
- `ruff check .`：All checks passed。
- P1 关联回归：315 passed, 10 skipped。
- 完整 pytest：2090 passed, 11 skipped。
- 离线 golden：20/20 passed (100.0%)。
- wheel/sdist：成功生成 `forgeagent-0.1.0-py3-none-any.whl` 与
  `forgeagent-0.1.0.tar.gz`。
- `openspec validate --all --strict`：18 passed, 0 failed。
- `git diff --check <base-ref>..HEAD`：通过。

首次在受限沙箱内运行完整 pytest 时，11 项既有 HTTP 黑盒测试因 loopback bind 被拒绝、1 项
嵌套 `uv build` 因环境权限失败；在允许 loopback 与本地 uv 缓存的同一代码版本上复跑后全部
通过。独立 build 使用空缓存时还因网络不可用无法下载 `hatchling`，改用已有默认缓存离线构建
成功。这些均为验证环境限制，不是产品行为分支。

## 两轮自审与代码审查

第一轮按 requirement/scenario 检查安全闭环、失败回滚、固定错误、descriptor/lock fd 生命周期
和文档一致性，修复了 FileWrite 非普通文件截断顺序、Memory 临时文件 fsync，以及非 POSIX
顶层 `fcntl` 导入兼容性。

第二轮检查锁顺序、每资源 lock inode、不同 ID 并行、未跟踪文件隔离和测试有效性，修复了测试
文件的 Windows 收集兼容性，并把重叠 checkpoint save 测试改为在 `LOCK_EX` 前同步，直接证明
真实锁竞争。未发现剩余 Critical 或 Important 问题。

按 `requesting-code-review` 尝试运行外部 `codex review` 时，安全策略因其可能导出仓库 diff 而
拒绝执行；未绕过该限制，改为上述两轮本地逐项审查。残余风险仅为设计中已明确的 advisory
`flock`/不可靠网络文件系统、绕过协议的外部写者，以及 checkpoint 不提供外部副作用
exactly-once。

## 分支与隔离

最终分支为 `codex/harden-local-persistence-boundaries`，从
`eb2dc8dfa053988ae9e71283fb79b02f8d176fc1` 建立，只包含本 P1 change 的提交。共享工作区中另一
任务的归档提交被完整保留在 `codex/harden-local-persistence-boundaries-shared-state`，没有进入
本 P1 分支，也没有被删除或改写。分支选择为保留不合并、不推送；change 验证通过后暂不归档。
