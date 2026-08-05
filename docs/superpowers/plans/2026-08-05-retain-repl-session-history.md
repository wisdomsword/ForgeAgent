---
change: retain-repl-session-history
design-doc: docs/superpowers/specs/2026-08-05-retain-repl-session-history-design.md
base-ref: 2c8f528224d79a91b6cbe3476db8b6b979b236a4
---

# REPL 会话历史保留实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在同一 REPL 进程内让任务型输入继承安全、有界的模型 transcript，同时每条顶层输入继续使用全新的 Task 安全状态。

**Architecture:** `Task.run()` 每次重新生成 system prompt，并将调用方提供的非 system 历史、副本化后与当前 user 输入拼成请求会话；`Step` 保存其唯一事实源 conversation 的快照，`TaskOutcome` 以非公开字段回传。`_cli_repl.repl()` 仅保存该内部 transcript：Single 直接替换，Duo/Triad 只追加确定性的公开投影；context policy 继续构造 provider request view，按完整 assistant/user 单元裁剪而不修改真实 transcript。

**Tech Stack:** Python 3.11、Pydantic 2、pytest 8、Rich、现有 `Message`/`Role` 模型与 `SlidingWindowContextPolicy`；不新增依赖。

## Global Constraints

- 基线提交必须为 `2c8f528224d79a91b6cbe3476db8b6b979b236a4`；实现前确认工作树的目标变更未混入无关修改。
- 不新增依赖、模块注册层、持久化格式、跨进程会话或第二个摘要/压缩器。
- 每条 REPL 顶层任务输入都必须创建新的 `Task`、backend、`Runtime`、task ID、确认状态和文件系统授权；历史只能作为模型文本上下文。
- 每轮必须重新生成当前 system prompt；历史不得含 `system` role，且不得携带旧 Runtime Authority、授权、receipt、工具注册表或宿主状态。
- 历史图片以结构化 `ImageItem` 保留到 `/new` 或 `/reset`；模型不支持图片时沿用既有能力错误，不静默删除图片。
- `TaskOutcome.session_messages` 必须 `exclude=True`、`repr=False`，不得进入 `model_dump()`、HTTP 投影、审计或日志公开面。
- context policy 只保留当前 system prompt、首个 user 锚点和预算内最新完整 assistant/user 单元；不得拆分工具调用及其 feedback，不得原地修改真实 conversation。
- 管理命令不得写入 transcript；`/new` 与 `/reset` 清空 transcript 与暂存图片，但保留模型、tier、Memory、MCP、输入行历史及 `usage_total`。
- Duo/Triad 只保存原始 goal 加确定性的公开 assistant 投影，投影只含 mode、status、stop reason、phase、counters、有界 evidence 和 execution-evidence 摘要；不得包含候选文件正文、evaluator 评语、内部 plan、receipt 或审计事件。
- 所有验证命令以 `rtk` 开头；通过前不得宣称完成。

## 文件结构

- 修改 `src/forgeagent/step.py`：将一次运行的真实 conversation 保存为只读复制快照，并保证所有正常终态都能取得它。
- 修改 `src/forgeagent/task.py`：定义内部 transcript 字段、扩展 `Task.run()` 的历史输入、在身份回答修复后同步 transcript，并创建终态 assistant 投影。
- 修改 `src/forgeagent/context.py`：增加不含 system 的 REPL session transcript 配对校验，并保留 provider request view 的完整 assistant/user 单元裁剪。
- 修改 `src/forgeagent/cli.py`：为 `run_once()` 增加并透传 `session_messages`，保持单次 CLI 省略该参数时的现有契约。
- 修改 `src/forgeagent/_cli_repl.py`：持有进程内 transcript，收敛 Single 调用，接入协作 prior context/公开投影，以及 `/new`、`/reset`。
- 修改 `src/forgeagent/_cli_collaboration.py`：为 `run_collaboration_once()` 与各角色 `Task.run()` 透传外层 prior transcript。
- 修改 `tests/test_step.py`、`tests/test_task.py`、`tests/test_context.py`、`tests/test_cli.py`、`tests/test_collaboration_integrations.py`、`tests/test_http_server.py`：锁定内部 transcript、配对裁剪、REPL 连续性、重置、授权隔离与公开序列化契约。

