## 1. Characterization

- [x] 1.1 固定 parser 顺序、畸形 comment、Memory/front matter/body/fence 行为。
- [x] 1.2 复用 Step 终态/audit、MCP lifecycle、collaboration Store/Runner 全组回归。

## 2. 纯移动

- [x] 2.1 抽取 `protocol_text.py` 并保留 protocol facade。
- [x] 2.2 抽取 `step_types.py` 并保留 Step 唯一编排所有权。
- [x] 2.3 抽取 `mcp_config.py` 并保留 mcp_manager facade。
- [x] 2.4 抽取 `collaboration_routing.py` 并保留 collaboration facade。

## 3. 验证

- [x] 3.1 每个移动点运行聚焦回归和 Ruff。
- [x] 3.2 运行最终全量回归并记录 C901 report-only 基线。
