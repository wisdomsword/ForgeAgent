## MODIFIED Requirements

### Requirement: 确定性准入与程序性分流
系统 SHALL 只准入陈述性事实、用户偏好和已确认决策；`kind=procedure` 的候选 MUST 被拒绝并反馈“请沉淀为 Skill”。候选内容 MUST 经过长度、控制字符、敏感环境值和明显提示注入指令检查；任一检查失败 MUST 拒绝候选。系统 MUST NOT 使用向量相似度、置信度模型或额外 LLM 调用决定准入。Task MUST 暴露每个逻辑模型候选的结构化准入结果，CLI SHALL 在任务输出中展示该权威结果且不得回显候选原文；同一 Task 内 scope、kind、key 和 content 均相同的重复候选 MUST 只应用、审计和反馈一次。

#### Scenario: 陈述性事实准入
- **WHEN** 候选 kind 为 fact、内容通过边界检查且 key 有效
- **THEN** 候选进入目标作用域并生成 accepted 审计事件

#### Scenario: 程序性记忆拒绝
- **WHEN** 候选描述“每次先运行某命令再修改文件”等做事步骤且 kind 为 procedure
- **THEN** 候选不进入任何作用域，并返回应沉淀为 Skill 的结构化拒绝原因

#### Scenario: 提示注入候选拒绝
- **WHEN** 候选内容包含要求忽略系统协议、泄露 secret 或执行越权动作的指令
- **THEN** 候选被拒绝且拒绝反馈不回显敏感原文

#### Scenario: 禁用记忆时纠正模型声明
- **WHEN** `--no-memory` 模式下模型响应包含合法 Memory 候选并声称已记住
- **THEN** Task 返回 disabled 结果，CLI 展示 `memory disabled`，且 session 与 project 存储不变

#### Scenario: 多轮重复候选幂等
- **WHEN** 同一 Task 的多个模型 round 重复发出 scope、kind、key 和 content 均相同的候选
- **THEN** Task 只应用该候选一次，并只返回一个准入结果和一条对应审计事件
