# Proposal

## Why

真实 Duo/Triad 验收发现 restricted worker 的 `import unittest` 无法发现标准库子模块。解释器库文件可读取，但首次导入需要的目录枚举被拒绝，导致生成任务无法运行测试。

## What Changes

- 为普通 restricted worker 配置解释器目录的只读枚举，与现有 evaluator check worker 采用相同策略。
- 补充冷启动标准库导入、项目 unittest 执行、越界枚举与解释器目录写入拒绝回归。
- 在新目录重跑相同模型与固定任务的 Duo/Triad，保存原失败记录和复验结果，通过后本地提交。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `tool-approval`: restricted 执行支持受信任解释器目录的只读模块发现，保持其余隔离边界。

## Impact

仅涉及 `_sandbox_worker.py` 的执行入口、restricted 回归测试及验证文档；无新依赖、公共 API、provider 路由或发布动作。
