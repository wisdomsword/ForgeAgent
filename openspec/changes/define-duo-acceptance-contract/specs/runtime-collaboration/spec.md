## ADDED Requirements

### Requirement: Duo 默认计划提供可观察验收契约
ForgeAgent SHALL 为新建 Duo 协作从 goal 的交付形态确定性生成冻结验收计划。计划项 MUST 使用稳定 ID，MUST 描述 Evaluator 可直接观察的产物、验证结果或响应证据，MUST NOT 使用“原始目标已满足”“满足用户需求”或其他以目标自身作为验收证明的循环表述。生成过程 MUST NOT 调用 LLM、安装依赖、复制原始 goal 正文、绝对路径或 secret。

#### Scenario: 文件或产物 goal
- **WHEN** Duo goal 要求创建、修改或处理文件或其他可检查产物
- **THEN** 冻结计划要求 Evaluator 定位允许根目录内的相对产物并检查其存在性和内容

#### Scenario: 命令或验证 goal
- **WHEN** Duo goal 主要要求运行测试、检查、构建或其他可验证命令
- **THEN** 冻结计划要求 Evaluator 检查注册验证结果或有界命令证据及其成功状态

#### Scenario: 文本或分析 goal
- **WHEN** Duo goal 不属于产物或命令验证类别
- **THEN** 冻结计划要求 Evaluator 引用具体响应片段或安全产物，并检查其是否包含可核对的结论与支撑证据

#### Scenario: 旧 Duo snapshot 恢复
- **WHEN** 持久化 Duo snapshot 已包含旧冻结计划和 digest
- **THEN** 系统按 snapshot 原样恢复，不用新模板重算或拒绝旧计划
