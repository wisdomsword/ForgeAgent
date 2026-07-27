# Brainstorm Summary

- Change: m23-collaboration-mode-evaluation
- Date: 2026-07-27

## 确认的技术方案

采用独立 Python harness 与版本化 JSON 协议。Harness 直接组装现有 `Task` 和 `CollaborationRunner`，为三种模式提供同一模型、参数、任务夹具、临时工作区和模式外产物检查；按固定轮换顺序完成 3 个任务、3 次重复、3 种模式共 27 次运行。每次运行原子写入安全 JSON，聚合器只读取这些原始记录生成机器报告和人工报告。

用户已明确授权在需要抉择时进行两轮自我评审并采用推荐方案，因此本 change 的 open/design/build 决策按该授权继续，不另行暂停。

## 关键取舍与风险

- 选择仓库外层 harness 而非 CLI shell，避免解析人类文本和交互式计划确认；不新增产品命令。
- 选择 `claude-haiku-4-5` 控制真实评估成本，并让所有角色使用同一 canonical ID；记录模型注册表 SHA-256，明确它不是服务端权重哈希。
- 任务完成由统一外部检查判定；Duo/Triad 的内部首次验收单独统计，Single 对验收循环指标记 `null`。
- 模型调用按逻辑 `llm.outcome` 计数，provider attempt 另存诊断；usage 缺失按调用级载荷计算，不用零代替未知。
- 三次重复只支持描述性比较，报告不得排序或自动宣称 Triad 优于 Single。

## 测试策略

- 先写离线合同测试，覆盖协议校验、27 次排程、任务工作区、usage 口径、N/A、原子记录、聚合可复算和中立报告。
- 用 fake client/runner 数据验证单次运行投影，不依赖真实 credential 或网络。
- 目标测试通过后运行真实 27 次调度，再执行 ruff、全量 pytest、OpenSpec strict、证据一致性检查和两轮自审。
- 用 git diff 断言 `src/forgeagent/collaboration.py`、credential 与 CLI 产品入口未被修改。

## Spec Patch

无。OpenSpec delta spec 已覆盖协议、排程、产物检查、适用性、usage、原始记录和中立报告场景。
