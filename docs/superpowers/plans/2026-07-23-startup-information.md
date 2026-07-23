---
change: startup-information
design-doc: docs/superpowers/specs/2026-07-23-startup-information-design.md
base-ref: 7e17ad540de9907fdd795c0791e7e03b485e5028
---

# Startup Information Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在真实交互式 REPL 中提供可清理的 ForgeAgent 启动标识和真实能力摘要，同时让 MCP 启动诊断脱敏、可解释，并让非 TTY 路径保持零启动噪声。

**Architecture:** `mcp_manager.py` 负责每个 server generation 的受限 stderr 捕获、固定类别分类和不可变诊断投影；它不渲染 UI，且维持现有 `server_status()`、`required_failures()` 与工具路由语义。`cli.py` 保持为唯一展示层：以私有 `_StartupDisplay` 编排初始化期 Live、确认 pause/resume、成功摘要和 `/mcp` 详情；`main()` 将启动失败输出严格导向 stderr。测试以 manager 单元测试锁定资源/竞态/泄漏，以 CLI 单元测试锁定显示边界，并以真实子进程覆盖 non-TTY 两路字节契约。

**Tech Stack:** Python 3.11+, Rich `Console`/`Live`, `asyncio`, `threading`, `os.pipe`, pytest, Ruff, OpenSpec, uv/hatchling。

## Global Constraints

- 不新增依赖、CLI 开关、配置项、持久日志、HTTP 启动输出、`/doctor` 或跨模块 UI 框架。
- `MCPManager.server_status() -> dict[str, str]`、`required_failures() -> dict[str, str]`、`enable()`、`disable()`、工具路由和 `run`/`serve` 的既有语义必须兼容。
- child stderr 必须按 server generation 隔离；内存仅保留前 `8192` bytes，持续排空后续内容，最终不保留原文。
- 公共启动输出、`/mcp`、结构化反馈和 lifecycle log 不得包含 child stderr、命令、参数、环境、server 内容、异常类型、`ExceptionGroup` 或 secret。
- 仅默认 reader 且 `console.is_terminal and sys.stdin.isatty()` 时可以使用交互启动 UI 或增强输入；显式 `read_line`、非 TTY、`TERM=dumb`、CI、`run`、`serve`、`models`、`smoke` 不得出现 Logo/动画；`NO_COLOR` 或无色终端的真实交互 REPL 显示静态单色标识。
- 只使用 ASCII 源码 Logo；完整 Logo 使用七色、8 FPS；窄终端使用单行 `ForgeAgent`；无色环境只显示静态单色文本。
- enabled server 才计入摘要分母；required 失败必须在任何 Ready 摘要前 abort；optional 失败只能输出一条固定降级说明。
- 保留既有 dirty 路径：`ACTION_PLAN.md`、`scripts/m16-filewrite-allowlist-blackbox.sh`、`.agent/`、`.agents/`、`.claude/`、`.codex/`、`.superpowers/brainstorm/`、`skills-lock.json`、`work/`、`何为Harness.html` 不进入本 change。

## File Structure

| 路径 | 责任 |
| --- | --- |
| `src/forgeagent/mcp_manager.py` | generation-owned pipe stderr capture、固定诊断类别、`MCPServerDiagnostic` facade 投影与生命周期释放。 |
| `src/forgeagent/cli.py` | 真实 TTY 判定、私有启动 renderer、无 prompt 的非 TTY reader、摘要/错误输出、`/mcp` 展示。 |
| `tests/test_mcp_manager.py` | capture 上限、读端排空、分类/掩码、generation 竞争、close/cancel 无泄漏。 |
| `tests/test_cli.py` | renderer 生命周期、TTY/no-color/narrow 降级、确认 pause/resume、摘要与 slash 命令、stdout/stderr 分离。 |
| `tests/test_cli_startup_blackbox.py` | 安装入口的 pipe quit、pipe goal、optional/required MCP 子进程输出契约。 |
| `tests/mcp_fixture_server.py` | 增加仅测试使用的 stderr chatter / Docker-like failure modes，供真实 stdio 子进程断言。 |
| `README.md`、`docs/m7-tools-mcp-survey.md` | 记录交互/非交互输出边界、`/mcp` 固定诊断和 MCP/Docker 信任边界。 |
| `docs/superpowers/reports/2026-07-23-startup-information-verify.md` | 记录定向、全量、golden、OpenSpec、构建、TTY smoke 和 dirty-path 审计结果。 |

