## Context

默认 ToolRegistry 注册七个内置工具，但 protocol.md 只说明 Exec/Edit，并把所有
执行型目标引向 Python/Exec。M16 的隔离 HTTP 黑盒测试证明：真实模型在没有用户
identity 或 MCP 动态目录时，即使从用户消息得到完整 FileWrite marker，仍连续回答
prose。工具实现、parser 和 headless confirmer 均未被触发。

## Goals / Non-Goals

**Goals:**

- 让包内固定协议与默认内置工具注册表保持一致。
- 让无自定义 identity 的模型得到每个工具的名称、精确参数和简短使用条件。
- 保持系统提示的稳定前缀和现有身份层顺序。

**Non-Goals:**

- 不修改 ToolRegistry、parser、HTTP API、allowlist、确认门或工具实现。
- 不为 MCP 复制静态目录；MCP 继续使用运行时发现的动态工具段。
- 不保证任意真实模型一定遵循提示，失败仍由现有 INCONCLUSIVE 判据处理。

## Decisions

1. 直接扩展包内 protocol.md，不新增动态 prompt builder。默认工具集合是现有稳定
   协议面，静态文本最小且保持 prompt-cache 前缀稳定。
2. 将开头规则改为“直接工具匹配时使用直接工具，否则使用 Python/Exec”，消除
   FileWrite 与系统级 Exec-only 指令冲突。
3. 为 Survey、WebFetch、FileRead、FileWrite、FileList 各提供一个紧凑 ToolCall
   marker 和参数说明；Exec/Edit 的既有详细示例保留。
4. 在 identity 组合测试中断言默认 prompt 含完整工具目录及 FileWrite 精确 marker，
   以防注册表和 prompt 再次漂移。
5. M16 黑盒以目标 FileWrite 的 operation-linked confirmation/tool 事件和最终文件
   状态为权威证据。额外成功工具可能产生替代效果，继续判为 INCONCLUSIVE；
   额外失败工具没有成功执行效果，只保留在审计中，不否定目标 FileWrite 决策。

## Risks / Trade-offs

- [固定 prompt 增长会增加少量输入 token] → 使用单行紧凑示例，不复制工具实现细节。
- [未来新增默认工具时可能再次漂移] → 测试显式锁定当前默认工具名称；新增工具必须
  同步更新协议断言。
- [模型仍可能不遵循文本协议] → 保留 M16 真实模型黑盒与 INCONCLUSIVE，不把提示
  存在误当作真实遵循证据。
- [失败工具可能在报错前产生部分文件副作用] → denied 阶段要求 allowed root 全空，
  allowed 阶段要求除精确目标外无其他 artifact；任一意外落盘仍判为 INCONCLUSIVE。
