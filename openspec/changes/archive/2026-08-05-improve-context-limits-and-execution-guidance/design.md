## Context

现有 `SlidingWindowContextPolicy` 已根据模型 input budget 计算反馈默认值，也允许配置显式覆盖，但解析结果只存在于策略内部。真实用户配置将 round/tool 上限设为 120/40 时，REPL 启动没有任何可见提示，用户只能从频繁截断反推原因。

固定协议同时把“直接工具匹配”描述得过宽。`FileList` 能列一个目录，并不能完成递归判重、聚合统计或大结果交付；模型仍可能因为名称看似匹配而在一次浅层调用后结束。

## Goals / Non-Goals

**Goals**

- 用一个纯解析结果统一表达配置值、自适应值和实际生效的 round/tool feedback 上限。
- 在交互启动、成功 `/model` 和 `/reload` 后显示生效上限，并对显式低值告警。
- 精确删除已授权用户配置中的 120/40 两行，不读取或重写 API key。
- 让固定协议按“能否完成整个目标”选工具，并明确 Survey、Exec 与大结果文件交付规则。
- 用 mock replay 和真实模型的受控临时目录 smoke 验证行为，不把 mock 输出冒充真实智能证据。

**Non-Goals**

- 不移除或放宽统一 feedback limiter。
- 不给 FileList 增加递归、cursor 或分页能力。
- 不自动归档任意工具的完整输出。
- 不改变 HTTP 请求 schema、非交互启动输出或 provider 参数。
- 不承诺模型在所有开放任务上确定性遵循提示词。

## Decisions

### 1. 抽取只读的反馈限额解析结果

在 `context.py` 提供一个不可变解析结果，包含 input budget、round/tool 的 adaptive、configured（可空）与 effective 值。`SlidingWindowContextPolicy` 消费同一解析函数，不再自行重复计算；CLI 也只读取该结果，不复制公式。

显式值仍按现有配置语义成为 effective 值。告警条件是 `configured is not None and configured < adaptive`，分别判断 round 与 tool；不凭主观阈值引入第二套“过低”标准。

### 2. 交互边界公开紧凑、无敏感信息的状态

启动摘要增加 `feedback round <effective> / tool <effective>`。存在显式配置时可同时显示 configured 与 adaptive 来源；任一显式值低于 adaptive 时另输出一行固定格式告警，只含字段名和数值。

成功 `/model` 和 `/reload` 后重新基于当前模型能力及当前配置解析并显示。非 TTY、`run`、HTTP 不新增 banner 输出。

### 3. 精确修改用户配置

只删除完整匹配的 `round_feedback_max_tokens: 120` 与 `tool_result_max_tokens: 40` 行，并在修改前后验证：两行修改前各存在一次、修改后均不存在、其余文件摘要在忽略这两行后相同、权限不变。检查过程只输出目标字段和摘要，不输出配置正文或 API key。

若目标行不再精确匹配，则停止外部修改并报告冲突，不能用 YAML 全量重写。

### 4. 按完整目标而非工具名称选择执行路径

固定协议按以下顺序说明：

1. 缺少继续执行所必需的信息时使用 `Survey`，并在收到答案后的同一 Task 继续。
2. 单个内置工具能够完整完成目标时直接调用它。
3. 递归遍历、跨文件聚合、内容哈希、转换或大量结果整理使用 Python/Exec。
4. 用户要求文件交付或结果较大时，执行代码将完整结果写到获准路径，最终回复只给数量、摘要和文件位置。

这只是路由提示；sandbox、确认和实际工具权限仍由宿主强制执行。

### 5. 分层验证真实行为

单元测试锁定限额公式、告警、命令刷新和 prompt 字节；mock replay 验证模型收到连续澄清上下文并产生预期工具调用。最后在项目内受控临时目录制造少量重复文件，通过真实配置模型运行 REPL 多轮 smoke，检查执行证据、报告文件和无截断摘要。真实 smoke 的模型输出作为特定环境证据，不提升为普遍保证。

## Risks / Trade-offs

- **启动摘要变长。** 使用单个紧凑字段和最多一条告警，且仅交互式显示。
- **显式低值可能是用户有意设置。** 只告警不覆盖；本次 120/40 删除来自用户明确授权。
- **提示词不能保证模型执行。** 用确定性契约测试加真实 smoke，并保留运行时终态与执行证据，不通过隐藏自动执行改变语义。
- **集中解析可能影响 HTTP Task。** 策略使用相同 effective 值，HTTP schema 与输出不变，运行回归测试。

## Migration Plan

1. 用失败测试定义解析结果、低值告警和命令刷新。
2. 抽取解析函数并让 context policy 与 CLI 共同消费。
3. 修改固定协议并增加 identity/mock replay 回归。
4. 精确删除用户配置两行并执行隐私安全校验。
5. 运行完整测试及受控真实模型 smoke。

回滚代码不会恢复用户配置的 120/40；如确需回滚，用户可显式重新配置。adaptive 默认本身是既有行为。

## Open Questions

无。告警判定、展示时机和配置修改范围均已明确。