---

### Task 1: Add Generation-Bounded MCP Stderr Capture and Diagnostics

**Files:**
- Modify: `src/forgeagent/mcp_manager.py:1-170,473-679,750-924,1070-1450`
- Modify: `tests/test_mcp_manager.py`

**Interfaces:**
- Consumes: existing `MCPServerConfig`, `_ServerState`, `_holder_slot_matches(name, generation, task=None, stop=None)`, `mask_secrets()` and public-label mapping.
- Produces: `MCPServerDiagnostic(name: str, enabled: bool, required: bool, status: str, tool_count: int, reason: str | None, impact: str | None, action: str | None)`; `MCPManager.diagnostics() -> tuple[MCPServerDiagnostic, ...]`; private `MCPManager._publish_unavailable(name: str, generation: int, capture: _BoundedStderrCapture) -> None`; `MCPManager._holder()` calls `stdio_client(params, errlog=capture.stream)`.

- [x] **Step 1: Write failing capture and projection tests**

Add focused tests that monkeypatch the imported `mcp.client.stdio.stdio_client` and exercise a real `_BoundedStderrCapture` reader without a real provider. Cover independent capture objects for two generations, valid UTF-8, `b"\\xff"` replacement decoding, exactly 8192 retained bytes, `truncated is True` after 8193 bytes, and a writer completing a payload larger than a pipe buffer while `text()` remains bounded.

```python
def _manager_with_secret(monkeypatch, secret: str) -> MCPManager:
    monkeypatch.setattr(mcp_manager, "sensitive_env_values", lambda: {secret})
    return MCPManager({"github": MCPServerConfig(command="fixture", required=False)})


def _fail_generation(manager: MCPManager, name: str, stderr: bytes) -> None:
    state = manager._states[name]
    capture = _BoundedStderrCapture()
    with capture:
        capture.stream.buffer.write(stderr)
        capture.stream.flush()
    manager._publish_unavailable(name, generation=1, capture=capture)


def test_bounded_stderr_capture_keeps_only_first_8192_bytes_and_drains():
    capture = _BoundedStderrCapture()
    with capture:
        capture.stream.write("x" * 8193)
        capture.stream.flush()
    assert capture.text() == "x" * 8192
    assert capture.truncated is True


def test_diagnostics_never_publish_raw_stderr_or_secret(monkeypatch):
    manager = _manager_with_secret(monkeypatch, "top-secret")
    _fail_generation(manager, "github", b"docker.sock top-secret /private/path")
    diagnostic = manager.diagnostics()[0]
    assert diagnostic.reason == "Docker is not running"
    assert "top-secret" not in repr(diagnostic)
    assert "/private/path" not in repr(diagnostic)
```

Add generation tests that fail generation N, enable generation N+1, then complete N's holder/finalizer; assert N+1's status, `diagnostic_code`, tools and diagnostic tuple are unchanged. Add success-path and close-path tests asserting the capture buffer is cleared, reader is joined, and no non-daemon reader thread survives.

- [x] **Step 2: Run the new tests to verify RED**

Run: `uv run pytest tests/test_mcp_manager.py -q -k "bounded_stderr_capture or diagnostics or generation"`

Expected: collection/import failure for `_BoundedStderrCapture` and `MCPManager.diagnostics`, or assertion failures because `stdio_client` receives no `errlog` and raw exception types still determine public status.

- [x] **Step 3: Implement the minimal capture and fixed projection contract**

At module scope, add a private capture with a binary pipe reader. `__enter__()` starts one daemon thread; `close()` closes only the parent write stream first, joins the reader, closes the read descriptor, and is idempotent. The reader must always consume chunks after the cap, only extending the locked bytearray by the remaining capacity.

