# Brainstorm Summary

- Change: improve-context-limits-and-execution-guidance
- Date: 2026-08-05

## 确认的技术方案

采用 `context.py` 单一不可变解析结果。结果同时包含 input budget、round/tool 的 adaptive、configured 和 effective 数值；SlidingWindowContextPolicy、交互启动、`/model <id>` 与 `/reload` 共用它。固定协议改为按完整目标选择 Survey、直接工具或 Exec，并要求大量结果通过获准文件交付。

未采用 CLI 内复制公式，因为模型预算公式会漂移；未采用仅启动时校验配置，因为 `/model` 和 `/reload` 会改变当前基准；未采用自动提高低值，因为显式配置仍是用户契约。

## 关键取舍与风险

- 低值判断严格使用 `configured < adaptive`，只告警，不改写 effective 值。
- 生产 REPL 从 Registry capability 解析；注入客户端且无 Registry 时，仅交互展示路径创建并关闭一次 probe client。非交互路径不新增输出或 probe。
- 告警只包含字段名与数值，不包含配置路径、配置正文或 secret。
- 用户级配置只删除两条精确匹配行；匹配数量、其余字节摘要和权限都必须验证。
- prompt 是路由指导而非新安全边界，真实能力需由 mock 契约和受控真实模型 smoke 分层证明。

## 测试策略

先写解析与显示失败测试，再实现共享解析和刷新路径；增加 protocol 字节断言与 mock replay，验证 Survey、递归聚合和文件交付指令。外部配置修改采用只输出计数/摘要的隐私安全检查。最后运行 context/CLI/identity/Task/HTTP 全量回归，并在项目内临时目录使用真实配置模型进行多轮重复文件扫描 smoke。

## Spec Patch

无。OpenSpec delta spec 已定义解析、展示、告警、执行路由和非交互静默边界。
