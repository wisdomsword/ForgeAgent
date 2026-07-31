## Context

ForgeAgent 的 `TrustedBackend` 在宿主进程执行 Python，`RestrictedBackend` 为每个 block 启动隔离 Python worker，`ContainerBackend` 通过一次性 Docker container 执行相同 JSON worker 协议。现有测试证明主要正确性与安全边界，但缺少同一入口生成的启动延迟、吞吐、恢复、结构、兼容和迁移证据。M32 定义了六项治理字段，M41 曾为 CLI 重构实际应用该结构；M43 将同一治理结构应用于执行后端替换的 readiness 判断。

当前约束是：不修改执行后端、不引入 Rust 或新依赖、不读取凭据、不访问网络、不把 Docker 不可用视为通过，并保持所有 M42 及更早契约不变。主工作区存在 M43 之前的用户改动，M43 只选择性归属自身文件。

## Goals / Non-Goals

**Goals:**

- 用一个标准库离线入口产生版本化 JSON 原始证据。
- 对六项指标分别固定 baseline、threshold、evidence、migration 和 rollback trigger。
- 区分 `measured`、`not_available` 和 `failed`，不把未运行场景算成通过。
- 产生 `keep_python`、`eligible_for_single_module_experiment` 或 `insufficient_evidence` 的有界 verdict。
- 让未来试验只能通过独立 change、单模块、保留旧路径并具备确定回滚条件进入。

**Non-Goals:**

- 不实现或脚手架化 Rust/FFI 后端，不修改 `executor.py` 或 worker 协议。
- 不新增依赖、配置、CLI 命令、运行时 schema、数据迁移或遥测。
- 不把本机微基准声明为跨平台 SLA，也不把计时阈值接成易抖动的 CI 失败门禁。
- 不执行 PyPI、tag 或发布自动化；普通分支 push 不是测量能力，但可按已授权的版本控制交接执行。

## Decisions

### 1. 使用标准库离线测量器和冻结 JSON 证据

新增 `scripts/m43_executor_rewrite_baseline.py`。父进程负责环境摘要、结构统计、后端测量、故障恢复和 verdict；计时使用 `time.perf_counter_ns()`，聚合使用 `statistics`。报告固定 schema 与六个 metric key，公开内容不包含绝对路径、环境值、代码正文、raw exception 或 subprocess 原始输出。

替代方案 A 是仅记录手工命令，改动最少但难以同口径复测；方案 C 是将绝对时间接成 CI 硬门禁，自动化更强但会被共享 runner 和平台差异误报。选择离线测量器，在测试中只验证结构和判定纯函数，真实计时仅作为评审证据。

### 2. 三条执行路径按可验证边界分层

- trusted 与 restricted 必须真实测量构造、简单 block 延迟和顺序吞吐。
- restricted 必须验证 worker 异常退出与 timeout 后的下一次执行仍成功，并以每个故障 block 各写
  一次临时哨兵、宿主最终只读到一个字节来观测没有重放；哨兵路径和代码正文不进入报告。
- container 只有 Docker daemon 和既定镜像本地可用时才真实测量；否则记录固定 `not_available` reason，不能进入性能比较或被计为可靠性通过。

不自动拉取镜像、不启动 daemon、不访问网络。容器缺证据不阻止建立 Python 主路径基线，但会让任何以 container 替换为目标的后续试验保持 `insufficient_evidence`。

### 3. 六项指标使用证据门与瓶颈门

每项指标都在 Markdown 基线表和 JSON evidence 中具备五个治理字段。performance、reliability、maintenance cost 用具体测量判断是否存在瓶颈；compatibility、team capability、migration/rollback risk 用可行性条件判断未来试验是否可控。

只有同时满足以下条件才输出 `eligible_for_single_module_experiment`：

1. 六项证据完整且没有 `failed`；
2. 至少一个真实使用相关的瓶颈阈值被越过；
3. compatibility、team capability、migration/rollback risk 三项均满足试验准入；
4. 对应边界有真实 verifier，不依赖未运行的 Docker 或推测数据。

否则输出 `keep_python`；关键证据缺失、测量失败或 metric status 不在对应固定词表内则输出
`insufficient_evidence`。该 verdict 只决定是否可以另建试验 change，不会切换运行时。

### 4. 阈值不伪装成跨机器 SLA

性能阈值写成当前硬件上的操作预算和同机复测规则，并保留原始样本。未来若越阈，必须在干净环境用同一命令复测一次且结合真实任务需求；单次微基准越界不够启动重写。可靠性要求正常执行与故障后恢复零控制面失败。维护、兼容、团队能力和回滚阈值分别约束新增复杂度、旧契约、维护所有权和旧路径保留。

### 5. M43 只交付测量能力和结论

测量结果、阈值表、验证报告和里程碑属于 M43。若 verdict 允许试验，后续仍必须建立新的 full Comet change，明确单一目标模块、migration、rollback 和平台 verifier；M43 不预建候选实现。

## Risks / Trade-offs

- [微基准受机器负载影响] → 保存原始样本和环境摘要，使用中位数/p95；越阈必须同机干净复测并绑定真实需求。
- [trusted 与 restricted 成本量级不同] → 分别报告，不用一个平均数掩盖隔离成本。
- [Docker 不可用造成证据缺口] → 固定标记 `not_available`，不拉取镜像，不把 skip 写成 pass。
- [脚本本身变成新框架] → 单文件标准库实现，只保留测量与纯判定函数，不新增通用 benchmark 抽象。
- [工作区既有改动被误归属] → M43 只选择性暂存新增/明确修改文件，最终 diff 按 base-ref 和文件归因双审。

## Migration Plan

M43 没有运行时迁移。先以测试锁定报告 schema、脱敏和 verdict，再运行真实测量并冻结 evidence，最后验证文档与 OpenSpec 契约。回滚 M43 只需删除其脚本、测试和文档；执行后端、配置、数据和依赖树均保持原样。

未来单模块试验必须保留当前 Python 路径为默认或显式 fallback，不迁移持久化状态；出现兼容失败、恢复失败、性能改善未达目标、维护者无法排障或回滚需要数据转换时立即停止并回退旧路径。

## Open Questions

无。真实数值和最终 verdict 由 build 阶段同口径测量决定，不在设计阶段预判。
