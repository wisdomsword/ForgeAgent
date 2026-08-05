---
change: improve-context-limits-and-execution-guidance
design-doc: docs/superpowers/specs/2026-08-05-improve-context-limits-and-execution-guidance-design.md
base-ref: 2c8f528224d79a91b6cbe3476db8b6b979b236a4
archived-with: 2026-08-05-improve-context-limits-and-execution-guidance
---

# Context 限额可观察性与执行指引 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一解析当前模型的反馈限额，在真实交互 REPL 边界安全展示其生效值，并让固定执行协议按完整目标选择 Survey、直接工具或 Python/Exec。

**Architecture:** 在 `context.py` 用一个不可变的纯解析结果承载 input budget、adaptive/configured/effective 值和低值标记；既有 policy、Registry 校验和注入 client 校验都消费它。REPL 只在真实交互启动、成功 `/model`、成功 `/reload` 时将这个结果交给 renderer，失败路径不发布候选状态；固定协议只修改路由文字，保持工具 schema、终态和安全边界不变。

**Tech Stack:** Python 3.11、`dataclasses`、Pydantic v2、Rich `Text`、pytest、ruff、mypy、OpenSpec；不新增依赖。

## Global Constraints

- `base-ref` 固定为 `2c8f528224d79a91b6cbe3476db8b6b979b236a4`；实现前先确认工作树中用户已有改动，绝不回退无关文件。
- 不新增依赖、新配置键、HTTP request/result schema、FileList 递归/cursor/分页或任意工具输出归档。
- 保留既有公式：`input_budget=floor(context_window*utilization_ratio)-effective_output`，`adaptive_round=floor(input_budget*0.10)`，`adaptive_tool=floor(adaptive_round*0.25)`；显式 configured 值优先且低值仅告警，不自动覆盖。
- 保留正数与 `round >= tool` 错误语义；HTTP、`run`、管道 REPL、日志及 response 不新增限额 banner。
- renderer 只能消费 `ResolvedFeedbackLimits` 和既有公开启动字段，不能读取配置文件、输出路径、endpoint、环境值、配置正文或 secret。
- 固定协议不改变内置工具名/JSON schema、`utils.set_state(key, value)`/`utils.get_state(key)` 签名、直接 prose 终态规则、sandbox 或确认权威边界；prompt 不是安全控制。
- 外部配置修改仅在 Tasks 1-3 代码专项验证通过后执行；只用 `apply_patch` 处理 `~/.forgeagent/config.yaml` 中两条完整目标行，绝不 YAML 解析后回写、打印正文或暴露 API key。
- 每项先 RED 后 GREEN；所有命令以 `rtk` 开头，Python 测试使用 `rtk uv run pytest`；每项完成即进行单独 conventional commit。

## 文件结构

- 修改 `src/forgeagent/context.py`：定义共享的冻结 `ResolvedFeedbackLimits` 与 `resolve_feedback_limits()`，并让 `SlidingWindowContextPolicy` 保留该结果。
- 修改 `src/forgeagent/_cli_http.py`：让 Registry/client validator 返回共享解析结果，仍可被仅校验调用方忽略。
- 修改 `src/forgeagent/_cli_repl.py`：为交互边界解析并渲染限额，保障 probe 生命周期和失败时的旧状态保留。
- 修改 `src/forgeagent/cli.py`：将 resolver/validator 的返回值和新 REPL binding 原样接通，维持 facade 的 monkeypatch 兼容性。
- 修改 `src/forgeagent/res/prompts/protocol.md`：替换工具路由说明，保留现有所有 ToolCall 示例与 Runtime API 文本。
- 修改 `tests/test_context.py`、`tests/test_cli.py`、`tests/test_identity.py`、`tests/test_task.py`：覆盖公式、交互展示、固定协议字节契约和确定性多轮 mock replay。
- 不增加永久 smoke helper；最终验证在临时目录构造受控重复文件 fixture，并通过真实 CLI/配置模型运行一次可复现 smoke。

