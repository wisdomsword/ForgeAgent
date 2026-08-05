---
comet_change: improve-context-limits-and-execution-guidance
role: technical-design
canonical_spec: openspec
archived-with: 2026-08-05-improve-context-limits-and-execution-guidance
status: final
---

# Context 限额可观察性与执行指引技术设计

## 1. 共享反馈限额解析

`context.py` 增加冻结的 `ResolvedFeedbackLimits` dataclass 和纯函数 `resolve_feedback_limits()`。结果包含：

- `input_budget`；
- round/tool 的 adaptive 值；
- round/tool 可空的 configured 值；
- round/tool 的 effective 值；
- 两个显式字段各自的低值布尔标记。

解析器严格复用现有公式：

```text
effective output = generation override 或模型最大输出
input budget = floor(context window * utilization ratio) - effective output
adaptive round = floor(input budget * 0.10)
adaptive tool = floor(adaptive round * 0.25)
effective value = configured 存在时使用 configured，否则使用 adaptive
```

现有正数校验和 `round >= tool` 校验集中在同一处。`SlidingWindowContextPolicy` 保存解析结果，并通过它实现已有 property，调用方接口不变。

## 2. CLI 边界解析

现有 Registry validator 改为返回 `ResolvedFeedbackLimits`，而不只是 `None`；只需要校验的调用方可以忽略返回值。注入 client 的 validator 同样从 `client.capability` 返回解析结果。

REPL 通过本地 helper 解析当前限额：

- 生产 Registry snapshot：直接使用选中模型 capability；
- 注入 client 且没有 Registry：只在交互展示边界创建一次 probe client，从 capability 解析，并在 `finally` 关闭；
- 非交互路径：保持当前静默行为，不创建仅用于展示的 probe。

这样既集中公式，也保持依赖注入测试和嵌入方兼容。

## 3. 展示规则

启动摘要增加一个紧凑字段：

```text
feedback round <effective> / tool <effective>
```

当至少一个显式值低于当前 adaptive 值时，再输出一条普通 `Text` 告警，例如：

```text
feedback limit warning | round configured 120 < adaptive 819 | tool configured 40 < adaptive 204
```

renderer 只接收 `ResolvedFeedbackLimits`，不读取配置文件，因此无法泄漏 API key。

成功执行 `/model <id>` 后，REPL 对新模型重新解析并显示限额及告警。无参数 `/model` 只列出模型，不声称发生切换。成功 `/reload` 后使用重载配置和当前模型。切换或重载失败时保留旧状态，不显示新的 effective 状态。

管道 REPL、`run`、`serve`、HTTP response 和日志都不增加限额 banner。

## 4. 固定执行协议

包内 `protocol.md` 保留所有现有工具名、schema、Runtime API 签名、终态规则、安全边界和直接 prose 行为，只调整路由指引。

新顺序为：

1. 纯知识问题直接回答。
2. 执行目标缺少继续所需信息时调用 `Survey`，收到反馈后继续。
3. 单个直接工具或明显有界的短序列能完成整个目标时使用直接工具。
4. 递归、哈希、聚合、转换、跨文件比较或大量结果整理使用 Python/Exec。
5. 用户要求 artifact 或结果很大时，把完整结果写入获准文件，最终只回报数量、摘要和路径。
6. 不得依据浅层或已截断样本宣称任务完成。

因此重复文件任务应走 Python/Exec，因为它需要递归遍历、大小分组、内容哈希、统计和可选报告写入。`FileList` 仍适用于直接列出单个目录。

## 5. 用户配置修改

项目外修改作为独立、可验证的 migration。不得解析后重新序列化 YAML，因为那会改写或暴露无关敏感字段。

前置条件：

- 完整行 `round_feedback_max_tokens: 120` 精确出现一次；
- 完整行 `tool_result_max_tokens: 40` 精确出现一次；
- 记录文件 mode；
- 计算仅移除这两行后的预期摘要，不输出正文。

修改只删除这两行。后置条件：

- 两条目标行均不存在；
- 修改后摘要等于修改前过滤摘要；
- 文件 mode 不变；
- 正常配置加载成功，两个字段均为 `None`。

任一前置条件不满足时，不执行项目外写入。

## 6. 错误语义

- 非正 input budget 或非法 effective 顺序保持当前启动/Task 错误。
- 显式低值仍然合法且继续生效，告警只提供诊断。
- Registry 或 probe 解析失败时沿用当前 model/reload 失败路径，不能把旧值冒充当前值。
- renderer 不输出路径、endpoint、环境值或配置片段。
- prompt 遵循不是安全控制；sandbox 与确认仍是权威边界。

## 7. 测试设计

### 7.1 解析测试

- 仅 adaptive 时在边界 budget 上与现有公式一致。
- 两个显式字段分别成为 effective 值并得到正确低值标记。
- 等于 adaptive 时不告警。
- 改变 context window 或输出预留后重新计算全部 adaptive 值。
- 非正值与 round/tool 顺序错误保留当前异常。
- SlidingWindowContextPolicy property 与共享结果一致。

### 7.2 REPL 测试

- 交互启动只显示一次 effective 限额。
- 显式低值只产生一条有界告警。
- 成功模型切换与 reload 重新计算。
- 失败切换或 reload 不发布新状态。
- 非 TTY 与注入 reader 保持静默，且不创建展示用 probe。

### 7.3 协议与行为测试

- 固定协议包含 Survey、完整目标匹配、递归/聚合 Exec、文件交付和禁止截断样本收尾规则。
- 现有身份顺序与工具 schema 断言不变。
- 确定性 mock replay 收到新协议，并在固定用例产生 Survey、Exec 与文件交付调用。
- 真实配置模型通过多轮 REPL 扫描小型临时重复文件 fixture，产生执行证据和可读报告路径，不停在 FileList 输出。

### 7.4 隐私与回归

- 配置 migration 检查只输出计数、mode 与摘要。
- 配置加载确认回落到 adaptive，但不打印文件。
- context、CLI、identity、Task、HTTP、lint、类型检查和完整测试通过。

## 8. 实施顺序

1. 编写 resolver 测试并抽取纯解析结果。
2. 编写 REPL 展示测试并接入启动/model/reload 刷新。
3. 编写 protocol/mock replay 测试并更新协议文本。
4. 执行精确的项目外配置修改。
5. 运行专项/完整验证和真实模型 smoke。

本变更不增加依赖、新配置键、输出归档、FileList 功能或 HTTP schema。