---

### Task 1: 建立 Task、Step 与 context 的 transcript 契约

**Files:**
- Modify: `src/forgeagent/step.py:281-512`
- Modify: `src/forgeagent/task.py:96-151, 338-430`
- Modify: `src/forgeagent/context.py:104-149`
- Test: `tests/test_step.py`
- Test: `tests/test_task.py`
- Test: `tests/test_context.py`
- Test: `tests/test_http_server.py`

**Interfaces:**
- Consumes: `Message(role: Role, content: str | list[TextItem | ImageItem])`, `Role`, `Step.run(messages: list[Message]) -> list[RoundResult]`。
- Produces: `Step.session_messages` 的复制快照；`Task.run(goal: str, *, images: list[ImageItem] | None = None, session_messages: Sequence[Message] | None = None, cancel_event: threading.Event | None = None) -> TaskOutcome`；`TaskOutcome.session_messages: list[Message] = Field(default_factory=list, exclude=True, repr=False)`。
- Produces: `validate_session_messages(messages: Sequence[Message]) -> list[Message]`，接受空历史或 `(USER, ASSISTANT)+` 且返回副本；非法 role、system role 或未以 assistant 结束时抛有界 `ContextBudgetExceeded`。
- Produces: provider request context 的合法结构仍为 `[SYSTEM, first USER, (ASSISTANT, USER)*]`，其中最后的 USER 可为下一顶层输入；超预算仍抛 `ContextBudgetExceeded`。

- [x] **Step 1: 写入会先失败的 Step/Task/context/HTTP 测试**

在 `tests/test_task.py` 增加用脚本化 client 捕获 provider 请求的测试，断言带 `session_messages=history` 的新 `Task.run()` 发出精确序列：新 system、调用方 history 的等值副本、当前 user（带图片时为 `[TextItem(goal), *images]`）；并断言调用方 `history` 未被修改、history 中 `Role.SYSTEM` 在 provider 前以既有公开失败语义被拒绝。

在 `tests/test_step.py` 增加取消、`ContextBudgetExceeded`、`ClientError`、prose 完成和 max-rounds 的参数化或独立测试：每个终态均可读取不含 system 的 `step.session_messages` 复制值；成功 reply 后 assistant 用 `_render_history_content(reply)` 追加，工具/解析活动后 user feedback 用既有 `_render_feedback()` 的有界结果追加。

在 `tests/test_task.py` 增加：身份修复后 `outcome.rounds[-1].body` 与 `outcome.session_messages[-1].content` 都是 ForgeAgent 身份答案；没有成功 assistant reply 的失败 Task 以一条有界、宿主生成的 assistant 终态投影结束，且该投影不声称任务完成。再新增已构造 `TaskOutcome` 的 `model_dump()` 不含 `session_messages` 的断言，并在 `tests/test_http_server.py` 对现有任务 HTTP 结果断言同样不含该键。

在 `tests/test_context.py` 增加：新的 `validate_session_messages()` 接受空列表与 `USER, ASSISTANT, USER, ASSISTANT` 并返回独立 list；拒绝 system role、assistant 开头、连续同 role 和未以 assistant 结束。另增加 provider request view 回归：`SYSTEM, USER(anchor), ASSISTANT, USER(next_top_level)` 合法；更长跨输入序列超预算时删除最旧完整 pair、保留 system/anchor/最新 pair；工具调用 assistant 与 feedback 仍整体保留或整体删除。后一组是已有算法的回归证明，不作为 RED 来源。

```python
def test_task_reuses_safe_history_with_fresh_system_prompt() -> None:
    history = [
        Message(role=Role.USER, content="draft the report"),
        Message(role=Role.ASSISTANT, content="Where should I save it?"),
    ]
    client = MockClient(script=[_reply(_done())])
    outcome = Task(client, tier="trusted").run(
        "save it under /tmp/report.md", session_messages=history
    )
    assert client.requests[0][0].role is Role.SYSTEM
    assert client.requests[0][1:] == [
        *history,
        Message(role=Role.USER, content="save it under /tmp/report.md"),
    ]
    assert outcome.model_dump().get("session_messages") is None

def test_context_accepts_next_top_level_user_as_complete_pair() -> None:
    assert policy.request_view(messages) == messages

def test_session_history_requires_complete_user_assistant_turns() -> None:
    history = [
        Message(role=Role.USER, content="goal"),
        Message(role=Role.ASSISTANT, content="question"),
    ]
    copied = validate_session_messages(history)
    assert copied is not history
```