archived-with: 2026-08-05-improve-context-limits-and-execution-guidance
---

### Task 1: 共享反馈限额解析与 policy 回归

**Files:**
- Modify: `src/forgeagent/context.py:38-102,151-169`
- Modify: `src/forgeagent/_cli_http.py:31,151-158`
- Modify: `tests/test_context.py:7-19,139-220`
- Modify: `tests/test_cli.py`（Registry/client context validator 的既有测试附近）

**Interfaces:**
- Consumes: `ModelCapability`, `GenerationParams | None`, `ContextConfig`。
- Produces: `@dataclass(frozen=True) class ResolvedFeedbackLimits`，字段依次为 `input_budget: int`、`adaptive_round_feedback_limit: int`、`adaptive_tool_result_limit: int`、`configured_round_feedback_limit: int | None`、`configured_tool_result_limit: int | None`、`effective_round_feedback_limit: int`、`effective_tool_result_limit: int`、`round_configured_below_adaptive: bool`、`tool_configured_below_adaptive: bool`。
- Produces: `resolve_feedback_limits(capability: ModelCapability, params: GenerationParams | None, config: ContextConfig) -> ResolvedFeedbackLimits`；`validate_context_policy(model: str, registry: Registry, context_config: ContextConfig) -> ResolvedFeedbackLimits` 与 `validate_client_context_policy(client: ModelClient, context_config: ContextConfig) -> ResolvedFeedbackLimits`。
- Produces: `SlidingWindowContextPolicy.limits: ResolvedFeedbackLimits`，同时保留既有 `input_budget`、`round_feedback_limit`、`tool_result_limit` property 的 `int` 返回类型。

- [x] **Step 1: 写失败的 resolver 与 policy 测试**

```python
from forgeagent.context import ResolvedFeedbackLimits, resolve_feedback_limits


def test_resolve_feedback_limits_uses_existing_formula_and_keeps_policy_properties():
    capability = _capability(1000, 200)
    config = ContextConfig()

    limits = resolve_feedback_limits(capability, GenerationParams(max_output_tokens=100), config)
    policy = SlidingWindowContextPolicy(capability, GenerationParams(max_output_tokens=100), config)

    assert limits == ResolvedFeedbackLimits(
        input_budget=700,
        adaptive_round_feedback_limit=70,
        adaptive_tool_result_limit=17,
        configured_round_feedback_limit=None,
        configured_tool_result_limit=None,
        effective_round_feedback_limit=70,
        effective_tool_result_limit=17,
        round_configured_below_adaptive=False,
        tool_configured_below_adaptive=False,
    )
    assert policy.limits is limits or policy.limits == limits
    assert (policy.input_budget, policy.round_feedback_limit, policy.tool_result_limit) == (700, 70, 17)


def test_resolver_marks_each_explicit_low_value_without_overriding_it():
    limits = resolve_feedback_limits(
        _capability(1000, 200),
        GenerationParams(max_output_tokens=100),
        ContextConfig(round_feedback_max_tokens=60, tool_result_max_tokens=10),
    )

    assert (limits.effective_round_feedback_limit, limits.effective_tool_result_limit) == (60, 10)
    assert (limits.round_configured_below_adaptive, limits.tool_configured_below_adaptive) == (True, True)


def test_resolver_recomputes_from_new_capability_and_rejects_existing_invalid_values():
    assert resolve_feedback_limits(_capability(2000, 200), None, ContextConfig()).adaptive_round_feedback_limit == 140
    assert resolve_feedback_limits(
        _capability(1000, 200), GenerationParams(max_output_tokens=100), ContextConfig(round_feedback_max_tokens=70)
    ).round_configured_below_adaptive is False
    with pytest.raises(ValueError, match="round feedback limit"):
        resolve_feedback_limits(_capability(1000, 200), None, ContextConfig(tool_result_max_tokens=80))
```

- [x] **Step 2: 运行 RED 测试**

Run: `rtk uv run pytest -q tests/test_context.py -k 'resolve_feedback_limits or policy_reserves_effective_output'`

