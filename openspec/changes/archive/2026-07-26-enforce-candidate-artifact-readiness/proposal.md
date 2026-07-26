## Why

真实模型 M22 Triad 人类冒烟连续出现 Generator 在未创建任何目标文件时直接成功调用零载荷 `SubmitCandidate`。当前运行时把该空候选视为合法提交，只能由 Evaluator 事后拒绝；模型随后重复原样提交，最终稳定耗尽 rejection limit。提示词加固已经被真实运行证明不足，因此候选提交边界需要一个宿主可验证、默认关闭的最小就绪条件。

## What Changes

- 允许宿主为一次协作冻结一组有界的顶层候选文件名。
- `SubmitCandidate` 仅在这些名字都解析为 allowed root 下的非符号链接普通文件时成功；失败保持当前 phase、attempt 和 verdict 不变，并向当前 Generator Step 返回有界结构化反馈。
- 默认要求列表为空，保持现有 single、Duo、Triad、Loop、HTTP 与嵌入调用行为不变。
- M22 人类冒烟通过私有子进程环境配置要求 `calc.py` 和 `test_calc.py`，不新增公开 CLI 参数，也不取消 Planner 或 FileWrite 人工确认。
- 更新 README、ACTION_PLAN 与离线回归，明确该门禁只验证候选载体存在，不验收内容正确性。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`: 增加宿主冻结候选文件存在性门禁及其原子失败语义。
- `triad-human-smoke`: 一键脚本为固定编程任务注入 `calc.py`、`test_calc.py` 候选就绪要求。

## Impact

- 代码：`src/forgeagent/collaboration.py`、`src/forgeagent/cli.py`、`scripts/m22-triad-human-smoke.py`。
- 测试：协作工具/Runner、CLI 私有配置与 M22 脚本离线测试。
- 文档与规格：README、ACTION_PLAN、两个现有 OpenSpec capability。
- 不新增依赖、持久状态字段、公开 CLI 参数、SubmitCandidate payload 或 Evaluator 权限。
