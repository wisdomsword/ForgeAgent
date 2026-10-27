## Why

M25 的冻结评估显示，当前“编程任务自动 Triad”策略没有稳定带来更高完成率，却显著增加模型调用、延迟和 token 成本；M26 又证明 Triad 只有在宿主提供并绑定当前 Candidate 的冻结检查时，才能避免自报通过造成的误完成。继续把普通编程任务无条件升级为 Triad，会把尚未证明的收益当成默认产品策略。

同时，README 仍把项目 MEMORY 描述为只读身份文件，与 M18 已交付的可写、可审计 Memory runtime 不一致；公开验证基线与平台文档仍停留在 M24 数字，Linux verified 状态说明还含过期矛盾。M27 需要一次性校准运行时合同与派生证据，避免路由、Memory 和公开报告继续分叉。

## What Changes

- **BREAKING**：编程任务不再自动升级为 Triad；未显式选择模式且宿主未提供冻结检查时统一使用 Single。
- 用户显式选择 `single`、`duo` 或 `triad` 时直接尊重选择，不再要求“较弱模式覆盖”确认；兼容配置 `allow_weaker_override` 不再改变路由结果。
- 宿主在路由时提供非空冻结检查定义时，可把未显式选择模式的任务路由到 Triad；只有候选文件就绪要求不构成完成证据，不触发自动 Triad。
- 修正 README 的 Memory 行为说明：项目 `.forgeagent/MEMORY.md` 由 Memory runtime 在准入后原子更新，并可由用户直接编辑；`--no-identity` 仍按身份合同禁用所有自定义身份文件和 Memory，`--no-memory` 仍是只关闭 Memory 的独立开关。
- 基于已冻结的 M25 raw 记录生成新的派生分析，不改写协议、raw、environment、`summary.json` 或原中立报告；新增按 model/mode 和 task family 的误完成率、运行时终止原因分类，并同时呈现质量、延迟和调用成本，形成 M27 路由决策依据。
- 更新 README、ACTION_PLAN、当前 pytest/OpenSpec/Golden 基线和平台矩阵；保留 M24 历史 container 运行的 Linux Docker verified 证据，并删除“仍 configured”的过期矛盾描述。

## Capabilities

### New Capabilities

- `collaboration-routing-evaluation`: 定义如何从冻结 M25 证据派生误完成率、终止原因、质量、延迟和调用成本，并约束这些派生指标对自动 Triad 策略的使用边界。

### Modified Capabilities

- `runtime-collaboration`: 将默认路由改为 Single，显式选择直接生效，只有宿主冻结检查证据可触发自动 Triad。
- `continuous-verification`: 当前基线必须来自最新可复验结果，平台 verified 状态必须与已记录执行证据保持一致且不得出现自相矛盾的状态描述。

## Impact

- 运行时：`src/forgeagent/collaboration.py` 及 CLI/HTTP/Loop 路由装配。
- 测试：协作路由、CLI/HTTP/Loop 集成、持续验证合同和 M25 派生分析测试。
- 评估：新增只读派生脚本与 M27 派生报告；M25 原始证据树保持字节不变。
- 文档：README、ACTION_PLAN、平台矩阵、运行时协议、威胁模型和 M27 里程碑。
- 不新增第三方依赖，不修改 M26 冻结证据，不重跑或覆盖 M25 真实模型批次，不自动恢复任何任务类别的 Triad 默认路由。
