---
comet_change: m25-programming-mode-evaluation
role: technical-design
canonical_spec: openspec
---

# M25 编程模式质量—成本评估技术设计

## 1. 背景与边界

M23 已证明固定协议、隔离运行、外部检查、安全 raw 和可复算报告可以对 Single、Duo、Triad 产生中立证据，但它只有三个任务、每组合三次重复、`claude-haiku-4-5` 单模型和一条 provider 路由。M25 在评估层扩充任务、重复和模型维度，不修改协作运行时，也不回写 M23 的任何历史文件。

规范事实源是 OpenSpec delta spec。本文只细化实现、数据流、失败语义和测试策略。

### 目标

- 独立固定 `forgeagent.m25.mode-evaluation/v1` 协议；
- 九个任务，其中保留三个 M23 基线任务并增加六个真实编程任务；
- `claude-haiku-4-5` 与 `gpt-5.4-mini`，每个任务—模型—模式五次重复；
- 完整 270-run、可中断续跑、只从完整 raw 复算；
- 记录完成、首次通过、rejection/correction、四类 token、调用、attempt、延迟和 usage 缺失；
- 分模型、模式、任务族和任务报告，不自动排名。

### 非目标

- 不修改 `src/forgeagent/`、模型注册、credential 语义或产品 CLI；
- 不增加 benchmark 框架、数据库、并发执行、统计显著性或综合评分；
- 不让真实 provider 调用成为 CI；
- 不把本机、当前日期和当前服务端权重的结果外推为长期产品结论。

## 2. 方案比较

### 方案 A：现有 harness 内向后兼容扩展（采用）

`scripts/m23_mode_evaluation.py` 继续保留 M23 v2 的严格模型和行为，新增 M25 v1 严格模型与 schema 分派；执行、检查、audit、安全写入和统计函数通过少量 helper 同时消费两种协议。

优点是 diff 最小、已审计路径复用最多、M23 专项直接充当回归门禁。缺点是文件名仍带 M23，且需要谨慎隔离两套序列化模型。文件名属于内部评估工具，不值得为命名做迁移。

### 方案 B：抽取共享 core，M23/M25 双入口

把当前脚本拆成通用模块和两个薄 wrapper。边界更整齐，但会产生大规模机械移动、导入兼容和历史命令迁移，增加与本次证据扩充无关的风险。只有方案 A 实现后出现明显重复时，才局部提取纯函数。

### 方案 C：复制 M25 harness

M23 完全不动，但会复制约千行安全、执行和聚合代码，后续修复容易漂移。拒绝。

## 3. 兼容数据模型

### 3.1 M23 类型保持不变

以下现有模型的字段、默认值、alias 和 `model_dump()` 结果不得改变：

- `EvaluationProtocol` / `TaskSpec` / `RunSpec`；
- `EnvironmentManifest`；
- `RawRecord` 及其嵌套记录。

原因是 M23 protocol hash、RunSpec hash、environment hash 和正式 raw 校验都依赖其 canonical JSON。向这些类加入值为 `None` 的可选字段也会改变序列化，不能接受。

### 3.2 M25 严格类型

新增独立模型：

- `M25TaskSpec`：在 M23 任务合同等价字段之外增加 `family`，值固定为 `baseline | bugfix | feature | refactor`；
- `M25EvaluationProtocol`：schema 固定，`model_ids` 精确包含两个唯一模型，`repetitions=5`，`tasks` 精确九个，声明三种 Latin `mode_orders`；
- `M25RunSpec`：`sequence, task_id, task_family, model_id, repeat, mode`；
- `M25ModelRoute` 与 `M25EnvironmentManifest`：每个模型一份 `client_kind`/route 安全 hash，不保存连接值；
- `M25RawRecord`：独立 raw schema，并绑定 `model_id`、`provider_route_sha256` 和 `task_family`；
- M25 summary 模型继续用普通 canonical dict 输出，但由离线 schema/键集合测试约束。

`validate_protocol()` 先读取原始 dict 的 `schema`，只允许 M23 v2 或 M25 v1，然后调用对应 Pydantic 模型。未知 schema 在任何模型解析或 route resolution 前失败。`load_protocol()` 对对应模型的完整 JSON 求 hash，因此 M23 digest 保持不变。

### 3.3 最小共享 helper

只增加调用点真正需要的 helper：

- `protocol_model_ids(protocol)`；
- `run_model_id(protocol, run_spec)`；
- `run_task_family(run_spec)`；
- `protocol_namespace(protocol)`；
- `route_hash_for_model(environment, model_id)`。