Expected: FAIL during collection because `ResolvedFeedbackLimits` and `resolve_feedback_limits` are not importable.

- [x] **Step 3: 实现单一解析结果并接入所有 validator**

```python
@dataclass(frozen=True)
class ResolvedFeedbackLimits:
    input_budget: int
    adaptive_round_feedback_limit: int
    adaptive_tool_result_limit: int
    configured_round_feedback_limit: int | None
    configured_tool_result_limit: int | None
    effective_round_feedback_limit: int
    effective_tool_result_limit: int
    round_configured_below_adaptive: bool
    tool_configured_below_adaptive: bool


def resolve_feedback_limits(
    capability: ModelCapability, params: GenerationParams | None, config: ContextConfig
) -> ResolvedFeedbackLimits:
    effective_output = params.max_output_tokens if params and params.max_output_tokens is not None else capability.max_output_tokens
    input_budget = math.floor(capability.context_window * config.utilization_ratio) - effective_output
    if input_budget <= 0:
        raise ValueError("input budget must be positive")
    adaptive_round = math.floor(input_budget * 0.10)
    adaptive_tool = math.floor(adaptive_round * 0.25)
    round_limit = config.round_feedback_max_tokens if config.round_feedback_max_tokens is not None else adaptive_round
    tool_limit = config.tool_result_max_tokens if config.tool_result_max_tokens is not None else adaptive_tool
    if round_limit <= 0:
        raise ValueError("round feedback limit must be positive")
    if tool_limit <= 0:
        raise ValueError("tool result limit must be positive")
    if round_limit < tool_limit:
        raise ValueError("round feedback limit must be >= tool result limit")
    return ResolvedFeedbackLimits(input_budget, adaptive_round, adaptive_tool, config.round_feedback_max_tokens, config.tool_result_max_tokens, round_limit, tool_limit, config.round_feedback_max_tokens is not None and config.round_feedback_max_tokens < adaptive_round, config.tool_result_max_tokens is not None and config.tool_result_max_tokens < adaptive_tool)
```

Store `self._limits = resolve_feedback_limits(capability, params, config)` in `SlidingWindowContextPolicy`; delegate its three legacy property values to `self._limits`. Replace the Registry validator body with `return resolve_feedback_limits(get_capability(model, registry), None, context_config)` and the client validator body with `return resolve_feedback_limits(client.capability, None, context_config)`, both annotated as `ResolvedFeedbackLimits`; no caller is required to consume the result yet.

- [x] **Step 4: 运行 GREEN 与局部静态检查**

Run: `rtk uv run pytest -q tests/test_context.py tests/test_cli.py -k 'context or policy or model_switch'`

Expected: PASS; pre-existing invalid budget/order tests retain their exact exception fragments.

Run: `rtk uv run ruff check src/forgeagent/context.py src/forgeagent/_cli_http.py tests/test_context.py tests/test_cli.py`

Expected: PASS with no diagnostics.

- [x] **Step 5: Commit**

```bash
rtk git add src/forgeagent/context.py src/forgeagent/_cli_http.py tests/test_context.py tests/test_cli.py
rtk git commit -m "feat: resolve feedback limits centrally"
```

### Task 2: 交互 REPL 显示、刷新与静默边界

**Files:**
- Modify: `src/forgeagent/_cli_repl.py:28-31,328-370,384-635`
- Modify: `src/forgeagent/cli.py:161-162,1190-1238`
- Modify: `tests/test_cli.py:280-370,3605-3840,5000-5120`

