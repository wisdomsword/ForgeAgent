## Why

M22 真实人类冒烟已完成 Triad 协作并生成可独立通过的 pytest 用例，但宿主 `RunCheck` 在隔离 worker 中以 `ModuleNotFoundError: No module named '_pytest._code'` 失败。根因是 check worker 的 audit hook 允许读取当前 Python 环境文件，却禁止导入器枚举同一 `sys.prefix` 目录，导致已安装包的子模块解析失败。

## What Changes

- 为 audit hook 增加仅供 check worker 使用的只读目录枚举根列表。
- check worker 仅允许枚举当前 Python 的 `sys.prefix` 与 `sys.base_prefix`，继续禁止其他宿主目录枚举、宿主文件写入、网络与进程创建。
- 增加真实 `python -m pytest` RunCheck 回归，并复验 M22 保留现场产物。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`: 宿主冻结的 Python 检查必须能够导入当前解释器环境中已安装依赖，同时保持项目副本之外的目录枚举拒绝。

## Impact

- 代码：`src/forgeagent/_sandbox_worker.py`、`src/forgeagent/_check_worker.py`。
- 测试：`tests/test_check_runner.py`。
- 文档：`ACTION_PLAN.md`、`docs/threat-model.md`。
- 不修改公共 API、状态 schema、依赖、Evaluator 工具权限或普通 restricted executor 的默认策略。
