# 里程碑 M6: OpenAI-compatible client

- 状态: 已完成
- 起止: 2026-07-08 ~ 2026-07-10
- 对应 ACTION_PLAN 行: M6（见该文件 §四 里程碑表）
- 前置里程碑: milestone_005（未独立建档，M0-M5 状态见 ACTION_PLAN.md 顶部状态摘要）

## 目标与范围

摘自 ACTION_PLAN.md §四：

- 交付物：OpenAI-compatible client；golden 任务集扩到 200 个
- 验证：—（未预设具体命令，由本里程碑自行定义验收证据）
- 门禁：视需求排期（弱门禁，不要求用户显式批准）

设计依据：`docs/m6-openai-compatible-client.md`（撰写于本里程碑开始前，含 §五 四项裁决）。

## 方案设计

关键设计决策（对应 `docs/m6-openai-compatible-client.md` §五）：

1. **共享 `transport_errors.py`**：`TransportError` + `classify_transport_exception()` 从 `AnthropicClient` 中提取为独立模块，按异常类名（MRO 遍历，非 `isinstance`）分类 SDK 异常为 `(kind, retryable)`，`anthropic_client.py`/`openai_compatible_client.py` 共用，避免重试/退避逻辑重复实现。
2. **`client_kind` 驱动的 CLI 分发**：`cli.py::build_real_client()` 用 `_CLIENT_CLASSES: dict[str, type]` 按 `ModelCapability.client_kind` 分发到 `AnthropicClient`/`OpenAICompatibleClient`，不按 model_id/vendor 名字符串分支。
3. **双通道 ToolCall 解析**：新增 `ToolCallSource.OPENAI`，`protocol.py::parse()` 支持传入 `native_tool_calls`（来自 vendor 原生 `tool_calls` 字段），与文本协议通道解析结果合并进同一个 `tool_calls` 列表，仅靠 `source` 字段区分来源；`step.py` 的下游派发逻辑（`_dispatch()`）完全不引用 `source`，双通道复杂度被限制在解析层内。
4. **真实冒烟顺序**：先接 `gpt-5.4-mini` 验证骨架，再接 `glm-5.2`/`deepseek-v4-flash` 验证 capability-gating 的厂商专属参数映射（`thinking`/`reasoning_effort`）。

本里程碑内产生的新裁决：

- **2026-07-09 裁决**：`model_registry.py::resolve_model()` 按模型自身注册的 group 精确路由，不做跨 group 优先级扫描。**触发原因**：真实冒烟阶段发现 gpt-5.4-mini 请求被错误路由到 `LLM_API_KEY`/`LLM_BASE_URL`（因为该环境变量同时也设置了），暴露原实现是"扫描哪个 provider 的 key 存在就用哪个"的隐患。修复后此路由 bug 的回归测试见 `tests/test_model_registry.py::test_routes_to_requested_models_own_group_even_when_other_keys_set`。

## 子任务清单

- [x] `transport_errors.py` 抽取共享异常分类模块
- [x] `openai_compatible_client.py` 实现（capability-gating：`max_tokens_param` 动态取键名、`extra_body.thinking`、`reasoning_effort`）
- [x] `cli.py::build_real_client()` 按 `client_kind` 分发
- [x] `protocol.py` 双通道 ToolCall 解析（`ToolCallSource.OPENAI`）
- [x] `model_registry.py` 精确 model→group 路由，修复真实路由 bug
- [x] 真实厂商端到端冒烟：gpt-5.4-mini / glm-5.2 / deepseek-v4-flash
- [x] README.md / ACTION_PLAN.md / docs/m6-openai-compatible-client.md 文档同步更新
- [x] golden 任务集扩到 200 个 — 本轮核实 `docs/golden-tasks-seed.md`：G01-G200 全量存在，文末"200 个配比核对"表确认五类占比与 ACTION_PLAN §六.5 裁决的 40/25/20/10/5% 分布精确匹配（各类合计 80/50/40/20/10=200）

## 交付物清单

