## Why

ForgeAgent 的单角色完成判定仍由执行任务的 Generator 自我声明；即使 M13 已修正完成声明的时机，错误产物仍可能被同一会话误判为完成。M22 需要把规划、生成与验收拆成隔离角色，并以冻结、可验证的任务契约和独立 Evaluator 结果决定协作模式的完成状态。

## What Changes

- 新增运行时 Duo 模式：Generator 提交后由独立 Evaluator 以只读产物访问权验收；失败证据有界打回 Generator，超过配置的打回次数后以逐项报告停止。
- 新增运行时 Triad 模式：Planner 先生成只描述可观察行为与验收标准的冻结清单，经确认后由 Generator 逐项实现、Evaluator 逐项验收；清单不得静默删项或降标。
- 新增确定性编程任务路由：显式 `/duo`、`/triad` 与 `--mode` 保留；直接指定的编程类任务至少进入 Triad，无法安全确认的 headless 请求必须使用服务端预授权策略或拒绝。
- Duo/Triad 下 Generator 的 `completed` 仅表示提交验收，最终 `completed` 由 Evaluator 判定；普通单角色 Task 的完成语义和公开结果字段保持兼容。
- CLI、REPL、既有 HTTP `/tasks` 与 Loop 入口接入同一协作模式、预算、确认和安全投影；不新增 endpoint、daemon、数据库或第三方编排依赖。
- 新增角色生命周期、确认、打回与终态审计事件；只记录稳定枚举、计数、模型标识和清单摘要，不记录目标、清单正文、反馈正文、工具参数、文件内容或 secret。
- 新增离线 mock replay、路由表、清单完整性、打回边界与普通路径隔离测试；真实模型质量对比保持显式 opt-in。

## Capabilities

### New Capabilities

- `runtime-collaboration`: 定义 Duo/Triad 角色隔离、冻结计划、独立验收、证据打回、预算停止、完成语义与兼容性边界。

### Modified Capabilities

- `completion-integrity`: 协作模式下 Generator 完成声明降级为提交验收，只有独立 Evaluator 通过才能形成最终完成状态。
- `repl-interactive-input`: 增加 `/duo <goal>` 与 `/triad <goal>`，并保持 slash 候选、帮助、历史与普通输入行为一致。
- `http-task-service`: 既有 `/tasks` 请求可选择协作模式并执行 headless Planner 确认策略，同时保持普通 Task/Loop 请求兼容。
- `loop-execution`: Loop 可冻结协作模式并复用 checkpoint/handoff 作为角色交接载体，恢复时不得改变计划或降级模式。
- `audit-logging`: 增加有界、脱敏的协作角色生命周期、计划确认、打回与终态事件。

## Impact

- 主要影响 Task 上层的新协作编排模块、角色提示词组合、CLI/REPL、HTTP task service、Loop 装配、配置和审计投影。
- 复用现有 `Task`、M20 Evaluator 的外部可观察验收原则、M21 checkpoint store、模型注册表、sandbox、Memory/Skills 与确认门；不修改 Provider client 或 Step 工具反馈状态机。
- Duo/Triad 会增加模型调用、token 成本和延迟，因此默认只对显式模式及确定性识别的编程任务启用；其他任务继续单角色直通。
- 基础 CI 保持无 API key 可运行，普通 Task、20 项 trusted golden core 与 M20 opt-in Evaluator 的既有契约保持不变。
