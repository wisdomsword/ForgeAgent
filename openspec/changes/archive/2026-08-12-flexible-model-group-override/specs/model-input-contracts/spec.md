## ADDED Requirements

### Requirement: 用户模型组覆盖支持显式替换
当用户配置覆盖已有 provider group 时，显式提供的 `models` MUST 替换该组的完整模型列表，而不是与内建列表合并。省略 `models` MUST 保留内建列表；显式空列表 MUST 清空该组。

#### Scenario: 模型被重新分组
- **WHEN** 用户在旧组显式移除一个模型并在新组列出该模型
- **THEN** 最终 registry MUST 只将该模型路由到新组
- **AND THEN** 不得因隐式保留旧组成员而产生重复路由错误

#### Scenario: 只覆盖组的标量字段
- **WHEN** 用户覆盖已有组但省略 `models`
- **THEN** 最终 registry MUST 保留该组的内建模型列表

#### Scenario: 显式清空组
- **WHEN** 用户为已有组配置 `models: []`
- **THEN** 最终 registry MUST 接受空列表并移除该组的全部模型成员