```python
_STDERR_CAPTURE_LIMIT = 8192


class _BoundedStderrCapture:
    def __init__(self, limit: int = _STDERR_CAPTURE_LIMIT) -> None:
        self._limit = limit
        self._data = bytearray()
        self._lock = threading.Lock()
        self._read_fd: int | None = None
        self.stream: TextIO | None = None
        self._reader: threading.Thread | None = None
        self.truncated = False

    def text(self) -> str:
        with self._lock:
            return bytes(self._data).decode("utf-8", errors="replace")

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.truncated = False
```

Create the `@dataclass(frozen=True) MCPServerDiagnostic` exactly as declared above. Extend `_ServerState` only with `diagnostic_code: str | None = None`; do not store display prose there. Add a private mapping from `docker_unavailable`, `timeout`, `startup_failed`, and `stderr_truncated` to fixed `(reason, impact, action)` tuples. `_classify_startup_failure(masked_stderr: str) -> str` matches only deterministic Docker daemon/socket and connection-timeout patterns; every other failure returns `startup_failed`.

In `_holder`, construct the capture before `stdio_client`, pass `errlog=capture.stream`, and in its exception branch call `_publish_unavailable(name, generation, capture)` only when `_holder_slot_matches(name, generation, stop=stop) and not self._closing`. That method clears tools, sets status to the existing compatible `"unavailable: <fixed_code>"`, and sets `diagnostic_code`. Never interpolate `exc`, its type, or raw capture text into state. On successful publication and in `finally`, clear and close the capture after the reader has observed EOF. Reset `diagnostic_code` before every enabled replacement generation. Implement `diagnostics()` on the facade thread: iterate deterministic state order, mask labels, compute `tool_count`, map only the fixed code, and return a tuple.

- [x] **Step 4: Run focused RED-to-GREEN tests and lifecycle regression**

Run: `uv run pytest tests/test_mcp_manager.py -q -k "bounded_stderr_capture or diagnostics or generation or close_terminates_child_processes"`

Expected: PASS. The successful-holder test observes no retained text; overflow test returns 8192 decoded bytes and `truncated=True`; replacement generation keeps its own projection; close/cancel tests leave no holder or reader resources.

- [x] **Step 5: Commit the MCP diagnostic boundary**

```bash
git add src/forgeagent/mcp_manager.py tests/test_mcp_manager.py
git commit -m "feat: add bounded MCP startup diagnostics"
```

### Task 2: Build the Private Interactive Startup Display

**Files:**
- Modify: `src/forgeagent/cli.py:24-40,856-1090,1127-1164,1554-1700`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 1 `MCPManager.diagnostics()`, existing `Console`, `Live`, identity/skill confirmer factories, and `Tier`.
- Produces: `_StartupDisplay(console: Console)`, `start(stage: str) -> None`, `set_stage(stage: str) -> None`, `pause() -> None`, `resume() -> None`, `stop() -> None`; `_interactive_repl(console, read_line_is_default) -> bool`.

- [x] **Step 1: Write failing display lifecycle and rendering tests**

Use a fake terminal `Console(force_terminal=True, width=100)`, a fake monotonic clock, and a `Live` factory recorder. Assert real TTY + default reader starts exactly one 8 FPS Live; seven phase frames use `red`, `yellow`, `green`, `cyan`, `blue`, `magenta`, `bright_magenta`; narrow width renders only `ForgeAgent`; `NO_COLOR`, `TERM=dumb`, CI and `console.color_system is None` do not construct animated Live. Test pause before identity/skill confirmation, resume after successful answer, and `finally` cleanup on `KeyboardInterrupt` and a startup exception.

```python
def _answer_identity_confirmation() -> bool:
    return True


def test_startup_display_pauses_for_confirmation_and_recreates_live(monkeypatch):
    display, lives = _display_with_recorded_live(monkeypatch)
    display.start("Loading identity")
    display.pause()
    _answer_identity_confirmation()
    display.resume()
    display.stop()
    assert [live.started for live in lives] == [True, True]
    assert all(live.stopped for live in lives)


def test_startup_display_narrow_terminal_is_single_line(monkeypatch):
    display = _display(width=12, monkeypatch=monkeypatch)
    assert display.logo_renderable().plain == "ForgeAgent"
```

