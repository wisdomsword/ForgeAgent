## Why

Duo 当前把任意 goal 固定成“原始目标已满足”，Evaluator 无法从该验收项知道应观察什么证据。M39 需要在不引入 LLM 拆解器或新依赖的前提下，让默认 Duo 计划成为确定、可冻结、可直接检查的验收契约。

## What Changes

- `_duo_plan(goal)` 根据 goal 的可观察交付形态选择固定验收模板，而不再丢弃入参。
- 保持单个稳定计划项 ID，避免破坏既有持久化状态和 SubmitEvaluation 覆盖契约。
- 文件/产物、命令/验证、文本/分析三类 goal 分别得到可由 Evaluator 直接观察的 behavior 与 acceptance。
- 禁止“原始目标已满足”“满足用户需求”等循环论证式伪验收。
- 增加至少三个 Duo golden case，覆盖三类交付形态和路径/secret 不泄漏边界。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`：Duo 默认验收计划必须由 goal 的交付形态确定性生成，并包含可直接观察的证据契约。

## Impact

影响 `src/forgeagent/collaboration.py`、Duo store/runner 测试与协作规范。不改变 Triad Planner，不新增依赖、LLM 调用、配置项或发布动作。
