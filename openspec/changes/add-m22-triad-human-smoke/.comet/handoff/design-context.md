# Comet Design Handoff

- Change: add-m22-triad-human-smoke
- Phase: design
- Mode: compact
- Context hash: 4aeb28d1db1f2260cd102c2dc4975f76715a31bae57022d3baad7f654d4512a1

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/add-m22-triad-human-smoke/proposal.md

- Source: openspec/changes/add-m22-triad-human-smoke/proposal.md
- Lines: 1-30
- SHA256: cb5486d8e5572c15c2655b9e824875fe3ab38dae62025e78515ab4ce75d0b32d

```md
## Why

M22 已有离线回归与人工执行记录，但缺少一个可重复的一键入口来驱动真实模型 Triad、保留
Planner 人工确认，并自动核验协作状态与产物。手工复制长命令容易漏参数，也难以稳定区分
模型协议失败、人工拒绝和产物验收失败。

## What Changes

- 新增仓库内 Python 一键脚本，在隔离临时目录中运行真实模型 Triad 的 `moving_average` 编程任务。
- 保留原 CLI 的 Planner 计划人工确认，不自动批准。
- 在协作结束后自动核验终态、角色 attempt、生成文件、pytest 与 CLI JSON 输出。
- 失败时保留现场目录并给出稳定诊断；成功时同样打印现场路径，便于人工复核。
- 新增无需真实模型的离线测试，并在 README 提供单命令入口和费用提示。

## Capabilities

### New Capabilities

- `triad-human-smoke`: 定义真实模型 Triad 人工确认冒烟脚本的一键入口、自动验收和失败保留行为。

### Modified Capabilities

无。

## Impact

- 脚本：`scripts/m22-triad-human-smoke.py`
- 测试：`tests/test_m22_triad_human_smoke.py`
- 文档：`README.md`
- 运行时代码、CLI 参数、公开 API、依赖和持久化 schema：不变

```

## openspec/changes/add-m22-triad-human-smoke/design.md

- Source: openspec/changes/add-m22-triad-human-smoke/design.md
- Lines: 1-61
- SHA256: d6fee17704fd7cac9c35a573494f5468d15a42ce803be8827fbc4d8dde65f7e4