- [x] **Step 2: Run display tests to verify RED**

Run: `uv run pytest tests/test_cli.py -q -k "startup_display or startup_renderer or startup_logo"`

Expected: FAIL because `_StartupDisplay` and `_interactive_repl` do not exist.

- [x] **Step 3: Implement minimal private renderer and confirmation adapter**

Add only private CLI helpers. The predicate must be exact and called once after reader selection:

```python
def _interactive_repl(console: Console, *, default_reader: bool) -> bool:
    return default_reader and console.is_terminal and sys.stdin.isatty()


def _startup_ui_available(console: Console) -> bool:
    return (
        console.is_terminal
        and os.environ.get("TERM") != "dumb"
        and not any(name in os.environ for name in ("CI", "GITHUB_ACTIONS", "BUILD_NUMBER"))
    )
```

`_StartupDisplay` owns an optional `Live`; its `get_renderable` callback derives the palette offset from `int(time.monotonic() * 8) % 7`. `Live(console=self._console, refresh_per_second=8, transient=True, get_renderable=self.renderable)` must be created on `start`/`resume`, never restarted. `pause()` calls `stop()` and leaves the stage intact. `stop()` is idempotent, calls `live.stop()` once, then sets the member to `None`; all REPL startup work stays under `try/finally: display.stop()`.

Wrap the existing confirmer calls with a small context manager that invokes `display.pause()` before `read_line` and resumes only if initialization continues. Preserve EOF/KeyboardInterrupt behavior by re-raising them after cleanup. Do not alter injected-reader semantics or create a `PromptSession` in that path.

- [x] **Step 4: Run renderer tests and existing reader regression**

Run: `uv run pytest tests/test_cli.py -q -k "startup_display or startup_renderer or startup_logo or repl_explicit_reader_never_constructs_prompt_session or repl_exits_cleanly_on_keyboard_interrupt"`

Expected: PASS; no Live instance exists for explicit reader/non-TTY/no-color paths and every started fake Live is stopped.

- [x] **Step 5: Commit the renderer lifecycle**

```bash
git add src/forgeagent/cli.py tests/test_cli.py
git commit -m "feat: render interactive startup information"
```

### Task 3: Wire Startup Summary, `/mcp` Details, and Sanitized Startup Errors

**Files:**
- Modify: `src/forgeagent/cli.py:639-668,856-1090,1127-1164,1554-1700`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 1 diagnostics tuple and Task 2 display lifecycle.
- Produces: `build_mcp_manager() -> MCPManager | None` with no `Console` argument and no output; `_render_startup_summary(console: Console, *, model: str, tier: Tier, root: str, diagnostics: tuple[MCPServerDiagnostic, ...]) -> None`; bare `/mcp` uses `diagnostics()` while `/mcp status|tools|enable|disable` remains accepted.

- [x] **Step 1: Write failing CLI behavior tests**

Add tests for: `build_mcp_manager()` does not print; summary includes selected model, tier, resolved root, and `MCP 1/2`; disabled state is excluded; no enabled MCP omits count; an optional Docker diagnostic prints exactly one fixed line and no secret/raw stderr; required failure raises before any `Ready` output; bare `/mcp` prints at most Status/Tools/Reason/Impact/Action lines per server and omits absent optional fields; status/enable/disable/tools continue their existing behavior and timeout prints fixed pending text.