- [x] **Step 2: 运行专项测试确认失败**

Run: `rtk uv run pytest tests/test_step.py tests/test_task.py tests/test_context.py tests/test_http_server.py -q`

Expected: FAIL during collection or execution，显示 `validate_session_messages` 不可导入、`Task.run()` 不接受 `session_messages`、`TaskOutcome` 缺少 `session_messages`，或 `Step` 没有 snapshot。现有 request-view 交替回归可以已经通过。

- [x] **Step 3: 实现最小 transcript 传递与配对规则**

在 `Step.__init__` 初始化 `self._session_messages: list[Message] = []`，并添加返回 `list(self._session_messages)` 的只读复制属性。将 `_run_rounds()` 的局部 `convo` 提升为该状态的副本：进入时复制传入 messages，退出前将其去除首条 system 后复制到 `_session_messages`。保持现有 assistant 和 feedback 追加位置为唯一事实源；对于 client error、取消、context 失败等未追加 assistant 的终态，`Task.run()` 而不是 Step 根据 snapshot 在末尾补一条有界 assistant 终态投影，以使下次顶层 user 满足交替结构。

在 `context.py` 实现 `validate_session_messages()`，逐对校验 `(USER, ASSISTANT)` 并返回副本。扩展 `Task.run()`：通过该函数校验并复制 `session_messages`，构造 `messages = [new_system, *prior, current_user]`，将其交给 Step；从 `step.session_messages` 创建 `TaskOutcome.session_messages`。把 `_repair_identity_answer()` 改为同时接收 transcript 或返回修正后的 answer，使 identity 修复同步替换末条 assistant 的字符串内容。终态投影使用受控文本，例如 `"Task ended with status: <bounded_reason>."`，并且只有 transcript 末项不是 assistant 时才追加。

更新 `_validated_prefix_and_rounds()` 的命名、注释与错误 detail，使其明确描述跨 Task 的 assistant/user interaction units；首两项仍固定为 `SYSTEM, USER`，其后每两项仍必须是 `ASSISTANT, USER`。不重写已经正确的 budget、估算和完整 pair 裁剪算法。

```python
class TaskOutcome(BaseModel):
    status: TaskStatus
    rounds: list[RoundResult]
    memory_results: list[MemoryResult] = Field(default_factory=list)
    execution_evidence: ExecutionEvidence = Field(default_factory=ExecutionEvidence)
    session_messages: list[Message] = Field(default_factory=list, exclude=True, repr=False)

def run(self, goal: str, *, images=None, session_messages=None, cancel_event=None) -> TaskOutcome:
    prior = list(session_messages or ())
    messages = [Message(role=Role.SYSTEM, content=self._build_system_prompt()), *prior, current_user]
    rounds = step.run(messages)
    transcript = step.session_messages
    # context policy 在首次 provider 调用前拒绝非法 prior role；随后同步 identity 修复和终态投影。
```

- [x] **Step 4: 运行专项测试确认通过**

Run: `rtk uv run pytest tests/test_step.py tests/test_task.py tests/test_context.py tests/test_http_server.py -q`

Expected: PASS；provider 只看到新 system + 合法 history + 当前 user，公开序列化不出现 transcript，window 只裁剪完整 assistant/user 单元。

- [x] **Step 5: 提交 Task 1**

```bash
rtk git add src/forgeagent/step.py src/forgeagent/task.py src/forgeagent/context.py tests/test_step.py tests/test_task.py tests/test_context.py tests/test_http_server.py
rtk git commit -m "feat: retain safe task session transcript"
```

### Task 2: 将 Single REPL 路由接入进程内会话

