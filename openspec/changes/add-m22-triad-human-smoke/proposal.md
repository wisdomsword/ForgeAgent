## Why

M22 已有离线回归与人工执行记录，但缺少一个可重复的一键入口来驱动真实模型 Triad、保留
Planner 人工确认，并自动核验协作状态与产物。手工复制长命令容易漏参数，也难以稳定区分
模型协议失败、人工拒绝和产物验收失败。

## What Changes

- 新增仓库内 Python 一键脚本，在隔离临时目录中运行真实模型 Triad 的 `moving_average` 编程任务。
- 保留原 CLI 的 Planner 计划人工确认，不自动批准。
- 在协作结束后自动核验终态、角色 attempt、生成文件、pytest 与 CLI JSON 输出。
- 失败时保留现场目录并给出稳定诊断；成功时同样打印现场路径，便于人工复核。
- 新增无需真实模型的离线测试，并在 README 提供单命令入口和费用提示。

## Capabilities

### New Capabilities

- `triad-human-smoke`: 定义真实模型 Triad 人工确认冒烟脚本的一键入口、自动验收和失败保留行为。

### Modified Capabilities

无。

## Impact

- 脚本：`scripts/m22-triad-human-smoke.py`
- 测试：`tests/test_m22_triad_human_smoke.py`
- 文档：`README.md`
- 运行时代码、CLI 参数、公开 API、依赖和持久化 schema：不变
