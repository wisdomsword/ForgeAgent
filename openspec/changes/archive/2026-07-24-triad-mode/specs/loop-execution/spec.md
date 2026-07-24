## MODIFIED Requirements

### Requirement: 失败反馈环有界收敛且不引入独立 Evaluator
每个 Loop 迭代 SHALL 按 checkpoint 中冻结的运行模式执行一个普通 Task 或一个 Duo/Triad 协作 runner；非完成结果 SHALL 生成脱敏、有界的失败摘要并与最近 checkpoint 交接信息一起进入下一迭代。Loop MUST 在停止预算内尝试修正，MUST 对明确不可恢复的配置、鉴权、checkpoint、计划完整性或策略错误立即停止，并 MUST NOT 在 resume 时改变协作模式、已确认计划、角色安全策略或完成标准。

#### Scenario: 可恢复失败后修正成功
- **WHEN** 一个普通 Task 或协作 runner 因工具失败、Evaluator 拒绝、上下文限制或轮次耗尽而未完成，但尚未命中 Loop 停止条件
- **THEN** 下一迭代收到有界失败证据和继续要求，最终按冻结模式完成时 Loop 写入 completed 终态

#### Scenario: 反复失败不无限重试
- **WHEN** 每个迭代均未完成且达到连续失败、轮次、token 或墙钟任一上限
- **THEN** Loop 停止并留下可诊断报告，不再调用模型

#### Scenario: Single Loop 保持既有边界
- **WHEN** Loop checkpoint 冻结为 single 模式
- **THEN** 系统不实例化 Planner 或 Evaluator，Loop 完成仍以现有 Task 的严格 completed 语义为准

#### Scenario: Collaborative Loop resume 保持计划
- **WHEN** Duo/Triad Loop 从有效 checkpoint 恢复
- **THEN** 系统验证冻结 mode 与计划摘要，继续角色打回/迭代计数，且不允许调用方覆盖完成标准
