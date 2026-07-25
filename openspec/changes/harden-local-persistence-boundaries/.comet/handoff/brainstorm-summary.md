# Brainstorm Summary

- Change: harden-local-persistence-boundaries
- Date: 2026-07-25

## 确认的技术方案

- FileWrite 从 canonical root directory fd 逐组件 `O_NOFOLLOW` 遍历，并以 descriptor 打开最终文件。
- 项目 Memory 通过稳定 `.MEMORY.lock` 的 `fcntl.flock(LOCK_EX)` 在锁内重读、合并和原子替换。
- Loop checkpoint 通过每个 Loop ID 独立稳定 lock file，在锁内完成 create/save 的存在性或 revision CAS。

## 关键取舍与风险

- 使用标准库 POSIX 能力，不新增依赖或通用存储抽象。
- advisory lock 只约束遵循协议的本地 ForgeAgent 进程，不承诺网络文件系统或外部编辑器强一致。
- lock file 保持存在以维持 inode 身份，不保存业务数据。

## 测试策略

- TDD：先增加可控竞态与跨进程失败测试，再实现最小修复。
- 覆盖 symlink 替换、根绑定替换、不同/相同 Memory key、同 revision Loop save/create、锁路径不安全和错误最小披露。
- 运行专项、完整 pytest、golden、Ruff、构建、OpenSpec strict 和独立代码审查。

## Spec Patch

已在 `tool-approval`、`runtime-memory`、`loop-execution` delta spec 中补充验收场景，无额外 patch。