```python
def _terminal_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=True, color_system="standard")


def _lines(*values: str) -> Callable[[str], str]:
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def _patch_diagnostics(
    monkeypatch, *, available: int, enabled: int, optional_code: str
) -> "_DiagnosticManager":
    values = tuple(
        MCPServerDiagnostic(
            name=f"server-{index}", enabled=True, required=False,
            status="available" if index < available else "unavailable: Docker is not running",
            tool_count=0, reason=None if index < available else "Docker is not running",
            impact=None if index < available else "Configured tools are disabled",
            action=None if index < available else "Start Docker or disable this server",
        )
        for index in range(enabled)
    )
    manager = _DiagnosticManager(values)
    monkeypatch.setattr(cli, "build_mcp_manager", lambda: manager)
    return manager


class _DiagnosticManager:
    def __init__(self, values: tuple[MCPServerDiagnostic, ...]) -> None:
        self._values = values

    def diagnostics(self) -> tuple[MCPServerDiagnostic, ...]:
        return self._values

    def required_failures(self) -> dict[str, str]:
        return {}

    def close(self) -> None:
        return None


def test_interactive_optional_failure_prints_one_fixed_degradation_line(monkeypatch):
    console = _terminal_console()
    manager = _patch_diagnostics(
        monkeypatch, available=1, enabled=2, optional_code="docker_unavailable"
    )
    _render_startup_summary(
        console,
        tier=Tier.RESTRICTED,
        model="claude-sonnet-5",
        root="/project",
        diagnostics=manager.diagnostics(),
    )
    output = console.file.getvalue()
    assert "MCP 1/2" in output
    assert output.count("Docker is not running") == 1
    assert "docker.sock" not in output


def test_required_mcp_failure_has_only_sanitized_stderr(monkeypatch, capsys):
    monkeypatch.setattr(cli, "build_mcp_manager", lambda: (_ for _ in ()).throw(MCPStartupError("startup_failed")))
    exit_code = cli.main([])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "startup_failed" in captured.err
    assert captured.out == ""
```

- [x] **Step 2: Run the CLI contract tests to verify RED**

Run: `uv run pytest tests/test_cli.py -q -k "build_mcp_manager or startup_summary or optional_failure or required_mcp or mcp_command"`

Expected: FAIL because the builder requires `Console`, emits lines itself, no summary exists, and slash command still derives all output from `server_status()`.

- [x] **Step 3: Move output ownership to REPL and implement fixed text rendering**

Change the signature to `def build_mcp_manager() -> MCPManager | None`; retain config load, manager construction, connect, required check and bounded cleanup. On connect/required failure, raise `MCPStartupError` built solely from a fixed diagnostic code/label, never from status or exception text. `main()` must create separate `Console()` stdout and `Console(stderr=True)` stderr objects, catch startup/config/container/identity/MCP errors through the stderr console, and return exit code 2 while normal task output stays stdout.

After successful interactive initialization and before first goal, call a renderer with deterministic lines:

```python
def _render_startup_summary(console: Console, *, model: str, tier: Tier, root: str,
                            diagnostics: tuple[MCPServerDiagnostic, ...]) -> None:
    enabled = [item for item in diagnostics if item.enabled]
    available = sum(item.status == "available" for item in enabled)
    fields = ["Ready", f"model {model}", f"sandbox {tier.value}", f"project {root}"]
    if enabled:
        fields.insert(1, f"MCP {available}/{len(enabled)}")
    console.print(" | ".join(fields))
```

Print the fixed optional message once per unavailable enabled optional diagnostic, using only `(name, reason, impact, action)` from Task 1. Required diagnostics are checked first and render no partial summary. For bare `/mcp`, render each diagnostic with no more than five labeled lines, using `Text` literals so bracket content cannot become Rich markup. Keep `/mcp status`, `/mcp tools`, `/mcp enable`, `/mcp disable` compatible; update the usage string to list all four forms.

- [x] **Step 4: Run targeted CLI tests**

Run: `uv run pytest tests/test_cli.py -q -k "build_mcp_manager or startup_summary or optional_failure or required_mcp or mcp_command or runtime_toggle_of_required"`

Expected: PASS. Existing runtime required-toggle test still keeps the REPL alive; no builder output is captured; public text contains neither test secret nor exception class.

- [x] **Step 5: Commit CLI output ownership and diagnostics**

```bash
git add src/forgeagent/cli.py tests/test_cli.py
git commit -m "feat: report MCP startup capability safely"
```

### Task 4: Enforce Non-TTY Input and Process-Level Output Contracts