**Interfaces:**
- Consumes: `ResolvedFeedbackLimits` from Task 1; `validate_context_policy(model: str, registry: Registry, context_config: ContextConfig) -> ResolvedFeedbackLimits`; injected `ModelClient.capability`.
- Produces: `resolve_repl_feedback_limits(model: str, registry: Registry | None, context_config: ContextConfig, client_factory: ClientFactory, use_registry_snapshot: bool, validate_context_policy: Callable[[str, Registry, ContextConfig], ResolvedFeedbackLimits]) -> ResolvedFeedbackLimits | None`.
- Produces: `render_startup_summary(console: Console, *, model: str, tier: Tier, root: str, diagnostics: Sequence[MCPServerDiagnostic], feedback_limits: ResolvedFeedbackLimits | None = None) -> None`; it appends `feedback round <effective> / tool <effective>` and emits at most one `Text` warning.
- Contract: Registry snapshot uses selected capability directly; injected client without a Registry creates exactly one display-only probe only in interactive mode and calls `close()` in `finally`; noninteractive execution returns `None` and never probes.

- [x] **Step 1: 写失败的交互边界测试**

```python
def test_startup_summary_displays_effective_limits_and_one_bounded_low_warning():
    console = _terminal_console()
    limits = resolve_feedback_limits(
        _capability(), None,
        ContextConfig(round_feedback_max_tokens=60, tool_result_max_tokens=10),
    )
    render_startup_summary(
        console, model="mock", tier="trusted", root="/project",
        diagnostics=(), feedback_limits=limits,
    )

    text = console.export_text()
    assert "feedback round 60 / tool 10" in text
    assert text.count("feedback limit warning") == 1
    assert "round configured 60 < adaptive" in text
    assert "tool configured 10 < adaptive" in text
    assert "API_KEY" not in text and "config.yaml" not in text


def test_model_and_reload_refresh_only_after_success(monkeypatch):
    old_registry = load_registry()
    new_registry = old_registry.model_copy(deep=True)
    new_registry.models["claude-haiku-4-5"].context_window = 20_000
    console = _terminal_console()
    inputs = iter(["/model claude-haiku-4-5", "/reload", "/reload", "quit"])
    reloads = iter([new_registry, Registry.model_validate({})])
    monkeypatch.setattr(cli_module, "_interactive_repl", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(cli_module, "reload_registry", lambda: next(reloads))
    monkeypatch.setattr(cli_module, "load_context_config", lambda: ContextConfig())

    cli_module.repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=cli_module.build_real_client,
        console=console,
        read_line=lambda _: next(inputs),
        registry=old_registry,
        use_registry_snapshot=True,
    )

    text = console.export_text()
    assert text.count("feedback round ") == 3
    assert "switched" in text and "reloaded" in text and "reload failed" in text
    assert text.rfind("feedback round ") < text.rfind("reload failed")


def test_noninteractive_repl_does_not_render_or_construct_display_probe(monkeypatch):
    probes = []
    cli_module.repl(tier="trusted", model="injected", client_factory=lambda _: probes.append(object()), console=_console(), read_line=lambda _: "quit")
    assert probes == []
```

单独增加 `ProbeClient(MockClient)` fixture，令 `close_calls = 0` 并覆盖 `close()` 递增。通过 `_cli_repl.repl()` 的测试 binding 显式令 `interactive_repl` 返回 `True`，断言注入 client 的交互启动只 probe 一次且只 close 一次；普通注入 `read_line` 的既有非交互测试必须继续返回 `False` 且不 probe。再增加无参数 `/model` 测试，断言只展示模型列表，`feedback round ` 计数仍只有启动那一次。failed reload 测试确保失败后不发布候选摘要或告警。

- [x] **Step 2: 运行 RED 测试**

Run: `rtk uv run pytest -q tests/test_cli.py -k 'feedback_limits or model_and_reload_refresh or display_probe'`

Expected: FAIL because the renderer has no `feedback_limits` parameter and the REPL has no display-only resolution path.

- [x] **Step 3: 实现纯展示解析和受限渲染**

