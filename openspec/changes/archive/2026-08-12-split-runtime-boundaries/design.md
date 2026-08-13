## Decisions

1. 顺序为 protocol、step、mcp_manager、collaboration，每个移动点先补 characterization 并单独回归。
2. `protocol.py` 保留 schema、错误投影与 `parse()` facade；内部模块只扫描文本边界。
3. `Step` 继续唯一拥有 round 循环、派发、审计和终态顺序；内部模块只持有公开重导出的类型和历史序列化。
4. MCP holder、generation 与 shutdown 状态机保持同文件，只移动配置 schema/加载。
5. collaboration Store/Runner/状态不变量保持同文件，只移动独立纯路由函数。

## Non-Goals

- 不引入通用 persistence 或 lifecycle framework。
- 不在本 change 开启阻塞 C901，也不继续拆分高耦合状态机。
