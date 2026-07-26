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

每次运行在 `/tmp` 创建唯一临时目录，并在其中执行 ForgeAgent。脚本从
`.forgeagent/collaborations/*.json` 要求恰好找到一份状态，以标准库读取 raw JSON dict 并只解析本冒烟
契约依赖的稳定字段，而不调用完整 `CollaborationState` 校验或抓取终端文案。这样可确认
`completed`、attempts、rejections 和 `invalid_role_submission`，同时避免复制持久化 schema 或依赖 Rich 输出格式。

### 默认保留现场，环境变量只覆盖模型

成功和失败都保留临时目录，便于用户打开文件复核。默认 Generator 为 `claude-sonnet-5`，Planner
和 Evaluator 为 `claude-haiku-4-5`；仅支持 `FORGEAGENT_M22_MODEL`、
`FORGEAGENT_M22_PLANNER_MODEL`、`FORGEAGENT_M22_EVALUATOR_MODEL` 覆盖，不增加通用配置系统。

### 自动验收使用项目虚拟环境解释器

脚本定位仓库 `.venv/bin/forgeagent` 与 `.venv/bin/python`，先验证它们是可执行文件（允许虚拟环境
的标准 symlink），再使用同一 Python 执行 pytest 和 `calc.py`，避免 PATH 指向其他安装。pytest 输出继承终端；CLI JSON 使用 capture 后严格
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
