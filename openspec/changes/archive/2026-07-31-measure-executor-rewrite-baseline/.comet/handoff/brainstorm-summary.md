# Brainstorm Summary

- Change: `measure-executor-rewrite-baseline`
- Date: 2026-07-31

## 确认的技术方案

使用一个标准库离线脚本测量 trusted、restricted 和条件可用的 container 执行路径，生成固定 schema 的 JSON 证据。六项指标在测量前固定 threshold；测试只锁定报告结构、脱敏、边界状态和 verdict 纯判定，不把本机计时接成跨机器 CI 门禁。只有证据完整、真实瓶颈越阈且兼容、团队能力、迁移/回滚三项可行性均通过，才允许未来另建单模块试验 change。

## 关键取舍与风险

- 选择可复现脚本而非手工命令，避免证据口径漂移。
- 不引入 benchmark 框架或新依赖；脚本保持单文件、标准库和项目现有 API。
- container 不可用固定记为 `not_available`，不自动拉镜像、不视为通过。
- Docker/container 启动时间只作诊断，不单独触发 Python rewrite，以免把容器运行时开销错误归因于 Python。
- `rustc/cargo` 可执行文件存在不等于团队具备维护能力；未完成构建、排障、打包和回滚演练时 team capability 不满足试验准入。
- 当前主工作区含 M43 前的用户改动，M43 必须按文件选择性归因和暂存。

## 测试策略

先写失败测试锁定六个 metric key、每项五个治理字段、三态 backend evidence、敏感内容禁入和三个 verdict。再实现最小测量脚本，运行真实 trusted/restricted 正常与 crash/timeout 恢复；container 仅在本地 daemon 与固定镜像现成可用时运行。完成后执行聚焦、全量 pytest、Ruff、format、diff check、OpenSpec strict 和 Comet verify。

## Spec Patch

无。OpenSpec delta spec 已覆盖证据完整性、不可用语义、准入判定和未来试验可逆性。

