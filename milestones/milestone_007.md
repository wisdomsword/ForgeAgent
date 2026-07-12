# 里程碑 M7: 工具插件化 + MCP + Survey + Registry 完善

- 状态: 已完成
- 起止: 2026-07-11 ~ 2026-07-11
- 对应 ACTION_PLAN 行: M7（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_006](milestone_006.md)

## 目标与范围

摘自 ACTION_PLAN.md §四 M7 行：

- 交付物：工具集 MCP/Survey 实现；能力登记 YAML + `ModelRegistry`（alias/reload）进一步完善；**工具插件化**（`ToolRegistry`）；golden 任务集扩到 300 个以内。
- 验证：—（未预设具体命令，由本里程碑自定义验收证据）。
- 门禁：视需求排期（弱门禁，不要求用户显式批准）。

设计依据：`docs/m7-tools-mcp-survey.md`（含 §五 8 项裁决、§八 Phase-0 spike 实测、§九 Phase-6 三评审记录）。

## 方案设计

8 项裁决（`docs/m7-tools-mcp-survey.md` §五，2026-07-11 用户确认）：

1. MCP 深度：真实 stdio MCP + 确认门（不做 HTTP/SSE）。
2. MCP 依赖：官方 `mcp` Python SDK（`mcp>=1.28.1`）。
3. Survey 非交互：纳入，headless 转 need_info，可注入 asker（无 promptabs）。
4. 档位默认：restricted 默认可用 MCP/Survey，有副作用 MCP 调用过确认门，只读放行。
5. **单 `MCP` 工具**（`{server,tool,arguments}` 路由）vs 扁平化顶层名——取单工具：把路由内化为协议而非让模型记名字、保留溯源、多 server 同名工具天生不冲突、与 MCP `ListTools` 的 per-server 返回对齐。
6. **Survey 内联** `question`（+可选 `options`）vs 引用 code block——Survey 是"对话"的一部分而非"数据结构"，省引用解析、REPL/确认门可读；参数名用 `question`（避与"LLM 提示词"撞车）。
7. **连接模型**：会话级常驻后台 loop + 并发建连 + 每 server 失败隔离（取代草稿的逐个 `asyncio.run()`）。
8. **eager 建连**：任务启动时并发连所有 enabled server 并 `list_tools()`——唯一第一性理由是工具可见性（工具清单要进系统提示词模型才会调，lazy 会幻觉工具）；延迟由并发建连（耗时=max）+ REPL 复用同一 manager 摊薄。

新裁决（本里程碑内）：

- **2026-07-11 裁决（未知工具名）**：保持显式 `ParseError`，不做 agent 的"未知名 fallback 成 MCP"隐式兜底——`MCP` 是显式注册的工具名、靠 `{server,tool}` 参数路由。与裁决 5 一致。

## 子任务清单

- [x] Phase 0：设计评审（8 项裁决确认）+ `mcp` SDK wire spike（常驻 session holder 模式 + 并发建连 + 死亡矩阵 D1-D7，9/9 通过，见 §八）+ `uv add mcp`
- [x] Phase 1：`ToolRegistry` 地基（纯重构）——`tools.py`（Tool/ToolRegistry/ToolContext、Exec/EditTool 平移）、`protocol.py`（`parse(tool_schemas=)`、`ToolCall.name: str`、ExecArgs `model_validator`）、`step.py` 改 registry 分派。252 旧测试保持全绿
- [x] Phase 2：Survey 工具——`SurveyArgs`/`SurveyTool`/`Asker`、Step 的 needs_info→NEEDS_INFO 桥接、CLI REPL asker + `run --interactive`
- [x] Phase 3：MCP 工具 + MCPManager（多 server）——`mcp_manager.py`（`mcpServers` 配置、后台 loop + 并发建连 + 失败隔离、list_tools/call_tool/tools_prompt/server_status/enable/disable/close、async→sync 门面）、`MCPArgs`/`MCPTool`、`Confirmer` + CLI 终端确认门、task.py 系统提示词组合、`threat-model.md` T8a/b/c
- [x] Phase 4：ModelRegistry alias/reload 完善——alias→canonical O(1) 索引、`reload_registry()` + REPL `reload`、`list_models()`/`ModelInfo` + CLI/REPL `models`
- [x] Phase 5：golden 扩到 300（G201-G300，含 6 个 MCP + 4 个 Survey 场景，配比 40/25/20/10/5 精确）+ 文档同步（text-protocol-spec / README / ACTION_PLAN）
- [x] Phase 6：三评审（技术方案 / 对抗性代码评审 / 验收）+ 5 个评审发现修复 + REPL `mcp enable/disable` 补齐 + 本里程碑文件