```md
## Context

M22 当前的人类测试依赖手工创建目录、复制长 CLI 命令、人工确认计划，再分别执行 pytest 与
`calc.py`。现有 CLI 已具备真实模型选择、restricted tier、identity/memory 关闭、Triad 编排与人工计划
确认；缺口只是一个可重复的 orchestration 和验收包装层。

## Goals / Non-Goals

**Goals:**

- 一个仓库内命令完成隔离目录创建、真实 Triad、人工计划确认和自动验收。
- 失败保留现场，并用稳定、脱敏的信息说明失败阶段。
- 离线测试覆盖脚本控制流，不让 CI 调用真实模型。

**Non-Goals:**

- 不新增 ForgeAgent CLI 子命令、运行时协议、HTTP endpoint 或持久化字段。
- 不自动批准 Planner 计划。
- 不比较 single/Triad 的质量或成本，不把一次冒烟结果当 benchmark。
- 不清理现场目录，不管理或输出用户凭证。

## Decisions

### 使用独立 Python 脚本包装现有 CLI

脚本使用标准库 `json`、`subprocess`、`tempfile` 和 `pathlib`。它以继承 stdin/stdout/stderr
的方式运行 ForgeAgent，因此 Planner 确认保持原生交互体验。相比 Bash，Python 更适合安全读取
状态 JSON、比较 CLI JSON 和提供可测试函数；相比新增 CLI 子命令，它不扩大产品 API。

### 从隔离目录的持久状态判断协议结果

每次运行创建唯一临时目录，并在其中执行 ForgeAgent。脚本从
`.forgeagent/collaborations/*.json` 要求恰好找到一份状态，解析稳定字段，而不抓取终端文案。这样可
确认 `completed`、attempts、rejections 和 `invalid_role_submission`，同时避免依赖 Rich 输出格式。

### 默认保留现场，环境变量只覆盖模型

成功和失败都保留临时目录，便于用户打开文件复核。默认 Generator 为 `claude-sonnet-5`，Planner
和 Evaluator 为 `claude-haiku-4-5`；仅支持 `FORGEAGENT_M22_MODEL`、
`FORGEAGENT_M22_PLANNER_MODEL`、`FORGEAGENT_M22_EVALUATOR_MODEL` 覆盖，不增加通用配置系统。

### 自动验收使用项目虚拟环境解释器

脚本定位仓库 `.venv/bin/forgeagent` 与 `.venv/bin/python`，先验证文件存在，再使用同一 Python 执行
pytest 和 `calc.py`，避免 PATH 指向其他安装。pytest 输出继承终端；CLI JSON 使用 capture 后严格
`json.loads` 比较数值数组。

## Risks / Trade-offs

- [真实模型具有波动和费用] → README 明确 opt-in 与费用；离线 CI 不运行脚本主流程。
- [用户拒绝与模型失败都返回非零] → 读取持久状态，优先报告 `needs_confirmation` 或稳定 stop reason。
- [模型可能留下多个状态文件] → 每次使用全新目录并要求恰好一份状态，异常时 fail closed。
- [临时目录积累] → 默认保留是人类测试的可诊断性要求；输出完整路径，由用户自行清理。

## Migration Plan

无需迁移。新增脚本、测试和 README 入口即可；回滚时删除这些文件与对应文档。

## Open Questions

无。人工确认、默认模型、验收任务与现场保留均已确认。

```

## openspec/changes/add-m22-triad-human-smoke/tasks.md

- Source: openspec/changes/add-m22-triad-human-smoke/tasks.md
- Lines: 1-14
- SHA256: 62396233ac6511cd03b4d61e73be3f699a3219747b532b93cd29d29cef626bcf

```md
## 1. 脚本控制流与离线测试

- [ ] 1.1 以 TDD 增加脚本导入、命令组装、成功状态解析、人工计划拒绝和 ForgeAgent 失败回归
- [ ] 1.2 实现隔离目录、真实 Triad 子进程、状态读取与稳定诊断

## 2. 产物验收

- [ ] 2.1 以 TDD 增加缺文件、pytest 失败和 CLI JSON 不匹配回归
- [ ] 2.2 实现文件、pytest 与 moving-average CLI 输出验收，并打印最终摘要

## 3. 文档与验证

- [ ] 3.1 更新 README 一键命令、人工确认、模型覆盖、费用和现场保留说明
- [ ] 3.2 运行专项、ruff、OpenSpec strict 与完整 pytest，并完成独立代码复审

```

## openspec/changes/add-m22-triad-human-smoke/specs/triad-human-smoke/spec.md

- Source: openspec/changes/add-m22-triad-human-smoke/specs/triad-human-smoke/spec.md
- Lines: 1-40
- SHA256: af92b696ce6daf50f6e89b86dbc4aa5bc8f5c397153f931f4dbb53d84d3d752f

```md
## ADDED Requirements

### Requirement: 一键脚本运行真实模型 Triad 并保留人工计划确认
仓库 MUST 提供单命令人类冒烟入口，在隔离工作目录中使用现有 ForgeAgent CLI 运行真实模型
Triad。脚本 MUST 保留 Planner 计划的终端人工确认，不得隐式批准；默认模型 MUST 可通过有界、
明确的环境变量覆盖，且脚本不得打印 API key 或其他 credential。

#### Scenario: 人工批准后执行完整 Triad
- **WHEN** 用户运行一键脚本并在 Planner 计划确认提示中批准
- **THEN** 脚本继续运行 Generator 与 Evaluator，并将原 CLI 输出实时显示在当前终端

#### Scenario: 人工拒绝计划
- **WHEN** 用户在 Planner 计划确认提示中拒绝
- **THEN** 脚本以非零状态结束，明确报告 `needs_confirmation`，且保留隔离现场目录

#### Scenario: 非交互终端拒绝启动
- **WHEN** stdin 或 stdout 不是交互终端，无法提供 Planner 人工确认
- **THEN** 脚本在调用任何真实模型前以非零状态结束，并明确提示需要交互终端

### Requirement: 脚本自动验证协作终态与可观察产物
脚本 MUST 在 ForgeAgent 进程结束后读取本次隔离目录中的协作状态，确认 mode 为 `triad`、status
为 `completed`、Planner 已提交计划、Generator 与 Evaluator attempts 均至少为 1，且 stop reason
不是 `invalid_role_submission`。随后 MUST 检查 `calc.py`、`test_calc.py`、pytest 成功和命令行 JSON
输出严格等于 `[1.5,2.5,3.5]`。

#### Scenario: 所有自动验收通过
- **WHEN** Triad 完成且生成产物、pytest 与 CLI 输出全部符合约定
- **THEN** 脚本以 0 退出，并打印 PASS、现场目录、collaboration ID、attempt 和 rejection 计数

#### Scenario: 协作或产物验收失败
- **WHEN** ForgeAgent 失败、协作状态不完整、文件缺失、pytest 失败或 CLI JSON 不匹配
- **THEN** 脚本以非零状态结束，列出失败阶段和有界诊断，并保留现场目录供人工检查

### Requirement: 一键入口具有无需真实模型的离线回归
脚本的命令组装、状态解析和产物验收 MUST 可通过依赖注入或子进程 fixture 离线测试；项目自动测试
MUST NOT 调用真实模型、访问真实用户 HOME 或消耗凭证。

#### Scenario: 离线成功与失败矩阵
- **WHEN** 测试分别提供成功、人工拒绝、ForgeAgent 失败、状态异常、pytest 失败和 CLI 输出错误 fixture
- **THEN** 测试可确定性验证对应退出码、诊断和现场保留行为，且不发起网络请求

```
