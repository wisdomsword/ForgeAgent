---
comet_change: define-duo-acceptance-contract
role: technical-design
canonical_spec: openspec
---

# Duo Acceptance Contract Design

## 1. Problem

`_duo_plan(goal)` 当前显式丢弃 goal，并为所有 Duo 返回同一个循环论证式计划项。Evaluator 只能看到“原始目标已满足”，无法知道应观察文件、命令结果还是文本证据。Duo 因此增加了角色成本，却没有形成可执行的独立验收契约。

## 2. Constraints

- 不引入 LLM 自动拆解器、新依赖或配置。
- 保持一个稳定计划项 ID `goal`，避免旧 snapshot、plan digest、恢复和 SubmitEvaluation 覆盖规则迁移。
- 不改变 Triad Planner 或 EvaluationItem 结构。
- 计划正文不得包含 raw goal、绝对路径、secret 或原始 prompt。
- 模板必须 English-first，并明确 Evaluator 能直接观察的证据。

## 3. Selected Design

`_duo_plan(goal)` 使用小型纯函数对 goal 的 casefold 文本做有限分类：

1. 产物/文件信号：file、path、artifact、document、write/create/update/save，以及对应中文关键词。
2. 验证/命令信号：test、check、verify、build、run、pytest、lint，以及对应中文关键词。
3. 未命中时使用文本/分析回退。

每类仍返回一个 `AcceptanceItem(id="goal", ...)`：

- 产物类要求 Evaluator 定位允许根目录内的相对产物并检查存在性和内容。
- 验证类要求 Evaluator 检查注册 check 或有界命令结果与成功状态。
- 文本类要求 Evaluator 引用具体响应片段或安全产物，并核对结论和证据。

Goal 只用于选模板，不插值到 behavior/acceptance。这样既利用入参语义，又不会把路径或 secret 复制到冻结计划、handoff 或报告。

## 4. Alternatives Rejected

- **三个固定计划项：** 可观察性更强，但会让旧 Evaluator 单项结果不完整，扩大持久化兼容面，不符合 M39 最小范围。
- **把 goal 摘要写入计划：** 更具体，但会复制绝对路径、secret 或 prompt 正文，违反公开投影边界。
- **LLM/通用 NLP 拆解：** 灵活但非确定、成本高、增加依赖和失败模式，用户已明确禁止。

## 5. Compatibility

新建 Duo 使用新模板与新 digest。旧 snapshot 已持久化自己的 plan 和 digest，加载时继续原样验证，不调用 `_duo_plan` 重算。调用方仍提交 `id="goal"` 的 EvaluationItem，因此协议形状不变。

## 6. Testing

- 三个 golden case 精确断言三类模板的 behavior/acceptance。
- 相同 goal 重复生成相同 plan 与 digest。
- 模板不含循环验收短语、raw goal、绝对路径或配置 secret。
- 旧 snapshot 加载与现有 Duo runner/store/tools 回归通过。
- 全量 pytest、Ruff、format、OpenSpec strict 与 `uv build` 通过。

## 7. Non-Goals

本 change 不做动态条目拆分、复杂语义解析、Triad 改造、Loop handoff 结构化、发布或 PyPI 工作。