**Files:**
- Modify: `src/forgeagent/cli.py:856-1090,1554-1700`
- Modify: `tests/mcp_fixture_server.py:1-53`
- Create: `tests/test_cli_startup_blackbox.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 3 stdout/stderr split and `build_mcp_manager() -> MCPManager | None`.
- Produces: default non-TTY reader that calls `input()`/stream read without a prompt; subprocess tests invoke the installed `forgeagent` console script with isolated HOME and fixture config.

- [x] **Step 1: Write failing black-box and regression tests**

Create `_forgeagent_process(argv: list[str], stdin: bytes, env: dict[str, str]) -> CompletedProcess[bytes]`, implemented as `subprocess.run(argv, input=stdin, capture_output=True, text=False, env=env, check=False)`, then use it to assert exit 0 and exact `stdout == b""`, `stderr == b""`. Add a pipe-goal test with a scripted local model double/entrypoint hook that proves MCP connects and only task result appears. Add optional fixture stderr output/failure and assert no Docker/SDK/path/secret raw text in either stream. Add required failure test asserting exit 2, stdout empty, stderr has only fixed text. Unit-test default non-TTY reader receives `""` prompt while terminal reader receives `"forge> "`.

```python
def test_pipe_quit_has_no_startup_bytes(isolated_cli_env):
    result = _forgeagent_process(["forgeagent"], b"quit\\n", isolated_cli_env)
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


def test_required_mcp_failure_is_stderr_only(isolated_cli_env):
    result = _forgeagent_process(["forgeagent"], b"", _required_failure_env(isolated_cli_env))
    assert result.returncode == 2
    assert result.stdout == b""
    assert b"startup_failed" in result.stderr
    assert b"Traceback" not in result.stderr