```python
from collections.abc import Sequence


def render_startup_summary(
    console: Console,
    *,
    model: str,
    tier: Tier,
    root: str,
    diagnostics: Sequence[MCPServerDiagnostic],
    feedback_limits: ResolvedFeedbackLimits | None = None,
) -> None:
    summary_fields = ["Ready", f"model {model}", f"sandbox {tier}", f"project {root}"]
    if feedback_limits is not None:
        summary_fields.append(
            f"feedback round {feedback_limits.effective_round_feedback_limit} / "
            f"tool {feedback_limits.effective_tool_result_limit}"
        )
    console.print(Text(" | ".join(summary_fields)))
    if feedback_limits is not None and (
        feedback_limits.round_configured_below_adaptive or feedback_limits.tool_configured_below_adaptive
    ):
        fields = []
        if feedback_limits.round_configured_below_adaptive:
            fields.append(f"round configured {feedback_limits.configured_round_feedback_limit} < adaptive {feedback_limits.adaptive_round_feedback_limit}")
        if feedback_limits.tool_configured_below_adaptive:
            fields.append(f"tool configured {feedback_limits.configured_tool_result_limit} < adaptive {feedback_limits.adaptive_tool_result_limit}")
        console.print(Text("feedback limit warning | " + " | ".join(fields)))
```

Add the helper specified above. For a Registry snapshot, call the returned validator result. For an injected client, create the probe only inside `if interactive`, call `resolve_feedback_limits(probe.capability, None, current_context)`, and always call its optional `close()` in `finally`. Resolve candidates before publishing `/model` or `/reload`; on exceptions print the existing failure line and keep the previous `model`, `current_registry`, `current_context`, and last rendered limits. Pass the new binding from `cli.repl`; preserve all existing noninteractive paths by never invoking the helper there.

- [x] **Step 4: 运行 GREEN、回归与静态检查**

Run: `rtk uv run pytest -q tests/test_cli.py tests/test_context.py -k 'startup_summary or feedback_limits or reload or model or noninteractive'`

Expected: PASS; exactly one warning for one or both low fields, no warning when configured equals adaptive, and all piping/injected-reader tests remain quiet.

Run: `rtk uv run ruff check src/forgeagent/_cli_repl.py src/forgeagent/cli.py tests/test_cli.py`

Expected: PASS with no diagnostics.

- [x] **Step 5: Commit**

```bash
rtk git add src/forgeagent/_cli_repl.py src/forgeagent/cli.py tests/test_cli.py
rtk git commit -m "feat: show resolved feedback limits in repl"
```

### Task 3: 固定协议按完整目标路由并作确定性 replay

**Files:**
- Modify: `src/forgeagent/res/prompts/protocol.md:1-80`
- Modify: `tests/test_identity.py:38-200`
- Modify: `tests/test_task.py`（现有 `MockClient` 多轮 ToolCall replay 测试区域）

**Interfaces:**
- Consumes: 现有固定 `ToolCall`/`CodeBlockStart`/`Memory` 文本协议、`Task.run()` 的反馈循环和默认工具注册表。
- Produces: 固定协议的六条顺序路由规则：知识直接回答；缺信息 Survey 并在同一 Task 继续；可完整完成的单工具；递归/哈希/聚合/转换/跨文件比较 Exec；大结果/文件交付写获准路径后只回复摘要/数量/路径；禁止用浅层/截断样本宣称完成。
- Contract: 保留所有工具名字、精确 JSON schema、`utils` API、memory-only prose 语义、YAML 终态、安全/确认文字和 identity section order。

- [x] **Step 1: 写失败的协议与多轮 replay 测试**