**Files:**
- Modify: `src/forgeagent/cli.py:440-523`
- Modify: `src/forgeagent/_cli_repl.py:420-700`
- Test: `tests/test_cli.py:3399-3535, 5393-`
- Test: `tests/test_collaboration_integrations.py:108-190, 737-`

**Interfaces:**
- Consumes: `run_once()` 的新增 `session_messages: Sequence[Message] | None = None` 关键字参数与 `TaskOutcome.session_messages`。
- Produces: `_cli_repl.repl()` 局部 `session_messages: list[Message]`；嵌套 `run_single(goal: str, *, images: list[ImageItem] | None = None) -> TaskOutcome`，唯一负责传入 history snapshot 并在成功返回后替换本地 transcript。
- Produces: 普通 single、`/single <goal>` 与 `/image <paths> <inline goal>` 都调用 `run_single`；抛异常时保留旧 transcript。

- [x] **Step 1: 写入会先失败的 Single 连续性与管理隔离测试**

在 `tests/test_cli.py` 使用每 Task 新建的 `MockClient`，第一条输入返回 prose 澄清问题，第二条输入为路径；断言第二个 client 的首个 provider request 含第一条 user、第一条 assistant 问题和第二条 user，且只有一个新的 system。增加普通输入、`/single`、inline `/image` 三种路由均把前一 Task 的 `TaskOutcome.session_messages` 作为下一次 `run_once()` 的 `session_messages`。

增加 `/help`、`/model`、`/reload`、`/memory`、`/mcp`、未知 slash command 与无 goal 的协作命令之间插入后，下一 provider request 不含命令文本或控制台输出。增加 run_once 抛异常时，下一正常输入仅继承最后一次成功 Task 的 transcript。

```python
def test_repl_follow_up_keeps_goal_question_and_answer() -> None:
    clients_seen: list[MockClient] = []
    scripts = iter([
        MockClient(script=[_reply("Which output path should I use?")]),
        MockClient(script=[_reply(_done())]),
    ])

    def client_factory(_model: str) -> MockClient:
        client = next(scripts)
        clients_seen.append(client)
        return client

    repl_inputs = iter(["write a report", "/tmp/report.md", ""])
    repl(
        tier="trusted", model="mock", client_factory=client_factory, console=_console(),
        read_line=lambda _prompt: next(repl_inputs), confirmation_available=False,
        no_identity=True, no_memory=True, use_registry_snapshot=False,
    )
    second_request = clients_seen[1].requests[0]
    assert [message.role for message in second_request] == [Role.SYSTEM, Role.USER, Role.ASSISTANT, Role.USER]
    assert second_request[-1].content == "/tmp/report.md"
```

- [x] **Step 2: 运行 REPL 路由测试确认失败**

Run: `rtk uv run pytest tests/test_cli.py tests/test_collaboration_integrations.py -q`

Expected: FAIL；第二次请求仍为 `[SYSTEM, USER]`，或 `run_once()` 不接受 `session_messages`。

- [x] **Step 3: 实现 Single helper 与历史替换**

在 `cli.run_once()` 增加可选 `session_messages: Sequence[Message] | None = None`，并仅将其原样交给 `task.run()`；无该参数的 CLI `run`、Loop、HTTP caller 行为不变。

在 `_cli_repl.repl()` 于 `usage_total`、`staged_images` 同级创建 `session_messages: list[Message] = []`。添加小型嵌套 helper，先用 `list(session_messages)` 调用 `bindings.run_once()` 的新增 `session_messages` 关键字参数，仅在其返回 `TaskOutcome` 后执行 `session_messages[:] = outcome.session_messages`。将 inline image、显式 `/single`、普通 single 三处重复的 `bindings.run_once()` 全部替换为此 helper；普通 single 使用 `staged_images` 的既有值，保持当前 staged-image 消费时机。

```python
session_messages: list[Message] = []

def run_single(goal: str, *, images: list[ImageItem] | None = None) -> TaskOutcome:
    outcome = bindings.run_once(
        goal,
        tier=tier,
        model=model,
        client_factory=task_client_factory,
        console=console,
        asker=asker,
        mcp=mcp,
        confirmer=confirmer,
        identity=identity,
        container_image=container_image,
        usage_total=usage_total,
        images=images,
        stream=stream,
        context_config=current_context,
        memory_manager=memory_manager,
        skills=current_skills,
        audit_sink=audit_sink,
        session_messages=list(session_messages),
    )
    session_messages[:] = outcome.session_messages
    return outcome
```