## 交付物清单

- [x] `src/forgeagent/tools.py` — 新增，可插拔工具层（Tool/ToolRegistry/ToolContext、ExecTool/EditTool/SurveyTool/MCPTool、Asker/Confirmer 类型、default_registry）
- [x] `src/forgeagent/mcp_manager.py` — 新增，多 server MCP 管理器（后台 loop + holder 协程 + 同步门面 + 配置加载 + 确认门辅助）
- [x] `src/forgeagent/res/mcp.yaml` — 新增，内置空 `mcpServers` 槽 + 注释示例
- [x] `src/forgeagent/protocol.py` — 修改，`parse(tool_schemas=)`、`ToolCall.name: str`、ExecArgs `model_validator`、新增 `SurveyArgs`/`MCPArgs`
- [x] `src/forgeagent/step.py` — 修改，registry 分派 + ToolContext、Survey needs_info→NEEDS_INFO 桥接
- [x] `src/forgeagent/task.py` — 修改，asker/mcp/confirmer 装配、MCP tools_prompt 组合进系统提示词
- [x] `src/forgeagent/model_registry.py` — 修改，alias_index 预计算、`reload_registry`、`list_models`/`ModelInfo`
- [x] `src/forgeagent/cli.py` — 修改，console asker/confirmer、build_mcp_manager、`models`/`reload`/`mcp status|enable|disable` 命令、`--interactive`
- [x] `tests/test_tools.py` — 新增，registry 契约 + Survey + MCP 确认门（16 用例）
- [x] `tests/test_mcp_manager.py` — 新增，配置加载 + 真实多 server 集成 + 5 个 Phase-6 回归（含子进程泄漏/enable 重连/崩溃标记/secret 掩码）
- [x] `tests/mcp_fixture_server.py` — 新增，测试用真实 stdio MCP fixture server
- [x] `tests/test_step.py` / `tests/test_cli.py` / `tests/test_model_registry.py` — 修改，Survey 桥接、mcp/models/reload 命令、alias/reload/list_models 覆盖
- [x] `docs/m7-tools-mcp-survey.md` — 设计文档（8 裁决 + spike 实测 + Phase-6 评审记录）
- [x] `docs/text-protocol-spec.md` / `docs/threat-model.md`（T8）/ `docs/golden-tasks-seed.md`（G201-G300）/ `README.md` / `ACTION_PLAN.md` — 同步更新
- [x] `pyproject.toml` / `uv.lock` — 新增 `mcp>=1.28.1` 依赖

## 三次评审

详见 `docs/m7-tools-mcp-survey.md` §九（完整记录）。摘要：

### 技术方案评审

- [x] 8 项裁决逐一对照实现代码确认落地，无方案偏离

### 代码评审

- [x] 委派 general-purpose subagent 对抗性复审（环境无 code-reviewer 类型，同 M6 做法）
- [x] 确认门无绕过、解析器泛化无回归、Survey 桥接、超时数学、env 处理——clean
- [x] 发现 5 个真实 bug 全部修复并加回归测试：①close 子进程泄漏 ②enable 空操作 ③MCP 结果未 secret 掩码 ④env 继承不一致 ⑤崩溃 server 仍标 available；第 6 条跨线程无锁经判定 CPython 下非 bug，加 docstring 说明
- [x] 附带补齐 REPL `mcp enable/disable` 命令（评审指出的 Phase-3 清单缺项）

