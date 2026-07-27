## Why

ForgeAgent 已具备 Single、Duo、Triad 三种运行模式，但目前缺少在同一任务、模型版本、生成参数和环境下进行多轮重复对照的可审计证据。M23 需要建立独立评估能力，用原始机器记录和聚合报告呈现质量、成本与可用性指标，而不是从单次样本或角色数量推断模式优劣。

## What Changes

- 新增仓库外层的独立评估 harness，按固定顺序重复运行 Single、Duo、Triad，不修改协作运行时。
- 版本化固定任务、模型版本、生成参数、执行环境、重复次数与产物检查，并记录协议摘要和环境指纹。
- 为每次运行保存不含 prompt、回复正文或密钥的原始机器记录，覆盖完成状态、外部产物检查、验收循环、token、模型调用、延迟和 usage 完整性。
- 生成按模式聚合的机器报告与人工可读报告，明确分母、N/A 语义和小样本限制，不自动排名或宣称 Triad 优于 Single。
- 保持 credential 加载、CLI 产品入口和协作运行时行为不变。

## Capabilities

### New Capabilities

- `collaboration-mode-evaluation`: 固定协议、多轮执行、原始记录、聚合指标和中立报告的 Single/Duo/Triad 独立评估能力。

### Modified Capabilities

无。

## Impact

- 新增 `scripts/` 下的评估 harness、`tests/` 下的离线合同测试，以及 `docs/evaluation/m23/` 下的协议和评估证据。
- 更新 `README.md`、`ACTION_PLAN.md` 和 M23 里程碑记录。
- 不新增运行时依赖，不修改 `src/forgeagent/collaboration.py`、credential 配置或现有运行模式接口。
