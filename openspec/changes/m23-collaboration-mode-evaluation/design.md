## Context

现有 Single、Duo、Triad 都可通过公开的 Task/CollaborationRunner 组装运行，并通过 audit 事件提供逐次模型调用的 usage。CLI 面向人工交互，不适合冻结参数、自动确认 Triad 计划或生成结构化多轮证据；协作运行时本身也不应为了评估而增加产品行为。

评估的主要偏差风险来自任务、模型、执行顺序、环境、产物判定和指标分母不一致。另一个风险是把 Single 没有 Evaluator 的事实编码为零拒绝或百分百首次通过，从而制造不可比数字。

## Goals / Non-Goals

**Goals:**

- 用版本化 JSON 协议固定 3 个确定性编程任务、3 次重复、轮换模式顺序、同一模型 ID、同一生成参数、同一隔离环境和外部产物检查。
- 用独立 Python harness 直接组装现有公开 Task/CollaborationRunner，采集原始运行记录并生成可复算聚合结果。
- 覆盖任务完成率、首次验收通过率、rejection/correction 次数、四类 token、逻辑模型调用次数、端到端延迟和 usage 缺失率。
- 明确保留样本数、分母、失败原因和 N/A，不自动排序模式或得出 Triad 更优的结论。

**Non-Goals:**

- 不修改协作运行时、角色提示词、CLI 产品入口或模型客户端。
- 不新增或改变 credential 来源、配置回退或密钥管理。
- 不把 M23 变成统计显著性研究、性能压测或长期 CI 门禁。
- 不保存 prompt、模型回复正文、环境密钥或其他敏感内容。

## Decisions

### 独立 harness，而非 CLI shell 或运行时子命令

新增 `scripts/m23_mode_evaluation.py`。它复用公开 Task、CollaborationRunner、模型注册表和 audit 协议，但在仓库运行时包之外负责协议加载、临时工作区、调度、外部检查、原始记录和聚合。相比 shell 驱动 CLI，这避免交互式计划确认和文本解析；相比新增 `forgeagent evaluate`，它不扩大产品接口或协作运行时范围。

### 固定协议和轮换顺序

`docs/evaluation/m23/protocol.json` 固定：

- 模型 ID `claude-haiku-4-5`，并记录模型注册表文件哈希；所有角色使用同一 ID。
- `max_output_tokens=4096`、`temperature=0`、`thinking=off`、`effort=null`、`timeout_seconds=120`、`max_rounds=10`、`max_rejections=2`。
- `restricted` tier、关闭 memory/identity/skills/MCP、临时工作区、自动同意受工作区边界保护的文件操作和 Triad 计划。
- 3 个只依赖标准库/仓库测试依赖的确定性任务，每个模式重复 3 次。
- 每个任务显式冻结 immutable fixture；候选检查在受限 worker 同一进程内执行，随后独立比较 fixture 字节。
- 每个任务按 Latin-square 风格轮换 `single/duo/triad` 首后顺序，降低时间漂移对单一模式的系统偏置。

协议以 SHA-256 标识。每个运行记录协议哈希、git commit、Python/平台信息、模型注册表哈希和固定参数；协议或环境不匹配时 harness 在模型调用前失败。`run` 和 `aggregate` 都只允许写入规范化的固定输出根，并拒绝 `..` 或符号链接祖先。

### 模式外完成判定与适用性

每个任务在独立临时工作区执行。运行结束后，无论模式内部状态如何，都执行同一个版本化外部检查。`solved` 只有在运行状态完成且全部外部检查通过时为真。

外部检查不得在 restricted check worker 内再次创建进程。需要执行候选 CLI 脚本时使用同进程 `runpy`，并在检查结束后把协议声明的 immutable fixture 与初始字节逐一比较；fixture 缺失、替换为符号链接或内容变化均使运行失败。

- `first_acceptance_passed`：仅 Duo/Triad 适用，表示第一次 Generator 候选被内部 Evaluator 接受；Single 为 `null`。
- `rejection_count` 和 `correction_count`：仅 Duo/Triad 适用；correction 是拒绝后新增的 Generator 尝试，Single 为 `null`。
- 原始记录保留模式状态与外部检查结果，避免将内部接受误当成任务完成。

### 调用、usage 与延迟口径

注入只在内存收集安全 audit 字段的 sink。`total_model_calls` 按 `llm.outcome` 逻辑调用计数；provider attempt 数另存为诊断字段，不替代主指标。每个有效 usage 必须包含非负整数的 input/output/cached/reasoning 四字段；缺失或无效视为该调用 usage 缺失。`usage_missing_rate` 的分母为逻辑模型调用数，零调用时为 `null`。

端到端延迟使用单调时钟，从模式运行开始到外部检查结束，包含协作轮次和产物验证。token 汇总只累加有效 usage，另保留缺失调用数，避免用零掩盖未知值。

### 证据布局与中立报告

每个运行完成后原子写入一个 `raw/*.json`，便于中断恢复；汇总器仅从这些原始文件复算 `summary.json` 和 `report.md`。原始记录只包含安全元数据、数值、状态、检查结果和产物哈希，不包含 prompt、回复正文或 credential。

报告按模式列出样本量、完成/首次验收/usage 分母、比例、token、调用数、rejection/correction 和延迟分布。模板禁止 winner/ranking/recommendation 字段，并固定写明“小样本描述性结果，不自动宣称 Triad 优于 Single”。

## Risks / Trade-offs

- [真实模型具有随机性且三次重复样本很小] → 固定协议、多轮重复、轮换顺序并只做描述性报告，不推断显著性。
- [canonical model ID 仍可能由服务端更新] → 记录 ID、注册表哈希、运行时间和环境指纹；报告明确这不是服务端权重哈希。
- [provider 不返回 usage] → 记录调用级缺失率和分母，不把缺失字段当零。
- [外部检查超时或异常] → 每项检查有固定超时，异常成为失败记录而不中断其他已排定运行。
- [真实运行可能因 auth/network 阻塞] → harness 在正式调度前做安全 preflight；失败不伪造评估结果，报告阻塞原因。
- [直接复用公开组装 API 可能随项目演进变化] → 离线合同测试覆盖协议、指标与记录结构；M23 不为未来兼容增加抽象层。

## Migration Plan

这是新增的仓库评估资产，无产品数据迁移。回滚时删除 harness、协议和 M23 证据即可，运行时行为不受影响。

## Open Questions

无。任务数、重复次数、模型、参数、环境、指标口径和非目标均在协议中冻结。