```python
def test_default_protocol_routes_by_complete_goal_and_preserves_contracts():
    rendered = compose_system_prompt(ApprovedIdentity(None, None, None, None))

    assert "Pure knowledge questions" in rendered
    assert "call Survey" in rendered and "continue the same Task" in rendered
    assert "can complete the entire goal" in rendered
    assert "recursive traversal" in rendered and "Python/Exec" in rendered
    assert "write the complete result to an approved file" in rendered
    assert "truncated sample" in rendered
    assert '<!-- ToolCall: {"name":"FileList","arguments":{"path":"."}} -->' in rendered
    assert 'utils.set_state("key", value)' in rendered


def test_protocol_mock_replay_keeps_survey_context_then_exec_and_file_delivery(tmp_path):
    client = MockClient(script=[
        _reply('<!-- ToolCall: {"name":"Survey","arguments":{"question":"Which root?","options":["fixture"]}} -->'),
        _reply(
            '<!-- CodeBlockStart: {"name":"write_report"} -->\n'
            '```python\n'
            'from pathlib import Path\n'
            'Path("duplicate_files_report.md").write_text("duplicate groups: 1\\nfiles: 2\\n")\n'
            '```\n'
            '<!-- CodeBlockEnd: {"name":"write_report"} -->\n'
            '<!-- ToolCall: {"name":"Exec","arguments":{"name":"write_report"}} -->'
        ),
        _reply('---\ntask_status:\n  completed: true\n  confidence: 0.9\n---\nFound 2 duplicates; report: duplicate_files_report.md'),
    ])
    task = Task(client, allowed_root=str(tmp_path), asker=lambda *_: "fixture")
    result = task.run("Recursively hash duplicates and write a report")

    assert result.status.completed is True
    assert [outcome.tool for item in result.rounds for outcome in item.outcomes] == ["Survey", "Exec"]
    assert (tmp_path / "duplicate_files_report.md").is_file()
    assert "fixture" in str(client.calls[1][-1].content)