```

- [x] **Step 2: Run black-box tests to verify RED**

Run: `uv run pytest tests/test_cli_startup_blackbox.py tests/test_cli.py -q -k "pipe or non_tty or startup_bytes"`

Expected: FAIL: current REPL prompt/banner/MCP status reaches stdout and required errors are not guaranteed to use the dedicated stderr console.

- [x] **Step 3: Implement the non-TTY reader boundary and fixture modes**

Select the reader once. When interactive predicate is false, use a callable that reads a line without passing a prompt to `input`; do not call PromptSession or `console.print()` for startup UI. Preserve EOF, `KeyboardInterrupt`, empty line, confirmations and Survey behavior exactly. Keep MCP manager creation in non-TTY REPL so submitted goals retain tools.

Extend `tests/mcp_fixture_server.py` only with environment-selected test modes: `startup_chatter` writes a benign line to stderr before normal server startup; `docker_failure` writes a Docker-daemon-shaped line then terminates before handshake. The test must use synthetic values and never require Docker.

- [x] **Step 4: Run non-TTY, stdout/stderr, and command-path regressions**

Run: `uv run pytest tests/test_cli_startup_blackbox.py tests/test_cli.py -q -k "pipe or non_tty or startup_bytes or main_reports_required_mcp_startup_error or run"`

Expected: PASS. `run`, `serve`, `models`, and `smoke` have no Logo or optional startup-status output; pipe quit is exactly two zero-length streams.

- [x] **Step 5: Commit the black-box contract**

```bash
git add src/forgeagent/cli.py tests/mcp_fixture_server.py tests/test_cli_startup_blackbox.py tests/test_cli.py
git commit -m "fix: silence noninteractive startup output"
```

### Task 5: Document the Contract and Produce Verification Evidence

**Files:**
- Modify: `README.md:20-71,222-241`
- Modify: `docs/m7-tools-mcp-survey.md:1-5,122-130`
- Create: `docs/superpowers/reports/2026-07-23-startup-information-verify.md`
- Modify: `openspec/changes/startup-information/tasks.md`

**Interfaces:**
- Consumes: final behavior from Tasks 1-4.
- Produces: user documentation that distinguishes real-interactive REPL from non-TTY/script paths; verification report containing literal command outcomes and the human TTY smoke result.

- [ ] **Step 1: Write the final contractual output assertion before editing prose**

In `tests/test_cli.py`, add `test_mcp_diagnostic_uses_only_fixed_public_labels`: make a diagnostic whose internal source includes `docker.sock`, an exception class name and a secret; invoke bare `/mcp`; assert output contains `Status`, `Tools`, `Reason`, `Impact`, `Action` and `Docker is not running`, while every internal value is absent. Do not assert animation ANSI escape sequences in documentation or tests.

- [ ] **Step 2: Run the acceptance check**

Run: `uv run pytest tests/test_cli.py -q -k "startup_summary or mcp_command"`

Expected: PASS before documentation edits because behavior is already complete; this confirms docs will describe proven output rather than prescribe unimplemented behavior.

- [ ] **Step 3: Update docs and verification report with exact scope**

In `README.md`, document that the logo/summary is real-TTY REPL only; `printf 'quit\\n' | forgeagent` intentionally produces no startup bytes; task result output remains available on non-TTY goal input; `/mcp` shows bounded safe diagnostics. In the MCP section, describe Docker only as an optional configured integration runtime, never a ForgeAgent prerequisite. In `docs/m7-tools-mcp-survey.md`, update the current runtime addendum with per-generation stderr isolation and no raw child-error exposure.

Mark only completed implementation tasks in `openspec/changes/startup-information/tasks.md`; do not alter requirements. Create the report with each command, exit status, relevant count, environment limitations, human smoke observations, review findings/fixes, and an explicit dirty-path audit against the Global Constraints list.

- [ ] **Step 4: Run final automated verification**

Run:

```bash
uv run pytest tests/test_mcp_manager.py tests/test_cli.py tests/test_cli_startup_blackbox.py -q
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/run_golden_core.py
openspec validate startup-information --strict
uv build --out-dir /tmp/forgeagent-startup-information-build
git diff --check
git status --short
```

Expected: focused and full pytest pass; Ruff reports no diagnostics and no formatting changes; golden core reports exactly `20/20`; OpenSpec prints `Change 'startup-information' is valid`; build emits wheel and sdist; diff check is empty; status has no changes outside this change plus the pre-existing dirty paths declared above. Record actual output rather than treating an unavailable build backend/network as a pass.

- [ ] **Step 5: Run the human interactive smoke before final commit**

In a real terminal, run `uv run forgeagent` with one available fixture MCP and then with one configured optional failure. Confirm: transient animation is visible; static logo and one summary appear; optional message is one line; prompt does not overlap a Live refresh; `/mcp` exposes only fixed fields; identity/skill confirmation pauses input safely; Ctrl-C/quit restores cursor and leaves no background refresh. Repeat `printf 'quit\\n' | uv run forgeagent` and record zero bytes for both streams.

- [ ] **Step 6: Perform two review passes and commit the completed change**

First compare every requirement/scenario in `openspec/changes/startup-information/specs/*/spec.md` to Tasks 1-5 and their test evidence. Second inspect the final diff for raw exception interpolation, capture/reader leaks, old-generation publication, Rich markup injection, disabled-server denominator mistakes, unexpected non-TTY output, and accidental pre-existing files. Fix each finding with a focused test and rerun the affected test plus the complete command block above.

```bash
git add README.md docs/m7-tools-mcp-survey.md docs/superpowers/reports/2026-07-23-startup-information-verify.md openspec/changes/startup-information/tasks.md tests/test_cli.py
git commit -m "docs: verify startup information behavior"
```

## Final Requirement Traceability

| Requirement / risk | Tasks and executable evidence |
| --- | --- |
| bounded per-generation child stderr and no raw disclosure | Task 1 capture, secret, overflow, success-clear, replacement-generation and close tests |
| optional degradation and required abort/cleanup | Tasks 1 and 3 diagnostics, required failure, cleanup regression tests |
| injected reader/non-TTY compatibility and zero-byte quit | Tasks 2 and 4 explicit-reader and subprocess pipe tests |
| interactive logo lifecycle, color/narrow fallback, confirmation pause | Task 2 fake Live/TTY/clock/confirmation tests plus Task 5 human smoke |
| actual capability summary and disabled denominator | Task 3 summary unit tests |
| `/mcp` safe details and compatibility | Task 3 slash command tests, Task 5 docs/smoke |
| full change quality gate | Task 5 focused/full pytest, Ruff, golden `20/20`, OpenSpec strict, build, diff, two review passes |