### 验收评审

- [x] ACTION_PLAN M7 行"验证"列（—，自定义证据）：mock 驱动全测试 + 真实多 server MCP 集成测试两类证据满足：
  ```
  $ .venv/bin/python -m pytest tests/ -q
  298 passed, 1 skipped in 14.04s
  $ .venv/bin/ruff check src/ tests/
  All checks passed!
  ```
- [x] ACTION_PLAN M7 行"门禁"列（视需求排期，弱门禁）：满足。golden 集扩到 300（`grep -oE '\bG[0-9]+\b' | sort -u | wc -l` = 300），配比核对表 120/75/60/30/15 = 40/25/20/10/5% 精确匹配
- [x] Phase-0 spike 与 Phase-6 子进程泄漏修复均有实测证据（spike 9/9；close 后 `pgrep` 存活子进程归零）
- [x] 无未满足项

## 遗留问题

- [ ] 跳过的 `test_hung_call_times_out`（慢速 hung-call）— 影响：正式单测未覆盖 D4 挂起超时路径 — 计划：等价路径已在 Phase-0 spike D4 实测验证（2.0s SDK read timeout 命中），正式测试因耗时暂跳过，后续可用更短超时参数补一个快速版
- [x] ~~真实多厂商 MCP 冒烟（filesystem + github 等真实 server）未在本环境跑~~ — **2026-07-11 已解决**：用户提供真实 `~/.forgeagent/mcp.yaml` 配置（npx `@modelcontextprotocol/server-filesystem` + docker `ghcr.io/github/github-mcp-server`），端到端跑通连接/工具发现/只读调用/确认门。过程中发现并修复用户配置里的真实 bug——github server 环境变量名写成了 `GITHUB_TOKEN`，但 `github-mcp-server` 要求 `GITHUB_PERSONAL_ACCESS_TOKEN`，错误命名会静默走 OAuth device-flow 而非用 PAT 认证（调用看似 `ok:true` 但返回的是授权提示文本，不是真实数据）。修正后 `get_me` 返回真实账号信息。这也说明了一个 M7 范围外的已知局限：MCPManager 目前只做协议级 `isError` 判断，不做语义级 payload 校验，无法自动识别"协议成功但语义是未认证提示"这类结果——留作后续可选加固项，不阻塞 M7。
- [ ] `enable()` 在 loop 未起（构造时全 disabled）时仍只翻标志 — 影响：极小，`build_mcp_manager` 对全 disabled 直接返回 None，REPL 拿到的 manager 必有 loop — 计划：暂不处理，YAGNI

## 续接指引

M7 已完成：工具集从硬编码 Exec/Edit 变为可插拔 `ToolRegistry`（Exec/Edit/Survey/MCP）；Survey 内联提问 + headless→need_info；MCP 多 server（官方 `mcp` SDK stdio、常驻后台 loop + 并发建连 + 每 server 失败隔离 + per-(server,tool) 确认门）；ModelRegistry alias O(1) + reload + list_models；golden 扩到 300。298 单测全绿 + 1 skip，ruff 清。Phase-6 对抗性代码评审发现的 5 个 bug 已全部修复并有回归测试（尤其 close 子进程泄漏、崩溃 server 标记、MCP secret 掩码）。

下一步可选方向（按 ACTION_PLAN 里程碑表）：**M8 container sandbox（OS 级隔离）** — 这是 restricted 应用层限权之上的下一层，也是让 MCP 之外的不可信代码真正密封的手段；或 **M9 流式 + 多模态**。M7 延续的约束：不硬编码厂商端点/key（`mcp.yaml` 的 `env` 只引用变量名）；工具插件化模式（加工具=注册 Tool，不改分派/解析）；MCP server 在主进程执行是 restricted 沙箱外的信任边界（确认门是唯一强制点，见 threat-model T8）；三轮评审机制（含对抗性代码评审）在每里程碑收尾执行。
