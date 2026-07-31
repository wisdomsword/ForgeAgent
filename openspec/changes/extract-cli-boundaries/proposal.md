## Why

`src/forgeagent/cli.py` 已增长到 3226 行、129220 字节并承担 parser/config、协作装配、REPL、HTTP/client 等多类职责，使评审、故障定位和局部验证成本持续上升。M41 在不改变任何 CLI、HTTP 或运行时契约的前提下，先用六项 Rewrite/Dependency 门禁建立退出条件，再做可回退的职责提取。

## What Changes

- 建立 performance、reliability、maintenance cost、compatibility、team capability、migration/rollback risk 六项基线、阈值、证据、迁移和回滚触发器。
- 将 parser/config、collaboration adapter、REPL、HTTP/client 代码提取到职责明确的内部模块，`forgeagent.cli` 继续作为兼容 façade 和 console-script 入口。
- 保持命令、参数、默认值、帮助文本、退出码、stdout/stderr、HTTP 请求/响应、既有导入与测试替换点不变。
- 使用按边界执行的测试和提交逐步迁移；任一硬阈值不满足时停止并回退 M41 自身提取，不触碰进入 M41 前的用户工作区改动。
- 不引入新依赖、语言、配置面、运行时能力、数据迁移或发布目标。

## Capabilities

### New Capabilities

- `cli-boundary-maintainability`: 定义 CLI 内部边界、兼容 façade、六项 Rewrite/Dependency 退出门禁和可回退验证要求。

### Modified Capabilities

无。现有 CLI、REPL、HTTP、Loop、Collaboration 和审计行为规格均保持不变。

## Impact

- 代码：`src/forgeagent/cli.py` 及新增的 `src/forgeagent/_cli_*.py` 内部模块。
- 测试：既有 CLI/协作/HTTP 测试继续作为兼容门禁，并新增结构与基线验证。
- 文档：新增 M41 六项基线、技术设计、实施计划、验证报告和里程碑记录。
- 依赖/API/数据：无新增依赖；无 public API、schema、配置或持久化数据变化。