```

Define `_reply` locally in this test module as `return AssistantMessage(content=content, usage=TokenUsage(), stop_reason="end_turn")`, or reuse the existing same-signature helper if present. The second-request assertion proves the same Task retained Survey feedback context.

- [x] **Step 2: 运行 RED 测试**

Run: `rtk uv run pytest -q tests/test_identity.py tests/test_task.py -k 'complete_goal or mock_replay_keeps_survey'`

Expected: FAIL because the existing protocol says any matching direct tool wins and lacks the complete-goal/Sample prohibition wording.

- [x] **Step 3: 最小化修改 `protocol.md` 的路由段**

```markdown
Use these rules in order. Pure knowledge questions may be answered directly. For an execution goal that lacks information required to continue, call Survey and, after its feedback, continue the same Task. Use one direct built-in tool only when it can complete the entire goal. Use Python code and Exec for recursive traversal, content hashing, aggregation, transformation, cross-file comparison, or organizing many results. When the user asks for an artifact or the complete result is large, write the complete result to an approved file and report only completion, key counts, a concise summary, and its path. Do not claim completion from a shallow or truncated sample.
```

Replace only the opening direct-tool routing paragraphs with this content, then retain the existing ToolCall examples and all following protocol paragraphs byte-for-byte unless a line is needed to remove a contradiction. Do not add tool schemas or a new security mechanism.

- [x] **Step 4: 运行 GREEN、identity 回归与格式检查**

Run: `rtk uv run pytest -q tests/test_identity.py tests/test_task.py tests/test_protocol.py -k 'protocol or survey or exec or identity'`

Expected: PASS; existing protocol fixed-text/order and every builtin schema assertions remain true.

Run: `rtk uv run ruff check tests/test_identity.py tests/test_task.py`

Expected: PASS with no diagnostics.

- [x] **Step 5: Commit**

```bash
rtk git add src/forgeagent/res/prompts/protocol.md tests/test_identity.py tests/test_task.py
rtk git commit -m "docs: guide complete execution workflows"
```

### Task 4: 后置、精确且保密的用户配置迁移

**Files:**
- Modify (external, authorized only after Tasks 1-3 GREEN): `~/.forgeagent/config.yaml`

**Interfaces:**
- Consumes: 原始 config bytes、文件 mode、两个精确完整行。
- Produces: 删除目标两行后的同一文件；除这两行外 bytes 不变，mode 不变，`load_context_config()` 返回两个 `None`。

- [x] **Step 1: 在不读取或回显配置正文的情况下执行前置检查**

```bash
rtk uv run python -c 'from pathlib import Path; import hashlib, stat; p=Path.home()/".forgeagent/config.yaml"; b=p.read_bytes(); lines=b.splitlines(keepends=True); targets=(b"round_feedback_max_tokens: 120", b"tool_result_max_tokens: 40"); matches=tuple([line for line in lines if line.strip()==target] for target in targets); filtered=b"".join(line for line in lines if all(line.strip()!=target for target in targets)); indent=tuple(len(items[0])-len(items[0].lstrip()) if len(items)==1 else -1 for items in matches); print(f"target-counts={tuple(map(len,matches))} indent={indent} mode={stat.S_IMODE(p.stat().st_mode):04o} filtered-sha256={hashlib.sha256(filtered).hexdigest()}"); raise SystemExit(0 if tuple(map(len,matches)) == (1, 1) else 1)'
```

Expected: exit `0`, exactly `target-counts=(1, 1)` plus numeric mode and digest only. Any other count: stop, do not write, and report the conflict without printing config content.

- [x] **Step 2: 使用 `apply_patch` 仅删除两条授权完整行**

```diff
*** Begin Patch
*** Update File: /Users/admin/.forgeagent/config.yaml
@@
-  round_feedback_max_tokens: 120
-  tool_result_max_tokens: 40
*** End Patch
```

如果 Step 1 报告的 indent 不是 `(2, 2)`，根据实际 indent 只调整补丁中两条目标行的前导空格，不读取相邻配置正文。该写入需要使用平台对项目外 `apply_patch` 的授权通道，不能改用 Python、YAML serializer、`sed -i` 或整文件重写。

- [x] **Step 3: 立即验证 bytes/mode/加载结果**

Run: `rtk uv run python -c 'from pathlib import Path; import hashlib, stat; from forgeagent.context import load_context_config; p=Path.home()/".forgeagent/config.yaml"; now=p.read_bytes(); targets=(b"round_feedback_max_tokens: 120", b"tool_result_max_tokens: 40"); config=load_context_config(p); print(f"targets-absent={all(target not in (line.strip() for line in now.splitlines()) for target in targets)} mode={stat.S_IMODE(p.stat().st_mode):04o} sha256={hashlib.sha256(now).hexdigest()} adaptive-defaults={config.round_feedback_max_tokens is None and config.tool_result_max_tokens is None}"); raise SystemExit(0 if all(target not in (line.strip() for line in now.splitlines()) for target in targets) and config.round_feedback_max_tokens is None and config.tool_result_max_tokens is None else 1)'`

Expected: exit `0`，只显示目标缺失布尔值、mode、digest 与 adaptive-defaults；将 mode 和 digest 与 Step 1 的记录核对，确认 mode 不变且 digest 等于 Step 1 的 filtered digest。绝不打印 YAML、secret、endpoint 或 API key。本任务是项目外修改，没有 git commit。

### Task 5: 全量验证、真实模型 smoke、严格规格校验与变更审查

**Files:**
- Review only: `src/forgeagent/context.py`, `src/forgeagent/_cli_http.py`, `src/forgeagent/_cli_repl.py`, `src/forgeagent/cli.py`, `src/forgeagent/res/prompts/protocol.md`, `tests/test_context.py`, `tests/test_cli.py`, `tests/test_identity.py`, `tests/test_task.py`

**Interfaces:**
- Consumes: Tasks 1-4 的已提交代码和已验证用户配置。
- Produces: 无额外产品接口；只确认没有公式漂移、secret 泄漏、非交互 banner、prompt 越界或无关改动。

- [x] **Step 1: 运行指定专项回归**

Run: `rtk uv run pytest -q tests/test_context.py tests/test_cli.py tests/test_identity.py tests/test_task.py tests/test_protocol.py tests/test_http_task_service.py`

Expected: PASS; HTTP schema 测试不出现 feedback-limit 字段，identity 工具 schema/order 测试不变。

- [x] **Step 2: 运行受控真实模型重复文件 smoke**

先用 `rtk mktemp -d` 创建唯一临时目录，再用 `apply_patch` 在其中创建两个内容相同、一个内容不同的小文件。启动真实 TTY session：

Run: `rtk uv run forgeagent --tier trusted --model claude-sonnet-5 --no-identity --no-memory`

向同一 session 输入：

```text
递归扫描 <临时目录绝对路径> 的重复文件，按内容哈希确认；将完整结果写入 <临时目录绝对路径>/duplicate_files_report.txt，只回复重复组数、文件数、摘要和报告路径。请直接执行。
根据刚才的执行结果，确认报告路径和重复组数，不要重新扫描。
quit
```

Expected: 第一轮 execution evidence 包含 `Exec`，不以单层 `FileList` 或截断片段收尾；报告存在且包含一组、两个重复文件；第二轮能引用上一轮报告路径和数量。记录实际安全输出；若 provider/凭证不可用，保留原始安全错误并明确该项未验证，不能用 mock replay 代替。临时 fixture 不加入 git。

- [x] **Step 3: 运行静态、完整与 OpenSpec 严格验证**

Run: `rtk uv run ruff format --check src tests scripts`

Expected: PASS with no formatting changes.

Run: `rtk uv run ruff check src tests scripts`

Expected: PASS with no diagnostics.

Run: `rtk uv run mypy src`

Expected: PASS; 若仓库基线不含 mypy 配置或命令不可用，原样记录输出，不以通过替代。

Run: `rtk uv run pytest -q`

Expected: PASS;容器集成 marker 如按既有策略跳过，保留 pytest 原始 summary。

Run: `rtk openspec validate improve-context-limits-and-execution-guidance --strict`

Expected: PASS.

- [x] **Step 4: 审查相对 base-ref 的范围和敏感信息**

Run: `rtk git diff --check 2c8f528224d79a91b6cbe3476db8b6b979b236a4..HEAD`

Expected: PASS with no whitespace errors.

Run: `rtk git diff --name-only 2c8f528224d79a91b6cbe3476db8b6b979b236a4..HEAD`

Expected: only Task 1-4 listed source/test/script files plus the approved plan/change artifacts; no user config, lockfile, dependency manifest, HTTP schema, or unrelated files.

Run: `rtk git diff 2c8f528224d79a91b6cbe3476db8b6b979b236a4..HEAD -- src/forgeagent/context.py src/forgeagent/_cli_http.py src/forgeagent/_cli_repl.py src/forgeagent/cli.py src/forgeagent/res/prompts/protocol.md`

Expected: one resolver formula, renderer only uses numeric `ResolvedFeedbackLimits`, noninteractive gates remain, and no paths/endpoints/environment values/config text are introduced.

- [x] **Step 5: 仅在验证产物确有修改时提交**

```bash
rtk git status --short
rtk git commit -am "test: verify context limits guidance"
```

Run the commit only if this change legitimately modified a tracked verification artifact; otherwise do not create an empty commit. Never stage or commit `~/.forgeagent/config.yaml`.

## 计划自审

- **Spec coverage:** Task 1 covers shared adaptive/configured/effective resolution, low flags, model capability changes, policy compatibility and validation errors. Task 2 covers interactive startup, `/model`, `/reload`, failure rollback, probe cleanup, and noninteractive silence. Task 3 covers protocol ordering, Survey continuation, complete-goal routing, recursive aggregation/Exec, file delivery, schema/API preservation and mock replay. Task 4 performs the exact authorized 120/40 migration with byte/mode/load checks and no secret output。Task 5 covers真实模型受控重复文件 evidence、context/CLI/identity/Task/HTTP、lint、类型检查、完整测试、严格 OpenSpec 与 diff 隐私审查。
- **Placeholder scan:** No `TODO`, `TBD`, “implement later”, “appropriate error handling”, ellipsis placeholder, or cross-task-only instruction remains.
- **Type consistency:** `ResolvedFeedbackLimits` and `resolve_feedback_limits()` are defined in Task 1; Task 2 consumes the same names and returned validator type; no later task invents a second limit type or formula. Existing public policy properties remain `int`; nullable configured fields are only interpolated after their matching boolean flag is true.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-05-improve-context-limits-and-execution-guidance.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?