不新增 factory、adapter、manager 或依赖。若一个函数只服务 M25 且不减少重复，直接写普通函数。

## 4. 固定协议与任务族

### 4.1 协议位置

新协议固定在 `docs/evaluation/m25/protocol.json`，schema 为 `forgeagent.m25.mode-evaluation/v1`。M23 的 `docs/evaluation/m23/protocol.json` 及证据树逐字节保持不变。M25 CLI 必须显式接收 M25 protocol 和 M25 output root；schema 与根不匹配时拒绝。

两个模型共享相同的协议级生成设置：`max_output_tokens=4096`、`temperature=0`、`thinking=off`、`effort=null`、`timeout_seconds=120`。client capability gating 仍在现有 client 内完成；harness 不按 provider 拼参数。

执行设置继续使用 restricted、`max_rounds=10`、`max_rejections=2`、identity/memory/skills/MCP 关闭、plan preauthorize 和 30 秒检查 timeout。成本上界由 270 个 run 以及这些调用上限约束，不声明无法可靠计算的美元上限。

### 4.2 九个任务

三个 baseline 任务从 M23 protocol 原样复制目标、fixture 和检查，M25 只增加 `family=baseline`。

六个新增任务采用自包含小型 Python 项目：

| ID | Family | 任务形态 | 关键验收 |
|---|---|---|---|
| `fix-ttl-expiration-boundary` | bugfix | 修复 cache 到期边界，单模块 | 精确时钟边界、命中与淘汰 |
| `fix-invoice-discount-composition` | bugfix | 修复跨模块折扣组合，多文件 | 顺序、上限、舍入与原 API |
| `add-topological-batches` | feature | 为依赖图增加批次 API，多文件 | 稳定顺序、孤立节点、环检测 |
| `add-jsonl-dead-letter-output` | feature | 扩展事件处理 CLI，多文件 | 正常输出、坏行收集、退出码 |
| `refactor-notification-routing` | refactor | 重组路由规则，多文件 | 公开 API 与全部行为不变 |
| `refactor-config-precedence` | refactor | 拆分配置合并实现，多文件 | defaults/file/env/CLI 优先级不变 |

每个 fixture 包含待修改实现、公开测试或示例和独立检查脚本。目标描述明确允许修改的候选文件与不可修改的合同文件。外部检查只使用当前 Python 和仓库已有 pytest；不联网、不安装包、不读取其他 run。至少一个初始检查必须失败，参考解必须通过，才能进入真实批次。

检查输出仍只保存状态、exit code、duration、UTF-8 字节数和 SHA-256，不保存正文。fixture integrity 对所有 `immutable_files` 做字节 hash。

## 5. 270-run 排程

定义三个 Latin 顺序：

1. Single, Duo, Triad；
2. Duo, Triad, Single；
3. Triad, Single, Duo。

稳定 task index 为 `t∈[0,8]`，稳定 model index 为 `m∈[0,1]`，repeat index 为 `r∈[0,4]`。该单元使用的顺序为：

```text
mode_order = mode_orders[(2*t + m + r) mod 3]
```

18 个任务—模型单元在模 3 上各有六个，因此五轮后每个 mode 在三个位置各出现 `6×5=30` 次。模型执行先后在每个 task/repeat 上按 `(t+r) mod 2` 正反交替，但 `m` 始终使用协议中的稳定 index，避免先后顺序改变 mode offset。

循环顺序为 task → repeat → 当轮 model order → mode order。最终 270 个 `M25RunSpec` 依次编号；测试断言长度、集合唯一性、每任务—模型—模式恰好五份、每模型 135 份、每模式 90 份、每位置 30 份和固定前后切片。

run ID 与 raw 文件名包含三位 sequence、task ID、模型安全 slug、repeat 和 mode。RunSpec hash 包含全部六个字段和 protocol hash。模型 slug 只允许由模型 ID 的 `[a-z0-9-]` 规范化结果生成；冲突在协议验证时拒绝。

## 6. 执行与环境数据流

```text
protocol.json
  → schema dispatch + strict validation
  → resolve two model routes + safe route hashes
  → environment.json bind/compare
  → deterministic 270-run schedule
  → isolated workspace + fresh client/Task per role
  → external checks + fixture/artifact hashes
  → atomic M25 raw record
  → strict complete aggregation
  → summary.json + report.md
```

`run_single()`、role task factory 和 collaboration runner 从 `M25RunSpec.model_id` 取模型；M23 路径继续从 `protocol.model_id` 取值。Task/collaboration ID 使用 protocol namespace 与足够位数的 sequence/hash，继续满足公开 API 的 canonical ID 合同。