- [x] **Step 4: 运行 REPL 路由测试确认通过**

Run: `rtk uv run pytest tests/test_cli.py tests/test_collaboration_integrations.py -q`

Expected: PASS；任务型 Single 输入的 provider 消息数量递增，管理命令和异常均不污染或覆盖已完成 transcript。

- [x] **Step 5: 提交 Task 2**

```bash
rtk git add src/forgeagent/cli.py src/forgeagent/_cli_repl.py tests/test_cli.py tests/test_collaboration_integrations.py
rtk git commit -m "feat: retain repl history for single tasks"
```

### Task 3: 接入 Duo/Triad prior context 与安全公开投影

**Files:**
- Modify: `src/forgeagent/_cli_repl.py:420-700`
- Modify: `src/forgeagent/cli.py:526-582`
- Modify: `src/forgeagent/_cli_collaboration.py:89-236`
- Test: `tests/test_collaboration_integrations.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_collaboration_once()` 的新增 `session_messages: Sequence[Message] | None = None` 关键字参数，以及 `CollaborationReport` 的公开 `mode`、`status`、`stop_reason`、`phase`、counters、evidence 与 execution evidence。
- Produces: 协作角色 `task.run(task_goal: str, *, session_messages: Sequence[Message] | None = None, cancel_event=None)`，各角色收到同一外层 transcript 的独立副本。
- Produces: `_project_collaboration_report(goal: str, report: CollaborationReport) -> list[Message]`，恰好返回 `[USER(goal), ASSISTANT(public_projection)]`；输出确定性且被现有 feedback/evidence 上限约束。

- [x] **Step 1: 写入会先失败的协作可见性测试**

在 `tests/test_collaboration_integrations.py` 增加 fake role task，记录每个角色的 `session_messages`，断言 Duo/Triad 的 planner（仅 Triad）、generator、evaluator 都接到等值但不同 list 对象的 outer transcript，且仍是各自新建的 Task/role system prompt。

增加 REPL 两次协作输入测试：第一次 `/duo <goal>` 或 `/triad <goal>` 后，第二次任务的 provider history 包含单条原始协作 goal 与单条公开 assistant 投影。断言投影包含 mode、status、stop reason、phase、round/counter、有限 evidence/execution evidence 摘要；不包含 fake planner transcript、evaluator critique、candidate file body、receipt 或 audit event。

```python
def test_repl_collaboration_stores_only_public_projection(monkeypatch) -> None:
    report = _report_with_private_details(
        planner_text="private plan", evaluator_text="private critique", candidate="SECRET SOURCE"
    )
    collaboration_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        repl_bindings,
        "run_collaboration_once",
        lambda *args, **kwargs: collaboration_calls.append(kwargs) or report,
    )
    repl(
        tier="trusted", model="mock", client_factory=_factory([_reply(_done())]),
        console=_console(), read_line=iter_reader(["/duo build it", "follow up", ""]),
        confirmation_available=False, no_identity=True, no_memory=True, use_registry_snapshot=False,
    )
    history = collaboration_calls[0]["session_messages"]
    assert history[0] == Message(role=Role.USER, content="build it")
    assert history[1].role is Role.ASSISTANT
    assert "private plan" not in str(history[1].content)
    assert "SECRET SOURCE" not in str(history[1].content)
```

- [x] **Step 2: 运行协作测试确认失败**

Run: `rtk uv run pytest tests/test_collaboration_integrations.py tests/test_cli.py -q`

Expected: FAIL；协作入口不接受 `session_messages`，各角色未收到 prior context，或 REPL 没有生成公开投影。

- [x] **Step 3: 实现 prior context 透传和确定性投影**

在 `cli.run_collaboration_once()` 和 `_cli_collaboration.run_collaboration_once()` 增加可选 `session_messages` 参数。在 `_cli_collaboration` 的 `OwnedRoleTask.run()` 中，以 `list(session_messages or ())` 调用每个 role Task；不得将某一 role 返回的 transcript 传给另一 role。

