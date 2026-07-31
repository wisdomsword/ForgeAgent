## Why

ForgeAgent 已具备 trusted、restricted 和 container 三条 Python 执行路径，但当前没有针对执行后端替换的同口径基线，无法用证据判断启动延迟、吞吐、隔离、崩溃恢复或维护成本是否已经构成重写瓶颈。M43 先把六项 Rewrite/Dependency 门禁落成可复现测量和有界结论，避免因技术偏好直接进入 Rust 重写或新增依赖。

## What Changes

- 新增标准库离线测量入口，生成版本化、机器可读且不含凭据或绝对路径的执行后端基线证据。
- 为 performance、reliability、maintenance cost、compatibility、team capability、migration/rollback risk 六项指标分别记录 baseline、threshold、evidence、migration 和 rollback trigger。
- 对 trusted 与 restricted 路径执行同口径测量；container 只在真实 Docker daemon 与固定镜像可用时测量，不可用必须记为未验证而非通过。
- 形成是否允许后续单模块可回滚试验的明确 verdict；未达到阈值或证据不完整时保持现有 Python 实现。
- 增加离线契约测试、验证报告和 M43 里程碑记录。
- 不实现 Rust 后端，不新增运行时或开发依赖，不改变执行协议、sandbox、CLI、配置、schema 或发布状态。

## Capabilities

### New Capabilities

- `execution-backend-rewrite-readiness`: 定义 Python 执行路径六项基线、证据完整性、试验准入和停止/回滚契约。

### Modified Capabilities

无。

## Impact

影响范围限于离线测量脚本、其契约测试、评估文档、验证报告、OpenSpec 产物和里程碑账本。`src/forgeagent/executor.py`、`_sandbox_worker.py`、运行时依赖树和所有用户可见接口保持不变；不执行 PyPI、tag 或发布自动化。普通分支 push 只作为已授权的版本控制交接，不属于测量能力。
