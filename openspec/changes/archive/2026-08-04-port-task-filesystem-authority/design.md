## Context

M47 的 `Task.allowed_root` 同时承担项目身份/记忆边界、内置文件工具边界和 restricted/container 执行边界。旧分支 change `2026-08-03-authorize-task-filesystem-access` 已完成安全设计、实现与验证；本 change 以 M47 为目标树移植该能力，并保留 M47 后续的工具批准和 HTTP 安全约束。

## Goals / Non-Goals

**Goals:**

- 分离不可变 project root 与任务内可升级的 filesystem root。
- trusted 的 Exec 和内置文件工具具有一致的宿主文件权限。
- restricted 经一次显式确认后扩大当前 Task 的文件范围，但不切换 tier 或放开其他隔离。
- 把实际 tier、权限范围和升级能力作为宿主事实提供给模型。

**Non-Goals:**

- 不改变默认 restricted tier，不提升为同进程 trusted。
- 不扩大 container 挂载，不改变 MCP server 权限。
- 不增加持久授权、目录级授权、撤销 UI 或 HTTP 请求字段。
- 不整体移植旧分支。

## Decisions

1. 以 M47 为目标树，复用旧 change 的已验证设计和测试；按 capability 分块移植，冲突时保留 M47 的新安全边界。
2. Task 保留 project root 用于身份、记忆和相对路径语义，ToolContext 另持有 filesystem root。restricted 批准后以平台根重建相同 restricted backend，tier 保持不变。
3. 默认 registry 注册类型安全的 `RequestFilesystemAccess`。ToolContext 缓存当前 Task 的 approved/denied 决定，目标路径只用于脱敏确认说明，不改变固定的全磁盘授权范围。
4. trusted 从任务创建起让内置文件工具使用平台根；container 固定返回不可动态扩大；未知 custom backend 不猜测 Exec 权限。
5. 每个 Task 的 system prompt 追加 host-generated Runtime Authority；MCP 批准明确不改变该权限事实。
6. 文件权限根只用于校验；文件工具对项目内路径继续显示 project-relative 路径，对项目外绝对路径只显示 basename，避免授权后泄露宿主目录结构。
7. 显式内置 restricted/container backend 的 `allowed_root` 必须与 Task project root 一致，否则构造时 fail closed；全磁盘授权只扩大路径权限，不复用为后续 FileWrite、WebFetch 或 MCP 副作用批准。
8. 相对路径必须针对 project root 完成 realpath containment 校验，扩权后也不得通过 `..` 或 symlink 逃逸；CLI/REPL 为每个单任务传递 audit sink 与 task id，FileWrite 确认审计对外部目标只记录 basename。

## Risks / Trade-offs

- [全磁盘读写范围很大] -> 默认 restricted、明确一次性确认、无 TTY fail closed、决定不跨 Task 持久化。
- [M47 工具批准契约已演进] -> 对照 M47 的 `tool-approval` 完整 requirement 移植，不覆盖后续 HTTP/receipt 语义。
- [backend 切换状态不一致] -> 只在权限工具边界切换，不自动重放此前失败代码，Runtime state 保持独立事实源。
- [跨平台根语义] -> 沿用旧设计的平台根计算；跨 Windows 卷授权不在本 change 范围。
- [扩权后校验根与解析根混淆] -> 相对路径始终以 project root 同时作为解析根和 containment 根；绝对路径才使用当前 filesystem root。

## Migration Plan

从已归档前两项 M48 port 后的最新 `main` 提交 `97af2c2cd8e0359957e43b02d9063078ea888d49` 建立隔离实现分支；build 与 verify 的改动归属统一按该 `base_ref` 比较，不得使用当前旧分支 HEAD `3245a448` 或原始 M47 提交作为 diff 基准。旧 change 仍只作为已验证补丁和测试来源。先移植安全边界测试，再分层移植工具协议、Task 权限状态、Runtime Authority 与 CLI 回归。运行聚焦安全测试、全量测试和 strict spec 验证。授权不持久化，因此无数据迁移；回滚恢复单一 allowed root 即可。

## Open Questions

无；安全模型已由旧 change 验证，实施阶段只处理 M47 冲突。