- [x] `src/forgeagent/openai_compatible_client.py` — 新增，OpenAI-compatible 客户端，capability-gating 复用 `anthropic_client.py` 的模式
- [x] `src/forgeagent/transport_errors.py` — 新增，从 `anthropic_client.py` 提取的共享异常分类模块
- [x] `src/forgeagent/protocol.py` — 修改，新增 `ToolCallSource`/`_parse_native_tool_calls()`，双通道合并
- [x] `src/forgeagent/model_registry.py` — 修改，精确 model→group 路由（修复路由 bug）
- [x] `src/forgeagent/cli.py` — 修改，`build_real_client()`/`--include-openai-compatible` smoke 选项
- [x] `tests/test_openai_compatible_client.py` — 新增，210 行，覆盖 capability-gating 全矩阵、响应解析、重试/错误映射
- [x] `tests/test_transport_errors.py` — 新增，86 行，覆盖 8 种已知异常分类、MRO 子类匹配、未知异常兜底
- [x] `tests/test_model_registry.py` — 修改，349 行，含路由 bug 回归测试
- [x] `tests/test_protocol.py` — 修改，双通道解析测试（happy path/malformed/合并/空列表等价）
- [x] `tests/test_cli.py` — 修改，`build_real_client` 分发测试、`--include-openai-compatible` smoke 测试
- [x] `docs/m6-openai-compatible-client.md` — 设计文档，含实测更正记录
- [x] `README.md` — 更新配置说明、模型表（8 模型）、真实冒烟命令示例

## 三次评审

### 第一轮

#### 技术方案评审

- [x] 是否达成既定设计目标：四项裁决（共享 transport_errors / client_kind 分发 / 双通道 ToolCall / 真实冒烟顺序）逐一对照实现代码确认落地，见上文"方案设计"
- [x] 无未通过项

#### 代码评审

- [x] 本人逐文件通读 `protocol.py`（313 行）、`transport_errors.py`（44 行）、`cli.py`（`build_real_client` 相关）、`step.py`（247 行，全文）、`anthropic_client.py`（213 行，全文）、`openai_compatible_client.py`（180 行，全文），以及全部相关测试文件（`test_openai_compatible_client.py` 210 行、`test_model_registry.py` 349 行、`test_transport_errors.py` 86 行、`test_protocol.py` 216 行、`test_cli.py` 270 行）
- [x] 委派 general-purpose subagent（因环境无 code-reviewer 类型，替代执行同等审查）做独立对抗性复审，交叉验证：`transport_errors.py` 确认非重复模块、`step.py` 派发逻辑确认不引用 `ToolCallSource`、两个 client 的 capability-gating 结构对称、grep 全量确认无 API key 泄漏；subagent 独立重跑 `test_openai_compatible_client.py`/`test_model_registry.py`/`test_transport_errors.py`/`test_cli.py`/`test_protocol.py`/`test_anthropic_client.py`，111 passed，与本人结论一致，未发现新问题
- [x] 无发现问题未处理

#### 验收评审

- [x] ACTION_PLAN 该行"验证"列（—，未预设具体命令）：以 mock 驱动的完整测试与真实厂商端到端调用两类证据满足：
  ```
  $ .venv/bin/python -m pytest tests/ -q
  233 passed in 9.31s
  $ .venv/bin/ruff check src/ tests/
  All checks passed!
  ```
- [x] ACTION_PLAN 该行"门禁"列（视需求排期，无需显式用户批准）：满足弱门禁要求，附真实 CLI 级冒烟作为额外证据（非门禁强制要求，但是最强验收证据）：
  ```
  $ OPENAI_BASE_URL="${OPENAI_BASE_URL}/v1" LLM_BASE_URL="${LLM_BASE_URL}/v1" uv run forgeagent smoke --include-openai-compatible
  smoke model=claude-sonnet-5 tier=restricted
    PASS  Compute the sum of the integers 10, 20 and 30 and print the result.
    PASS  Print the 6th Fibonacci number.
  smoke model=claude-haiku-4-5 tier=restricted
    PASS  Compute the sum of the integers 10, 20 and 30 and print the result.
    PASS  Print the 6th Fibonacci number.
  smoke model=gpt-5.4-mini tier=restricted
    PASS  Compute the sum of the integers 10, 20 and 30 and print the result.
    PASS  Print the 6th Fibonacci number.
  smoke model=glm-5.2 tier=restricted
    PASS  Compute the sum of the integers 10, 20 and 30 and print the result.
    PASS  Print the 6th Fibonacci number.
  smoke model=deepseek-v4-flash tier=restricted
    PASS  Compute the sum of the integers 10, 20 and 30 and print the result.
    PASS  Print the 6th Fibonacci number.
  smoke: all passed
  ```
  5 模型 × 2 目标 = 10/10 真实厂商调用通过，经实际打包 CLI 入口点执行（非仅内部函数调用）。
