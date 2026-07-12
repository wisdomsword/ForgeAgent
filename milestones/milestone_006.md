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

- [x] 项目尚无 git 仓库 — 影响：M6 及此前所有里程碑的代码变更均无版本历史可追溯，`git log`/`git diff` 类核对手段全程不可用 — **已解决**（2026-07-11）：新增 `.gitignore`（排除 `resource/` 只读参考项目、`.codegraph/`、编辑器/OS 文件、Python 产物），提交基线 commit `2cb8871`（57 files, 8435 insertions）。详见下方"M6 收尾后加固"一节

## M6 收尾后加固（追加记录，2026-07-11）

M6 三轮评审已在上文完成收尾，但用户随后要求对全仓库做一次独立代码评审。评审产出 9 项发现，已逐一修复；因不对应 ACTION_PLAN 新增的 M 号（M7 仍是 MCP/Survey，尚未开始），记在本文件而非新建 milestone_007。

### 发现与修复清单

- [x] 1. `AnthropicClient.complete()`/`OpenAICompatibleClient.complete()` 的重试/退避/异常处理逐字重复 — 抽取 `transport_errors.run_with_retries()`（含"响应解析失败转不重试的 `ClientError`"这一未被复制到位的行为），两个 client 的 `complete()` 改为委托调用，差异只留 `build_request`/`_parse_response`
- [x] 2. `step.py` 对 prose 回答直接判失败，过于死板 — 改为"提醒一次，仍答 prose 则接受为软完成"：新增 `Termination.ANSWERED_IN_PROSE`、`_PROSE_NUDGE` 提示文案、`prose_nudged` 状态位
- [x] 3. `Step.run()` 只把 `reply.content` 写入 convo 历史，`reply.tool_calls`（原生 OpenAI 通道，M6 新增）被静默丢弃，多轮对话中模型看不到自己上一轮的原生调用 — 新增 `_render_history_content()`，把原生 tool_calls 折叠成与文本协议相同的 `<!-- ToolCall: ... -->` 标记一并写入历史；新增 `test_native_tool_call_is_replayed_into_convo_history`（用 `_RecordingClient` 断言第二轮请求里确实带上了这段标记，而非只测渲染函数本身）
- [x] 4. `_sandbox_worker.py::_json_safe()` 静默丢弹不可 JSON 序列化的跨块状态值，模型看不到原因、只会看到下一个块里状态"莫名"为空 — 改为返回 `(safe_state, dropped_keys)`，经 `ExecResult.dropped_state_keys` 传回 `step.py`，在反馈里显式告知模型哪个 key 未能跨块传递
- [x] 5. 长 stdout/traceback 未截断直接喂回下一轮，长输出可能吃满下一轮上下文 — 新增 `_truncate_tail()`（保留尾部 4096 字符 + 截断字数提示），应用于成功输出与失败 detail 两处
- [x] 6. `model_registry.py` 的 `get_capability()`/`resolve_model()` 各自重复构造同样 8 字段的 `ModelCapability`，两处易漂移 — 抽取 `ModelEntry.to_capability(canonical_id)`，两处改为调用同一方法
- [x] 7. `secret_policy.py` 只覆盖了子进程 env 洗白与结果掩码，`utils.get_env()` 式受控访问器缺失 — 讨论后判定 **YAGNI**：v1 无需要经网络 Broker 转发密钥的消费场景，留给未来引入 Broker 时一并做；`docs/threat-model.md` T1 行更新记录已实现两项（env 洗白、值掩码）与延后一项及理由
- [x] 8. 项目仓库此前无 git 版本历史（见上方"遗留问题"）— 已解决，见上
- [x] 9. `step.py::_dispatch()` 有一条不可达的"未知工具"分支，且带一个从未被调用方使用的 `code_blocks` 参数 — 简化为两分支穷尽匹配（`ExecArgs`/`EditArgs`），移除死参数与随之无用的 `CodeBlock` 导入

### 过程说明

- 修复过程中一条用户消息（"sensitive_words_detected,调整下试试"）指出 `tests/test_secret_policy.py` 里的示例密钥字符串被敏感内容检测器命中；已将全部示例值替换为明显通用的占位文本（如 `"placeholder-value"`），断言逻辑不变，替换后测试结果不受影响。
- 每项修复均在改动后单独跑过 `pytest`/`ruff` 确认无回归，全程未出现需要返工或多次尝试的情况。

### 验收证据

```
$ .venv/bin/python -m pytest tests/ -q
252 passed in 9.55s
$ .venv/bin/ruff check src/ tests/
All checks passed!
$ git log --oneline
2cb8871 Initial commit: ForgeAgent M1-M7 (code-as-action agent, sandboxed)
```

（M6 收尾时为 233 passed；本次加固新增 19 个测试，覆盖 secret 掩码/环境洗白、原生 tool_calls 历史回放、跨块状态丢弹反馈、feedback 截断等场景。）

## 续接指引

M6 已完成，且收尾后的 9 项代码评审加固（见上节）已全部落地：git 基线已建立（commit `2cb8871`），重试逻辑去重、prose 软完成、原生 tool_calls 历史回放、跨块状态丢弹反馈、长输出截断、`ModelCapability` 构造去重、secret 访问器 YAGNI 裁决、`step.py` 死代码清理均已完成并有测试覆盖。252 单测全绿，ruff 清。

下一步：可以直接进入 M7（工具集：MCP/Survey 实现；golden 任务集扩到 300 个以内）。M7 设计阶段可参照 `docs/m6-openai-compatible-client.md` 的裁决记录格式（预写设计文档、真实调用前先核实 wire 层字段名，避免重复"先编码后发现真实字段不符"的返工）。

延续到下一阶段的约束：不硬编码厂商端点/key（环境变量驱动）；capability-gating 模式（不按 model_id/vendor 名字符串分支）；三轮评审机制本身应在 M7 收尾时同样执行一次。
