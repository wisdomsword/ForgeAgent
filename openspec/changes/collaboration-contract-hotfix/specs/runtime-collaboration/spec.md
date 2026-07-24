## MODIFIED Requirements

### Requirement: Planner 生成冻结且不可降级的验收清单
Triad Planner MUST 只定义 WHAT：每个清单项包含稳定 ID、可观察行为与验收标准，不得指定实现步骤。系统 MUST 对 `behavior` 与 `acceptance` 两个字段同时执行 WHAT-only 校验。计划提交后系统 MUST 规范化并计算摘要；确认后的条目、顺序和标准 MUST 冻结，后续角色不得删除、替换、重排或降低标准。

#### Scenario: 合法计划确认
- **WHEN** Planner 提交非空、唯一 ID 且全部字段有界的计划，并由交互用户确认或由 headless 预授权策略接受
- **THEN** 系统冻结规范化计划和摘要并允许 Generator 开始

#### Scenario: Planner 在任一计划字段指定实现方法
- **WHEN** Planner 在 `behavior` 或 `acceptance` 中把工具调用、库选择或具体实现步骤当作验收内容
- **THEN** 系统通过结构化反馈要求其改写为外部可观察行为，不接受或冻结该版本计划

#### Scenario: 后续角色改变计划
- **WHEN** Generator、Evaluator、Loop resume 或打回轮次提供缺项、改项、重排或不同摘要的计划
- **THEN** 系统拒绝变更并保持已确认计划不变