在 `_cli_repl.repl()` 添加 `run_collaboration(goal, decision) -> CollaborationReport` helper：把当前 transcript 副本传给 bindings，返回后以 `_project_collaboration_report()` 的两条消息 append 到 session。投影仅从报告公开模型字段取值，采用稳定的键序和既有 `render_execution_evidence`/feedback 的 token 限额；不得通过 `model_dump()` 泛化导出完整 report。所有协作模式结束状态都追加投影；协作入口抛异常时不改变 transcript。

```python
def _project_collaboration_report(goal: str, report: CollaborationReport) -> list[Message]:
    evidence = _bounded_public_evidence(report)
    content = (
        f"mode={report.mode}\nstatus={report.status}\nstop_reason={report.stop_reason}\n"
        f"phase={report.phase}\nrounds={report.rounds}\n{evidence}"
    )
    return [
        Message(role=Role.USER, content=goal),
        Message(role=Role.ASSISTANT, content=content),
    ]
```

- [x] **Step 4: 运行协作测试确认通过**

Run: `rtk uv run pytest tests/test_collaboration_integrations.py tests/test_cli.py -q`

Expected: PASS；每个协作角色接收独立外层 history，外层会话只含公开、确定性且有界的协作结果。

- [x] **Step 5: 提交 Task 3**

```bash
rtk git add src/forgeagent/_cli_repl.py src/forgeagent/cli.py src/forgeagent/_cli_collaboration.py tests/test_collaboration_integrations.py tests/test_cli.py
rtk git commit -m "feat: project collaboration results into repl history"
```

### Task 4: 添加会话重置命令并验证授权不跨 Task

**Files:**
- Modify: `src/forgeagent/_cli_repl.py:420-700`
- Modify: `src/forgeagent/cli.py`（仅当命令菜单/帮助绑定需要公开 `/new` 与 `/reset` 时）
- Test: `tests/test_cli.py:3488-3535, 5017-5393`
- Test: `tests/test_task.py:574-724`
- Test: `tests/test_collaboration_integrations.py`

**Interfaces:**
- Consumes: `_cli_repl.repl()` 的 `session_messages`、`staged_images`、`usage_total`、当前 model/tier/Memory/MCP。
- Produces: `/new` 与 `/reset` 同义命令：不创建 `Task`、不调用 provider，执行 `session_messages.clear()` 与 `staged_images = None`，并输出固定有界确认。
- Produces: 新 Task 在历史含 `RequestFilesystemAccess` 批准文本或成功 feedback 时仍以 project scope 开始，并由当前 Task 自己的 confirmer 决定授权。

- [x] **Step 1: 写入会先失败的 reset 和权限隔离测试**

在 `tests/test_cli.py` 增加参数化 `/new`、`/reset`：先产生带图片的历史，执行命令，再输入新 goal；断言 client factory/provider 调用数不因 reset 增加，下一请求只有新 system + 新 user，不含旧图片或历史；断言输出为一条有界确认。断言当前 model、tier、memory manager、mcp 对象与累计 usage 的第二个任务总量没有被 reset 改变。

扩展现有 `test_repl_filesystem_access_decision_resets_between_goals` 或在 `tests/test_task.py` 新增继承 transcript 的回归：第一个 restricted Task 接受 `RequestFilesystemAccess`，第二个 Task 的 history 仍包含批准文本/工具 feedback，但再次请求项目外路径时仍会触发当前 Task confirmer；拒绝后 backend 与 file tools 保持 project scoped。

```python
@pytest.mark.parametrize("command", ["/new", "/reset"])
def test_repl_reset_does_not_call_provider_and_discards_history(command: str) -> None:
    inputs = iter(["first goal", command, "second goal", ""])
    repl(
        tier="trusted", model="mock", client_factory=client_factory, console=console,
        read_line=lambda _prompt: next(inputs), confirmation_available=False,
        no_identity=True, no_memory=True, use_registry_snapshot=False,
    )
    assert len(clients_seen) == 2
    assert [message.role for message in clients_seen[1].requests[0]] == [Role.SYSTEM, Role.USER]
    assert "session reset" in console.export_text().lower()
```