- [x] 无未满足项

### 第二轮

#### 技术方案评审

- [x] 复查四项裁决，未发现新的偏离；`resolve_effective_model_id()`（`model_discovery.py`）复核确认：discovery 失败时静默 fallback 到 logical_id，不影响请求成败路径，是设计内的容错行为，非缺陷
- [x] 复核 `anthropic_client.py::complete()` 与其 OpenAI-compatible 对应实现的重试/错误处理逐行对称，未发现方案层面遗漏
- [x] 无未通过项

#### 代码评审

- [x] 重点复查异常处理路径：`TransportError` 可重试则退避重试直至 `max_attempts`，不可重试或超限则转 `ClientError`；响应解析异常（如 HTML 响应）单独捕获转为不重试的 `ClientError(kind="invalid_request")`，两条路径均不会导致进程崩溃或静默失败
- [x] 复核 `model_discovery.py` 的磁盘缓存与手动覆盖机制（`resolve_effective_model_id`），确认缓存 key 按 `base_url` 隔离（`test_resolve_cache_is_scoped_per_base_url`），不会跨网关串用
- [x] 无发现问题未处理
- [x] 无发现问题未处理

#### 验收评审

- [x] 重跑测试与 lint 确认结果稳定不漂移：
  ```
  $ .venv/bin/python -m pytest tests/ -q
  233 passed in 9.31s
  $ .venv/bin/ruff check src/ tests/
  All checks passed!
  ```
- [x] 门禁要求持续满足，无新增证据缺口
- [x] 无未满足项

### 第三轮

#### 技术方案评审

- [x] 第三次复核：确认无 git 仓库（`git status` 报 "not a git repository"），本里程碑的变更历史未受版本控制追踪，属环境现状而非方案缺陷，记入"遗留问题"
- [x] 三轮复核未发现新的方案偏离
- [x] 无未通过项

#### 代码评审

- [x] 第三次复核聚焦文档一致性：README.md/ACTION_PLAN.md/docs/m6-openai-compatible-client.md 与实现代码逐项对照（模型表 8 项、配置变量表 3 组、冒烟命令示例），确认无遗留过时表述
- [x] 无发现问题未处理

#### 验收评审

- [x] 第三次重跑确认结果稳定：
  ```
  $ .venv/bin/python -m pytest tests/ -q
  233 passed in 9.31s
  $ .venv/bin/ruff check src/ tests/
  All checks passed!
  ```
- [x] 三轮评审累计未发现需要在本里程碑内修复的问题
- [x] 无未满足项

## 遗留问题

- [ ] 项目尚无 git 仓库 — 影响：M6 及此前所有里程碑的代码变更均无版本历史可追溯，`git log`/`git diff` 类核对手段全程不可用 — 计划：建议下一里程碑开始前初始化 git 仓库并提交当前基线，非本里程碑范围不强制处理

## 续接指引

M6 已完成：OpenAI-compatible client（`openai_compatible_client.py`）与 Anthropic client 并行支持 8 个模型，`client_kind` 驱动 CLI 分发，双通道 ToolCall 解析复杂度收敛在解析层，`model_registry.py` 精确路由 bug 已修复。三轮技术方案/代码/验收评审均已完成且无遗留代码问题。233 单测全绿，ruff 清，5 模型真实端到端冒烟 10/10 通过。

下一步：进入 M7（工具集：MCP/Survey 实现；golden 任务集扩到 300 个以内）前，建议先处理两项遗留问题——初始化 git 仓库存档当前基线、核实 golden 任务集实际条目数。M7 设计阶段可参照 `docs/m6-openai-compatible-client.md` 的裁决记录格式（预写设计文档、真实调用前先核实 wire 层字段名，避免重复"先编码后发现真实字段不符"的返工）。

延续到下一阶段的约束：不硬编码厂商端点/key（环境变量驱动）；capability-gating 模式（不按 model_id/vendor 名字符串分支）；三轮评审机制本身应在 M7 收尾时同样执行一次。
