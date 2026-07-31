## Context

M30 的协议模型和 `MCPDescribeTool` 已进入 M44 代码，但 manager 查询方法、目录边界测试、专属主规格和归档证据没有进入同一 Git 基线。结果是 registry 会向模型公开 `MCPDescribe`，真实 manager 却无法执行该调用；工具层 fake 测试因为自行提供 `describe_tool()` 而保持绿色。

本 change 把修复限制在 discovery 公开投影层。现有连接、调用、确认、外部动作 receipt、CLI 诊断和内部 raw identity 路由均不改变。

## Goals / Non-Goals

**Goals:**

- 让真实 `MCPManager` 完整实现已被工具层消费的只读查询接口。
- system prompt 只注入有界目录，详情通过 `MCPDescribe` 按需读取。
- 用真实 manager 集成测试证明接口、边界和无副作用语义。
- 恢复无占位的 `mcp-progressive-disclosure` 主规格和可追溯验证证据。

**Non-Goals:**

- 不修改 MCP SDK 生命周期、协议、确认、receipt 或错误分类。
- 不新增缓存、分页、自动选工具、Code Mode、Worker、HTTP 路由或依赖。
- 不从主工作区批量复制未审查文件。

## Decisions

### 1. manager 是 discovery 快照的唯一所有者

`MCPManager.describe_tool(server, tool)` 遍历 `list_tools()` 的当前 public `MCPToolInfo`，只匹配精确 public server/tool pair，并返回 deep copy。查询不提交 coroutine、不连接 server、不触发确认或 receipt。相较于让工具直接读取 `_states`，该方案保持 manager 封装和当前 available 过滤语义。

### 2. 恢复最小有界目录而非新抽象

`tools_prompt()` 继续由 manager 渲染。描述先把 Unicode 控制/格式/代理/行分隔字符投影为空格，再折叠空白并截取 160 字符；每项附加 `auto-approved` 或 `confirmation required`。不新建 helper 模块，因为逻辑只服务 manager prompt 且不足以形成共享抽象。

### 3. 测试必须跨越真实接口边界

保留工具的局部安全投影测试，同时增加使用真实 `MCPManager` 的测试：构造 available discovery 快照，通过 `MCPDescribeTool.run()` 查询并断言成功、无 receipt、无确认和无网络调度。该测试会在 manager 方法再次缺失时直接失败，避免 fake 自洽。

### 4. 历史材料仅作为候选证据

主工作区中 M30 代码、测试、规格和归档只读比较。只把与本 proposal/spec 一致的最小差异重新实现到 M45 工作区；`TBD` Purpose、过期计数和无法证明的完成声明不复制。

## Risks / Trade-offs

- **风险：目录摘要截断丢失参数细节。** → 目录明确指向 `MCPDescribe`，完整 schema 只按需返回。
- **风险：同名 raw identity 与 public label 混淆。** → 查询只接受当前 `list_tools()` 中已经过 manager 安全投影的精确 pair。
- **风险：恢复历史实现时带入无关脏改动。** → 只修改 manager、相关测试和本 change 产物，并逐文件 diff。
- **代价：模型可能多消耗一次详情调用。** → 这是渐进披露的预期成本，不增加自动调用或缓存复杂度。

## Migration Plan

1. 先增加真实 manager 集成失败测试并确认因缺少方法失败。
2. 恢复 manager 查询和有界目录最小实现，运行 MCP/Tool/Task/CLI 聚焦回归。
3. 同步无占位主规格，执行全量测试、Ruff、format、build 和 OpenSpec strict。
4. 若任何兼容测试失败，回滚本 change 提交即可；无数据或状态迁移。

## Open Questions

无。未来目录分页或动态 schema 版本化必须基于真实规模/一致性需求另立 change。
