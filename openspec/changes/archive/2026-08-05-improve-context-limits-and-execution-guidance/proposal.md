## Why

当前真实配置把单轮反馈和单工具结果分别限制为 120/40 近似 token，远低于模型自适应预算，但启动时不可见；同时固定协议过度强调“直接工具优先”，使模型把递归判重等聚合任务误降级为单层 `FileList`，再用截断片段向用户汇报未完成结果。

## What Changes

- 统一计算并公开当前模型的配置值、自适应值和实际生效的 round/tool feedback 上限。
- 交互式启动、`/model` 和 `/reload` 显示生效上限；任一显式值低于当前模型自适应值时输出安全、有界告警。
- 精确删除用户级配置中的 `round_feedback_max_tokens: 120` 与 `tool_result_max_tokens: 40`，保留含 API key 的其余文件字节和权限不变。
- 收紧固定执行协议：缺少必要信息时使用 Survey；直接工具只有能完成完整目标时才优先；递归扫描、聚合、转换或大量输出使用 Exec；大结果写入用户要求的文件并只回报摘要和路径。
- 保留现有统一 feedback limiter、诚实截断和安全投影，不增加 FileList cursor、分页或任意工具结果归档。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-context-management`: 自适应与显式反馈上限具有可复用的解析结果，并以当前模型自适应值判定低值配置。
- `repl-startup-information`: 启动、模型切换和重载公开实际反馈上限及低值告警。
- `runtime-identity`: 固定协议按完整任务适配工具，使用 Survey 保持澄清上下文，并对聚合/大输出任务使用 Exec 和文件交付。

## Impact

- 主要影响 `src/forgeagent/context.py`、`src/forgeagent/_cli_repl.py`、`src/forgeagent/cli.py`、包内 prompt 资源及对应 context/CLI/identity/mock replay 测试。
- 用户级 `~/.forgeagent/config.yaml` 只做已授权的两行精确删除；不读取、输出或重写 API key。
- 不新增依赖，不取消安全限额，不改变 HTTP 请求 schema、FileList 功能面或任意工具输出保留策略。