- [x] **Step 2: 运行 reset 与授权回归确认失败**

Run: `rtk uv run pytest tests/test_cli.py tests/test_task.py tests/test_collaboration_integrations.py -q`

Expected: FAIL；`/new`、`/reset` 落入未知命令分支，或第二 Task 错误地继承了历史/图片/文件系统授权。

- [x] **Step 3: 实现同义 reset 命令并保持 task-scoped 授权**

在 `_cli_repl.repl()` 的 slash command 分发中、任何模型/协作路由之前，处理 `goal in {"/new", "/reset"}`：`session_messages.clear()`，`staged_images = None`，`console.print("[green]session reset[/green]")`，然后 `continue`。将 `/new` 与 `/reset` 加入现有命令表或帮助文本的同一条目，确保它们显示为同义操作且没有新命令解析层。

不要为授权增加任何继承实现：Task 继续在构造时新建 backend、Runtime、receipt store 和 ToolContext；history 仅流向 `Task.run()` 的新增 `session_messages` provider 消息。保留现有 per-Task `RequestFilesystemAccess` confirmer/decision 状态。

- [x] **Step 4: 运行全部质量门禁与受控 smoke**

Run: `rtk uv run ruff check src tests`

Expected: PASS。

Run: `rtk uv run ruff format --check src tests`

Expected: PASS。

Run: `rtk uv run pytest tests/test_step.py tests/test_task.py tests/test_context.py tests/test_cli.py tests/test_collaboration_integrations.py tests/test_http_server.py tests/test_http_task_service.py -q`

Expected: PASS。

Run: `rtk uv run pytest -q`

Expected: PASS（container integration marker 按现有 pytest 默认策略处理）。

Run: `rtk openspec validate retain-repl-session-history --strict`

Expected: PASS，OpenSpec delta specs 严格有效。

Run: `rtk git diff --check 2c8f528224d79a91b6cbe3476db8b6b979b236a4`

Expected: PASS，无空白错误。

受控 smoke：以注入式 `MockClient` 驱动两条 REPL 输入，第一条返回澄清问题、第二条回答；断言第二个 provider request 是 `[SYSTEM, USER(original), ASSISTANT(question), USER(answer)]`，并单独运行 `/reset` 后断言下一请求回到 `[SYSTEM, USER]`。

- [x] **Step 5: 审查变更并提交 Task 4**

审查 `rtk git diff 2c8f528224d79a91b6cbe3476db8b6b979b236a4 -- src/forgeagent tests`：确认没有持久化、没有新增依赖、没有旧 system prompt 或私有协作内容进入 transcript，且非任务命令和异常没有更新会话。

```bash
rtk git add src/forgeagent/_cli_repl.py src/forgeagent/cli.py tests/test_cli.py tests/test_task.py tests/test_collaboration_integrations.py
rtk git commit -m "feat: add repl session reset commands"
```

## 自审结果

- Spec coverage：Task 1 覆盖 fresh system、历史复制、Step snapshot、终态投影、身份修复、序列化排除和跨输入 window；Task 2 覆盖普通/Single/inline image 与管理命令隔离；Task 3 覆盖 Duo/Triad prior context 和安全公开投影；Task 4 覆盖 `/new`、`/reset`、图片/usage 保留语义及历史授权不得恢复权限。单次 CLI、Loop、HTTP 的兼容性由 Task 1/2 的公开序列化和 Task 4 的专项/完整回归锁定。
- Placeholder scan：已逐项检查；所有测试、接口、命令、预期结果和提交内容均已明确，未遗留待定项或泛化错误处理占位。
- Type consistency：所有调用方使用 `session_messages: Sequence[Message] | None` 输入与 `TaskOutcome.session_messages: list[Message]` 输出；`Step.session_messages` 仅提供复制快照；协作入口返回既有 `CollaborationReport`，公开投影只由 REPL 生成。

## 执行交接

计划已保存至 `docs/superpowers/plans/2026-08-05-retain-repl-session-history.md`。执行时可选择：

1. Subagent-Driven（推荐）：每个任务使用新的 subagent，并在任务间审查。
2. Inline Execution：在当前会话按任务执行，并在每个检查点复核。
