## Context

M21 为具备编程特征的目标引入了确定性的自动 Triad 路由。M25 随后冻结了 Single、Duo、
Triad 共 270 次真实模型运行；M26 又增加了宿主拥有的冻结检查，把 Evaluator 裁决绑定到当前
Candidate。当前默认行为仍会在不知道是否具备这类证据时升级编程任务，并要求用户确认才能采用
显式选择的较弱模式，同时暴露 `allow_weaker_override` 兼容配置。

M25 raw 是不可变的历史证据。M27 可以从中生成新派生分析，但不得修改 protocol、raw、
environment、summary 或原中立报告。公开文档另有三处陈旧状态：MEMORY 被描述为只读、当前
测试基线仍停留在 M26 之前、Linux 表格在证据未同时记录两种架构时宣称 `amd64/arm64`，且同一
文档末尾仍残留 Linux 为 `configured` 的旧结论。

## Goals / Non-Goals

**目标：**

- 用户未选择模式且宿主没有绑定非空冻结检查时，一律默认 Single。
- 用户显式选择 Single、Duo 或 Triad 时直接尊重选择。
- 可信宿主拥有冻结检查定义时，可以不依赖模型或文本分类器选择 Triad。
- 生成可复算、加法式的 M25 派生结果，覆盖误完成、终止原因、质量、延迟与调用成本，并记录
  M27 路由裁决。
- 修正文档中的 MEMORY、当前基线和 Linux 证据表述，不改变对应运行时和历史证据。

**非目标：**

- 不修改 M26 check runner、Evaluator 完成门禁或冻结检查安全边界。
- 不增加意图分类器、额外模型调用、新配置面或新依赖。
- 不重跑 M25，也不重写任何 M25 冻结产物。
- 不为 solved rate 未超过 Single 的任务类别恢复自动 Triad。
- 不改变 M18 Memory runtime 或 `--no-identity`、`--no-memory` 合同。

## Decisions

### 1. 只根据显式选择与宿主证据路由

`resolve_collaboration_mode` 保留已有 goal 和兼容关键字参数，并增加一个表示宿主是否绑定非空
冻结检查的布尔事实。解析顺序如下：

1. 显式 `single`、`duo` 或 `triad` 原样返回，原因为 `explicit`。
2. 未显式选择且存在冻结检查时返回 Triad，原因为 `bound_checks`。
3. 其他情况返回 Single，原因为 `default`。

原编程文本分类器不再参与路由。继续保留无效的私有策略会增加误用风险和正则复杂度，因此删除
对应常量与 helper。`allow_weaker_override` 为源码和配置兼容继续接受，但不再影响结果。
`ModeDecision.override_required` 保留在稳定报告形状中，新路由下始终为 false。

未采用的方案：

- 保留编程分类但令其输出 Single：仍维护一个不影响决策的复杂组件。
- 把候选文件要求当作证据：文件存在不能证明验收行为通过，会削弱 M26 边界。
- 让冻结检查覆盖显式 Single 或 Duo：这与尊重用户显式选择冲突。

### 2. 路由器只接收证据事实

路由器只接收布尔值，不接收检查 argv、环境、路径、输出或快照。可信宿主仍负责创建并向 M26
runner 注册 `CheckDefinition`。这样可以保持路由审计有界，并避免 mode resolver 变成第二个
检查注册表。现有 CLI、REPL、Loop 和 HTTP 在初始路由点都没有冻结检查，因此普通默认行为变为
Single；已经拥有冻结检查的 library 或 harness 宿主可以传入该事实，显式模式始终优先。

### 3. 从不可变 M25 raw 派生 M27 指标

一个仅用标准库的脚本读取冻结 M25 protocol 和 terminal raw，复用 M25 独立验证边界，并在
M27 派生目录输出 JSON 投影与 Markdown 报告。它按 model/mode 和 task-family/mode 汇总：

- scheduled、runtime-completed 与 solved 运行数；
- 误完成：`runtime_completed == true && solved == false`，同时报告 scheduled 与
  runtime-completed 两种分母；
- 原样统计稳定 `runtime_reason`，不主观合并类别；
- logical model calls、provider attempts、延迟和 token 的总计与均值。

派生产物使用预先命名的事务目录与逐文件 `replace` 发布。正常成功时两个公开文件均替换完成；
普通 I/O 异常会尽力恢复发布前文件并清理事务目录。该机制不是跨两个文件的原子事务：若遇到
`KeyboardInterrupt`、`SystemExit`，或回滚/状态探测本身失败，脚本停止后续破坏性 rename，抛出
`BaseExceptionGroup`，并保留事务目录中的 `*.old`、`*.staged`、`*.failed-new` 恢复证据。此时
公开路径可能处于中间态，调用方不得把运行视为成功，也不得删除事务目录后继续发布。

是否恢复某类自动 Triad，先判断该类别的 Triad solved rate 是否严格高于 Single。冻结 M25 中
没有类别通过该质量门：baseline 持平，bugfix、feature 和 refactor 均更低。因此 M27 不恢复
任何自动类别；延迟和调用成本作为支持证据报告，不引入任意权衡阈值。M25 早于 M26 证据绑定，
报告必须把误完成标记为历史结果，不得声称其衡量当前 evidence-bound Triad 的质量。

### 4. 把公开文档收窄到可证明结论

README 描述 M18 已有的 Memory runtime，而不是改代码。当前测试数字只在最终验证后更新。
Linux 平台行继续把 Pipeline 50 / Job 249 的 Linux Docker runner topology 记为 `verified`，但
不在缺少对应架构记录时宣称同时覆盖 amd64 与 arm64，并删除文末过期的 `configured` 句子。

## Risks / Trade-offs

- [宿主只设置证据布尔值却未注册检查] -> 文档明确它是可信宿主事实；内置入口固定为 false；
  实际完成安全仍由 M26 runner 是否收到定义决定。
- [删除分类器改变现有自动行为] -> 作为 breaking change 记录，保留所有显式模式，并覆盖 CLI、
  REPL、Loop、HTTP 与 resolver 集成测试。
- [M25 早于 M26] -> 在机器与人类报告中注明时间边界，只用它否定缺乏支撑的自动策略，不用来
  证明当前 Triad 质量。
- [精确测试数会在未来陈旧] -> 标注为 M27 当前基线，持续验证命令仍是长期合同。
- [Linux 证据没有完整架构投影] -> 收窄 tuple 文字，不猜测，也不把已执行证据降级为 configured。

## Migration Plan

1. 先添加路由和派生分析的失败测试。
2. 简化 resolver 并更新所有内置入口。
3. 生成并独立验证加法式 M25 派生产物。
4. 根据最终证据修正 README、ACTION_PLAN 与平台文档。
5. 执行定向、全量、OpenSpec、Golden、lint/format、打包和 diff 验证。

回滚使用普通 revert 恢复 M27 实现与文档提交。M25、M26 冻结证据不变，因此无需证据迁移或
破坏性回滚。

## Open Questions

无。自动任务类别恢复明确延期到新的冻结证据证明质量提高之后；未来策略变化必须使用新的版本化
change。
