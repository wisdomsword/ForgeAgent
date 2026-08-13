## ADDED Requirements

### Requirement: Restricted 资源限额可配置且反馈稳定
ForgeAgent MUST 为 restricted Python worker 提供正有限 wall timeout、正整数 CPU 秒数和正整数 memory MiB 限额。解析优先级 MUST 为 CLI 显式覆盖、用户配置、内置默认值；默认值 MUST 保持 30 秒、10 秒和 512 MiB。该配置 MUST NOT 改变 container 或 trusted 行为。

#### Scenario: CLI 覆盖用户配置
- **WHEN** 用户配置 restricted CPU 为 20 秒且 CLI 显式提供 5 秒
- **THEN** 本次 restricted Task 使用 5 秒 CPU 限额，其他未覆盖字段保留配置值

#### Scenario: CPU 限额终止
- **WHEN** restricted worker 超过 CPU soft limit 并已产生部分输出
- **THEN** 反馈说明超过配置的 CPU 时间限额，保留有界、已掩码的 stdout/stderr，而不是只返回裸信号号

#### Scenario: SIGKILL 原因不确定
- **WHEN** worker 以 SIGKILL 结束且宿主不能确定具体来源
- **THEN** 反馈只说明可能由资源限制导致，不虚报为确定的 memory 或 CPU 超限
