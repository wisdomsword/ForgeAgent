# Brainstorm Summary

- Change: calibrate-collaboration-routing
- Date: 2026-07-29

## 确认的技术方案

采用“显式模式优先、宿主证据其次、其余 Single”的最小路由：显式 Single/Duo/Triad 原样生效；
无显式模式但可信宿主已绑定非空冻结检查时选择 Triad；其他任务无论是否具有编程文本特征都默认
Single。路由器只接收 `has_bound_checks` 布尔事实，不接触检查内容。删除已不参与决策的私有编程
分类器；`allow_weaker_override` 和 `ModeDecision.override_required` 仅为兼容保留，前者不改变结果，
后者在新路由中恒为 false。

M25 派生分析使用新的标准库脚本，只读验证 270 份冻结 raw 及既有 summary，按 model/mode 与
task-family/mode 输出 solved、误完成双分母、精确 runtime_reason、调用、provider attempts、
延迟和 token 指标。只有 Triad solved rate 严格高于 Single 的类别才进入恢复评估；M25 没有任何
类别满足，因此不恢复自动 Triad。输出写入独立 M27 派生目录并记录冻结输入摘要。

Memory 只修正文档：`.forgeagent/MEMORY.md` 可由 M18 runtime 在准入后原子更新，也可由用户编辑；
`--no-identity` 与 `--no-memory` 语义不变。Linux 保留 M24 历史 container 运行已证明的 verified，
但把 tuple 收窄到证据实际记录的 Linux Docker runner topology，并删除同文档的 configured 旧句。

## 关键取舍与风险

- 方案 A“保留分类器但默认 Single”被否决：增加无效维护面并可能被未来调用方误用。
- 方案 B“把 CheckDefinition 直接交给路由器”被否决：扩大数据与信任边界，重复 M26 registry。
- 方案 C“只传宿主布尔证据事实”获采用：接口最小、审计有界、显式选择可预测。
- 可信宿主若错误设置布尔值，路由可能进入无检查 Triad；内置入口固定无证据，实际完成门禁仍由
  M26 runner 的真实检查注册决定，文档明确该参数不可来自普通用户输入。
- M25 早于 M26，派生报告只能否定旧自动策略的充分性，不能证明当前 evidence-bound Triad 质量。

## 测试策略

- Resolver 单元测试：全部显式模式、默认 Single、bound-check Triad、显式优先、候选文件无效、
  兼容参数无效、审计只含稳定原因。
- 入口集成测试：CLI run、REPL、Loop 与 HTTP 的编程目标均默认 Single；显式 Duo/Triad 不再确认。
- 派生分析 TDD：合成完整 M25 evidence，验证误完成定义、双分母、reason 分类、family/model 分组、
  cost 指标、冻结输入防篡改与生成目录边界；再对真实冻结批次生成产物。
- 文档合同：Memory 行为、当前 pytest/OpenSpec/Golden 基线一致、Linux verified tuple 不夸大且无
  configured 矛盾。
- 完成门禁：定向测试、全量 pytest、OpenSpec strict、Golden、Ruff、打包、diff check，以及两轮
  自审和独立 review 后的复验。

## Spec Patch

无。现有 M27 delta spec 已明确显式优先、宿主证据定义、双分母、历史证据边界与 Linux tuple
收窄规则。
