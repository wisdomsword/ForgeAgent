## Context

M23 的 `scripts/m23_mode_evaluation.py` 已实现严格协议校验、隔离工作区、Single/Duo/Triad 运行、审计投影、外部检查、原子 raw、完整性聚合和中立报告。其当前 schema 将单一 `model_id`、三个任务、三次重复和 27 个 run 固定在 M23 v2，正式证据位于 `docs/evaluation/m23/`。

M25 要把样本扩大到九个任务、两个模型和五次重复，同时保持 M23 协议与所有历史证据逐字节不变。完整批次包含 270 个真实 run，必须允许中断后按固定 identity 续跑，并在不完整时拒绝聚合。

## Goals / Non-Goals

**Goals:**

- 提供独立的 `forgeagent.m25.mode-evaluation/v1` 协议和 `docs/evaluation/m25/` 证据根。
- 保留三个 M23 基线任务，新增 bugfix、feature、refactor 三个真实编程任务族，每族两个任务。
- 固定 `claude-haiku-4-5`、`gpt-5.4-mini`、五次重复及确定性顺序，生成 270 个唯一 run。
- 保留 M23 全部质量、成本、调用、延迟与 usage 完整性口径，并增加模型、路由和任务族维度。
- 保持运行时、credential、模型注册和依赖不变。

**Non-Goals:**

- 不修改 M23 的 protocol、raw、environment、summary、report 或无效批次。
- 不生成显著性检验、综合分数、winner、自动排名或产品默认模式建议。
- 不把真实 provider 调用加入 CI，不声称本机结果代表其他平台或未来模型权重。
- 不引入通用 benchmark 框架、数据库、并发调度器或新依赖。

## Decisions

### 1. 独立协议与证据命名空间

M25 使用独立 schema、协议文件和输出根。每份 raw 同时绑定协议 hash、环境 hash、模型 ID、provider route hash、任务族和 RunSpec hash；M25 聚合器拒绝任何 M23 schema 或跨协议、跨环境、跨路由记录。M23 文件不迁移也不重写。

备选是直接把 M23 protocol 升级到 v3；这会让历史命名空间与新证据混合，故拒绝。

### 2. 向后兼容扩展现有 harness

保留 M23 CLI 和 v2 行为，通过最小的通用数据模型与分支支持 M25 v1，而不是复制约千行执行与安全逻辑。M23 的现有 53 项合同继续作为兼容门禁；M25 新测试只覆盖新增 schema、模型维度、任务族、排程和分层汇总。

若直接扩展使 M23 代码出现重复分支，则只提取纯函数/通用模型，不新增 factory、manager 或第三方库。不得修改协作运行时来迁就评估。

### 3. 固定任务矩阵

M25 protocol 含九个任务：三个 M23 基线任务原样复制到新协议，另外六个任务以小型多文件 Python 项目 fixture 表达：

- `bugfix`：边界/状态错误与跨模块数据处理错误；
- `feature`：在既有 API 上实现有明确验收的功能；
- `refactor`：在保持行为和公开接口的前提下重组现有实现。

每族包含两个任务，至少一个任务涉及多个源文件。所有任务仅用 Python 标准库和仓库已有测试工具；初始 fixture、不可变文件、候选文件和外部检查均写入固定协议。完成仍定义为 runtime completed 且所有模式无关检查、fixture integrity 和 artifact 检查通过。

备选是直接从当前 ForgeAgent 源树抽取任务；这会引入许可证、版本漂移和 fixture 体积问题，故采用自包含的小型真实项目。

### 4. 两模型与顺序平衡

两个模型都承担每个角色，生成与执行设置保持同一协议声明；能力适配仍由现有 client 完成。preflight 分别解析并哈希 `[model_id, client_kind, base_url-or-provider-default]`，不保存 base URL 或 credential。

排程遍历九个任务、两个模型和五次重复；每次包含三种模式。三种 Latin 轮换顺序按“任务 × 模型”单元偏移，使全部 18 个单元上的模式位置计数相等。模型先后顺序也按任务和重复确定性交替，减少单一路由持续集中在批次前半段。协议和测试固定完整 270-run 顺序。

### 5. 安全续跑与严格聚合

每个 run 使用包含 model slug 的稳定文件名和独立临时工作区。已有 raw 必须通过完整 schema、identity、hash 和环境绑定校验后才能跳过；冲突记录使运行停止。每次终态原子写入 raw；聚合只接受 270/270 的完整集合，不提供 partial-summary 开关。

环境清单记录两个模型的安全 route hash、内置 registry/config hash、提交、tracked dirty、平台和固定参数。真实运行前要求 tracked 源码干净；本 change 规划/证据文件的预期状态按协议记录，不把无关未跟踪文件混入 environment 判定。

### 6. 分层且中立的输出

`summary.json` 的主要分母按模型和模式分开，并提供 task family 与 task 的样本计数及同口径指标。`report.md` 展示每个模型下的 Single/Duo/Triad 描述性数据以及各任务族结果，不计算跨模型综合分数，不包含 `rank`、`winner`、`best` 或优越性结论。

所有 M23 指标继续记录：solved、first acceptance、rejection/correction、input/output/cached/reasoning tokens、logical calls、provider attempts、端到端延迟和 usage missing rate；Single 的验收循环指标继续为 N/A。

## Risks / Trade-offs

- [270 次真实运行带来显著费用与耗时] → 固定上限、原子 raw 和严格续跑避免重复付费；preflight 与离线合同先通过后才调用 provider。
- [五次重复无法在单个任务/模型单元内让三个位置完全等频] → 在 18 个单元间轮换偏移，使全批次位置分布精确平衡，并保留每个 run 的顺序。
- [两个 provider 的服务端权重和负载不可固定] → 记录 UTC、commit、模型 ID、route hash、attempt、latency 和限制说明，只给描述性结论。
- [真实编程 fixtures 可能泄漏答案或偏向某种模式] → 任务目标只暴露公开合同；外部检查固定且模式无关；两轮离线任务审计检查可解性、歧义和检查强度。
- [兼容扩展可能回归 M23] → M23 protocol hash、正式证据文件 hash、现有专项测试和独立复算均作为回归门禁。
- [本机无第二路由 credential] → preflight 在任何模型调用前失败并报告缺失的模型路由；不得用单模型不完整集合替代正式报告。

## Migration Plan

1. 保存 M23 受保护文件 hash 基线并建立离线回归合同。
2. 先以测试驱动扩展 schema、排程、identity、环境和聚合逻辑。
3. 编写 M25 固定协议与六个任务 fixture，运行全部离线协议和安全测试。
4. 在源码提交且 preflight 通过后执行 270 次真实 run；可安全中断和续跑。
5. 只在 270 份 raw 完整后聚合、独立复算并生成中立报告。
6. 验证失败时保留 raw 供审计但不发布不完整汇总；回滚只删除未归档的 M25 新证据，不触碰 M23。

## Open Questions

无。任务规模、模型、重复数、真实批次授权和中立报告边界均已确认。
