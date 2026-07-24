## Why

ForgeAgent 目前只能把一次 `Task` 执行到终态；长任务被进程中断后无法从耐久状态续接，也没有统一的 token、墙钟和连续失败停止预算。M21 需要在不改变现有 `Step` 单任务反馈语义、也不提前引入 M22 多角色验收的前提下，增加一个可由 CLI、HTTP 和操作系统调度器触发的轻量持久化 Loop。

## What Changes

- 新增 Task 之上的 Loop 控制层：按迭代调用现有 Task，持久化进度、未解问题、交接反馈、预算消耗和终态报告。
- 新增原子 checkpoint 与显式 resume；恢复时校验版本、任务身份和配置兼容性，并保证已提交完成的迭代不重复执行。
- 新增统一停止条件：迭代/轮次上限、累计 token 预算、任务级墙钟预算、连续失败上限和协作取消；任一命中均写入可诊断终态。
- 新增失败收敛反馈：可恢复失败的有界摘要进入下一迭代，不可恢复失败或预算耗尽立即停止，禁止无限重试。
- 新增 `forgeagent loop` CLI 入口，并让现有 HTTP 任务提交接口可选地启动或恢复 Loop；普通 `run`、REPL、serve 单任务语义保持不变。
- 新增本地 cron/launchd/systemd 触发示例和一个只产出报告、不自动创建 PR 的端到端 Loop 示例；不内置 scheduler 守护进程。
- 新增 Loop 生命周期审计事件和离线确定性测试；M20 Evaluator 保持显式 opt-in，不自动接入普通 Task 或 Loop。

## Capabilities

### New Capabilities

- `loop-execution`: 定义持久化 Loop 的触发、checkpoint/resume、预算停止、失败收敛、终态报告和兼容性边界。

### Modified Capabilities

- `http-task-service`: 现有任务提交请求新增可选 Loop 启动/恢复模式，同时保持普通任务请求和响应兼容。
- `audit-logging`: 增加有界、脱敏的 Loop 生命周期与 checkpoint 审计事件，不记录 checkpoint 正文或敏感配置。

## Impact

- 主要影响 `Task` 之上的新 Loop 模块、CLI 装配、HTTP task service/server 和审计事件投影；`Step` 的轮内协议、工具执行和完成判定不改变。
- checkpoint 只写入用户指定或配置允许的项目根目录，采用版本化 JSON 和原子替换；不引入数据库、常驻服务、新依赖或自动工作树管理。
- HTTP 保持原有 endpoint，通过可选请求字段选择单任务或 Loop；现有调用方无需修改。
- 离线 CI、20 项 trusted golden core 和真实模型显式 opt-in 成本边界保持不变。
