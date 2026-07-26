## MODIFIED Requirements

### Requirement: 一键入口具有无需真实模型的离线回归
脚本的命令组装、状态解析和产物验收 MUST 可通过依赖注入或子进程 fixture 离线测试；项目自动测试 MUST NOT 调用真实模型、访问真实用户 HOME 或消耗凭证。状态加载 MUST 通过控制流稳定区分超大文件与无效 JSON，不得依赖底层异常消息字符串；计划中重复的合法 ID MUST 被唯一性校验明确拒绝。

#### Scenario: 状态错误与重复 ID 精确分类
- **WHEN** JSON parser 抛出与文件过大诊断同文案的异常，或计划包含两个相同且格式合法的 ID
- **THEN** 前者仍稳定报告无效 JSON，后者精确报告 plan item ID 不唯一，且离线测试直接覆盖对应分支
