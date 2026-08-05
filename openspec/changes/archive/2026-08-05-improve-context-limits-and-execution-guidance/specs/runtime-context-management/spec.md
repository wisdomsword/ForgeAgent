## ADDED Requirements

### Requirement: 反馈限额解析结果统一且可观察

ForgeAgent MUST 通过同一个运行时解析结果计算并公开当前模型的 input budget、round/tool adaptive 值、可选 configured 值和 effective 值。Sliding-window policy 与 REPL 展示 MUST 消费同一解析结果，不得复制或偏离计算公式。显式配置值低于对应 adaptive 值时，系统 SHALL 标记该字段为低值配置，但 MUST NOT 在未获授权时自动覆盖用户配置。

#### Scenario: 没有显式反馈限额
- **WHEN** context 配置未设置 round 或 tool feedback 上限
- **THEN** configured 值为空，effective 值分别使用当前模型 input budget 对应的 adaptive 值

#### Scenario: 显式值高于自适应值
- **WHEN** 某一显式反馈限额等于或高于当前模型 adaptive 值
- **THEN** effective 值使用显式配置，且该字段不产生低值告警

#### Scenario: 显式值低于自适应值
- **WHEN** 某一显式反馈限额低于当前模型 adaptive 值
- **THEN** effective 值仍使用显式配置，同时解析结果标记该字段并供交互 REPL 输出有界告警

#### Scenario: 模型切换改变 input budget
- **WHEN** REPL 切换到具有不同 context window 或最大输出预留的模型
- **THEN** adaptive 值、低值判断和未显式配置字段的 effective 值均基于新模型重新计算

#### Scenario: HTTP 策略保持兼容
- **WHEN** HTTP Task 使用统一解析结果构造 context policy
- **THEN** 实际 limiter 语义与相同配置下既有行为一致，HTTP 请求和结果 schema 不新增字段
