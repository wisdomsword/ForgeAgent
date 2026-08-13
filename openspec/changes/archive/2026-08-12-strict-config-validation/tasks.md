## 1. 配置边界回归

- [x] 1.1 编写 RED：未知根键/叶字段、非 mapping YAML、MCP 布尔字符串或数字、非有限 temperature。
- [x] 1.2 确认失败来自当前静默忽略、隐式转换或非有限值接受，而非测试支架。

## 2. 最小实现

- [x] 2.1 每份 models/config/MCP YAML 在 merge 前验证根节点与允许顶层键。
- [x] 2.2 对 ModelEntry、GroupConfig、Registry、MCPServerConfig 配置 `extra="forbid"`。
- [x] 2.3 仅收紧 MCP `enabled` / `required` 为严格布尔，保留 `autoApprove` alias。
- [x] 2.4 temperature 使用 FiniteFloat；对外配置错误采用带来源的稳定文案。

## 3. 验证

- [x] 3.1 运行 model registry、MCP manager 与 model 聚焦 pytest。
- [x] 3.2 运行 Ruff、OpenSpec strict 和关联 CLI 配置回归。
