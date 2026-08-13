# M51 Hardening Verification Report

## 结论

本里程碑的 11 个 Comet change 均已实现并归档。两轮自我审查和独立只读复核发现的问题均已修复，补充回归后重新通过全量验证。独立复核命中并修复了 canonical spec 占位 Purpose、图片增长竞态的无界读取、内置配置错误来源丢失和 TaskStatus 终态投影可变四项问题。

## 验证证据

- 完整 pytest：受限环境为 `3028 passed, 23 skipped, 15 failed`，15 项均因 loopback 或隔离构建网络权限失败；允许相应本地权限后为 `3055 passed, 11 skipped`。
- Golden：`20/20 passed (100.0%)`，报告在 `/tmp/forgeagent-m51-golden/report.md`。
- Ruff：`rtk uv run ruff check src tests` 通过；`ruff format --check src tests` 通过；`git diff --check` 通过。
- 依赖与构建：`uv lock --check` 通过；`uv build` 成功生成 sdist/wheel。
- OpenSpec：全部 `51 passed, 0 failed`（含 11 个 active change 和 40 个主规格）。
- 归档后 OpenSpec：`42 passed, 0 failed`；11 个 change 均为 `phase: archive`、`verify_result: pass`、`archived: true`。
- C901 report-only：保留现有复杂函数清单，不作为本阶段阻断门禁；结构拆分后未新增 C901 门禁。

## 自我审查与修复

- 恢复 `mcp_manager.DEFAULT_USER_MCP_PATH` 猴子补丁兼容，并添加回归测试。
- 将 G08 旧 sandbox 错误文案断言和 CLI help 快照同步到新的稳定反馈/可配置限额契约。
- 共享 `config.yaml` 严格校验明确允许既有 `groups`、`context`、`restricted`、`search_engine`，并增加组合配置回归。
- 独立复核发现的四项问题均已修复：主规格占位 Purpose、图片增长后的有界读取、内置/用户配置来源定位、不可变三态 TaskStatus 投影。
- Storage 进程准入测试仅证明 POSIX 本地文件锁、SIGKILL 恢复和父目录 fsync 顺序；不外推 NFS 或断电耐久性。

## 已知边界

- `restricted` 仍是应用层隔离，不是 OS 密封沙箱；Unix `rlimit` 在 Windows 不可用时由父进程超时作为后备。
- C901 仍有既有复杂函数，按裁决仅记录 report-only，后续结构拆分可再处理。
- OpenSpec CLI 的 PostHog 刷新曾出现网络超时；原生本地验证结果不受影响。