preflight 在任何 provider 调用前完成：

1. schema、任务、排程和 output root 校验；
2. 两个模型均能唯一 resolve，credential 非空；
3. 每条 route 计算安全 hash 后丢弃 base URL 原文；
4. git commit 可解析且 tracked source clean；
5. environment 已存在时稳定字段完全相等；
6. 已有 raw 要么完整匹配当前 identity，要么立即冲突失败。

每个逻辑 run 仍串行执行，避免并发改变 provider 限流、延迟口径和本机资源竞争。SIGINT/进程退出后已原子落盘的 raw 可复用；当前未完成 run 没有终态文件，续跑时从该 run 重做。

## 7. 完整性与聚合

M25 aggregator 先由 protocol 构造 270 个期望 identity，再逐个加载 exact 文件名。它拒绝：

- 缺失、额外、重复或无法解析的 raw；
- M23/未知 schema；
- protocol/environment/RunSpec hash 混杂；
- model ID 与 route hash 不匹配；
- task family 与 protocol 不匹配；
- run ID、sequence 或文件名不一致；
- 非终态记录。

完成后输出：

- `models[model_id].modes[mode]`：所有既有指标；
- `families[family].models[model_id].modes[mode]`：同口径 family 切片；
- `tasks[task_id].family` 和每模型/模式样本与指标；
- 完整性、失败 run、usage gap、protocol/environment hash 和 limitations。

usage missing rate 始终以 logical calls 加权，而非 run 平均。token 只汇总 usage 完整的 call；未知值不补零。Single 的 first acceptance、rejection、correction 保持 null/N/A。

报告逐模型展示模式，再展示 family/task 切片。禁止键名和文本包含自动决策语义：`rank`、`ranking`、`winner`、`best_mode`、`superior`。任务 ID 中合理的普通词不受限制；测试针对 schema 键和结论模板，不做脆弱的全文件子串误报。

## 8. 错误处理与隐私

- route/credential/协议错误：调用前退出，固定错误分类，不创建 raw；
- provider/运行时错误：创建该 run 的终态 raw，保留稳定 `error_category`，不保存原异常正文；
- check timeout/failure：raw 保存安全投影并令 solved=false；
- 写入冲突：不覆盖，立即退出；
- 不完整批次：不写 summary/report；
- M23 文件变化：离线门禁失败，真实批次不得开始。

M25 raw 禁止包含 goal、prompt、messages、reply、body、text、api_key、base_url、environment 原文或绝对路径。任务源文件和检查输出正文不写入 raw；只记录 protocol 内已固定的 ID 与 hash。

## 9. 测试策略

### 9.1 M23 保护

- 现有 `tests/test_m23_mode_evaluation.py` 全部通过；
- checked-in M23 protocol digest 与 27-run 顺序不变；
- 正式 M23 protocol/environment/raw/summary/report 的文件清单和 SHA-256 manifest 不变；
- 对 M23 正式 raw 独立复算，结果继续等于现有 summary/report。

### 9.2 M25 TDD

新测试按失败优先覆盖：

- schema dispatch、严格字段、两个唯一模型、九个唯一任务、family 与 slug；
- 270-run schedule、位置平衡、identity/hash 和续跑；
- 双 route environment 与 secret/base URL 排除；
- 六个任务的初始失败、参考通过、immutable 与 artifact 边界；
- Single/Duo/Triad 各执行装配使用正确 model ID；
- 270 synthetic raw 的完整聚合、重复复算和每层分母；
- 缺失、额外、混合 M23、错误 route/family/filename 的拒绝；
- report 的 N/A、限制与无排名合同；
- raw/summary/environment 递归敏感键和值扫描。

### 9.3 真实证据门禁

真实调用前必须通过 M23/M25 专项、Ruff、OpenSpec strict、M23 hash manifest 和双 route preflight。完整批次后独立脚本从 raw 重算关键分母与 totals，不复用 report renderer。最后运行全量 pytest、golden 20/20、build、`git diff --check` 和两轮人工式数据审计。

## 10. 完成判定

只有同时满足以下条件才宣称 M25 完成：

- protocol 与实现提交绑定，tracked source clean；
- 270/270 terminal raw，任一任务—模型—模式恰好五份；
- 两个 route hash 各唯一且与 environment 绑定；
- summary/report 仅由完整 raw 生成并经独立复算一致；
- 所有要求指标均有明确分母，Single N/A 正确；
- 没有 prompt/reply/credential/base URL/绝对路径泄漏；
- 没有自动排名或优越性结论；
- M23 历史文件 hash 未变；
- 项目验证门禁通过并记录原始输出摘要。
