---
change: hardening-core-correctness
design-doc: docs/superpowers/specs/2026-07-13-hardening-core-correctness-design.md
base-ref: 44456c57e2ef76990f44846eadb83bc8d5e25166
---

# ForgeAgent Core Correctness Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 ForgeAgent 的代理 SSRF 绕过、工具确认、完成状态和 MCP 生命周期问题，并建立 20 项完全离线、自动判定和报告的黄金可信核心。

**Architecture:** 在现有模块边界内完成最小加固：网络、CLI、Step 和 MCPManager 各自维护所属契约，不新增统一策略层。测试侧新增 `tests/golden/`，以类型化 manifest 绑定固定场景 callable，由单一 runner 生成 JSON 和 Markdown 报告。

**Tech Stack:** Python >=3.11、标准库 `urllib`/`asyncio`/`tempfile`、Pydantic v2、pytest、Rich、PyYAML、现有 MCP SDK、uv、Ruff。

## Global Constraints

- `spec.md` 是最高约束；结论先行、实证汇报、最小范围、未验证不得声称通过。
- 不增加依赖，不修改 `resource/agent/`，不引入厂商端点、凭证或代理转发功能。
- 所有实现遵循 Ponytail：优先标准库和现有 helper，不新增 manager/factory/policy 抽象。
- 所有行为变更先建立可观察的 RED，再写最小 GREEN；每个任务独立运行定向测试并提交。
- OpenSpec 五份 delta specs 是验收事实源；Design Doc 是实现事实源。
- 基础 CI 和 20 项黄金核心不得访问公网、Docker、真实模型凭证或真实 `~/.forgeagent`。
- 保留用户对 `ACTION_PLAN.md` 中 M11/M12 的现有改动；文档收尾只补加固事实，不重排用户规划。
- 每次理解或修改产品调用路径前先使用 CodeGraph。当前索引来自主 checkout，若报告 different-worktree/stale 警告，则只把图结果用于调用路径与影响面，当前 worktree 的直接源码读取、diff 和测试才是实现事实源；不在 worktree 内自行重建用户管理的索引。

---

### Task 1: 隔离测试 HOME 并稳定环境能力断言

**Files:**
- Create: `tests/conftest.py`
- Modify: `tests/test_ssrf_guard.py`
- Modify: `tests/test_mcp_manager.py`
- Modify: `tests/mcp_fixture_server.py`
- Reference: `src/forgeagent/mcp_manager.py`, `src/forgeagent/model_registry.py`, `src/forgeagent/web_search.py`, `src/forgeagent/model_discovery.py`

**Interfaces:**
- Produces: pytest session hook 隔离的 `HOME`/`USERPROFILE`；`FORGE_TEST_MCP_PID_FILE` 测试协议；本地 socket bind capability helper。
- Consumes: pytest hooks、标准库 tempfile/shutil/os、现有 `_server()` MCP fixture config helper。

- [x] **Step 1: 添加测试进程启动前 HOME 隔离 hook**

在 `tests/conftest.py` 定义唯一 stash key，`pytest_sessionstart` 创建 worker 专属目录并保存原环境，`pytest_sessionfinish` 恢复环境和删除目录：

```python
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_HOME_STATE = pytest.StashKey[tuple[Path, str | None, str | None]]()


def pytest_sessionstart(session: pytest.Session) -> None:
    worker = getattr(session.config, "workerinput", {}).get("workerid", "main")
    home = Path(tempfile.mkdtemp(prefix=f"forgeagent-test-home-{worker}-"))
    session.config.stash[_HOME_STATE] = (
        home,
        os.environ.get("HOME"),
        os.environ.get("USERPROFILE"),
    )
    os.environ["HOME"] = str(home)
    os.environ["USERPROFILE"] = str(home)


def pytest_sessionfinish(session: pytest.Session) -> None:
    state = session.config.stash.get(_HOME_STATE, None)
    if state is None:
        return
    home, old_home, old_userprofile = state
    for name, value in (("HOME", old_home), ("USERPROFILE", old_userprofile)):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    shutil.rmtree(home, ignore_errors=True)
```

- [x] **Step 2: 写隔离回归并验证 RED/GREEN**

在 `tests/test_mcp_manager.py` 断言默认 MCP 路径位于测试 home，且测试进程看不到开发者真实配置。运行：

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_mcp_manager.py tests/test_cli.py -q
```

预期：新增隔离断言 PASS；测试不连接用户 MCP server。

- [x] **Step 3: 用 PID 文件替换全局进程计数**

在 `tests/mcp_fixture_server.py` 启动时执行：

```python
from pathlib import Path

pid_file = os.environ.get("FORGE_TEST_MCP_PID_FILE")
if pid_file:
    Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")
```

扩展 `tests/test_mcp_manager.py::_server()` 允许传入每服务唯一 PID 文件。泄漏测试读取 PID，用 `os.kill(pid, 0)` 和有截止时间的轮询判断 close 后进程消失，不再比较全局 `ps` 行数。

- [x] **Step 4: 让本地 bind 测试按能力诚实 skip**

`test_guarded_urlopen_blocks_loopback_target` 改为不启动 server，直接请求一个 loopback URL 并断言 socket connect 未发生。保留 redirect server 测试，但 `_start_server()` 捕获 `PermissionError/OSError` 后调用 `pytest.skip("local socket bind is unavailable")`。

- [x] **Step 5: 运行基线并记录结果**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run ruff check src tests
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest -q -ra
```

预期：Ruff PASS；真实 HOME 不再造成 CLI/MCP 失败；Docker/公网/本地 bind 不可用时只出现带理由的 skip。

- [x] **Step 6: 提交测试隔离**

```bash
git add tests/conftest.py tests/test_ssrf_guard.py tests/test_mcp_manager.py tests/mcp_fixture_server.py
git commit -m "test: isolate user configuration and process fixtures"
```

### Task 2: 禁用环境代理并约束重定向

**Files:**
- Modify: `src/forgeagent/ssrf_guard.py`
- Modify: `tests/test_ssrf_guard.py`
- Modify: `tests/test_web_search.py`
- Modify: `tests/test_web_file_tools.py`

**Interfaces:**
- Produces: `_GuardedRedirectHandler`、`_MAX_REDIRECTS = 10`；不变的 `guarded_urlopen(url, timeout=...)` 公共接口。
- Consumes: `_ALLOWED_SCHEMES`、`SSRFGuardError`、现有 guarded HTTP/HTTPS handlers。

- [x] **Step 1: 写环境代理和重定向 RED 测试**

覆盖以下断言：

```python
def test_environment_proxy_does_not_replace_guarded_target(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://8.8.8.8:9999")
    with pytest.raises(SSRFGuardError, match="127.0.0.1"):
        guarded_urlopen("http://127.0.0.1/resource", timeout=0.1)


def test_redirect_handler_rejects_eleventh_hop():
    handler = _GuardedRedirectHandler()
    request = urllib.request.Request("https://example.com/0")
    request._forgeagent_redirect_count = 10
    with pytest.raises(SSRFGuardError, match="redirect limit exceeded"):
        handler.redirect_request(request, None, 302, "Found", {}, "https://example.com/11")


@pytest.mark.parametrize("url", ["ftp://example.com/a", "file:///etc/passwd"])
def test_redirect_handler_rejects_non_http_scheme(url):
    handler = _GuardedRedirectHandler()
    request = urllib.request.Request("https://example.com/start")
    with pytest.raises(SSRFGuardError, match="scheme"):
        handler.redirect_request(request, None, 302, "Found", {}, url)
```

同时参数化 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY 及小写变体。先运行并确认至少环境代理或新符号测试 FAIL：

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_ssrf_guard.py -q
```

- [x] **Step 2: 实现空 ProxyHandler 和 guard-owned redirect handler**

在 `src/forgeagent/ssrf_guard.py` 增加：

```python
_MAX_REDIRECTS = 10


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        scheme = urllib.parse.urlsplit(newurl).scheme.lower()
        if scheme not in _ALLOWED_SCHEMES:
            raise SSRFGuardError(f"redirect scheme {scheme!r} is not allowed")
        count = getattr(req, "_forgeagent_redirect_count", 0)
        if count >= _MAX_REDIRECTS:
            raise SSRFGuardError(f"redirect limit exceeded ({_MAX_REDIRECTS})")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected._forgeagent_redirect_count = count + 1
        return redirected
```

opener 构造改为显式实例：

```python
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _GuardedRedirectHandler(),
    _GuardedHTTPHandler(),
    _GuardedHTTPSHandler(),
)
```

不得 `pop` 或修改代理环境变量。

- [x] **Step 3: 验证 WebFetch 和 search 共用修复路径**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_ssrf_guard.py tests/test_web_search.py tests/test_web_file_tools.py -q
```

预期：代理矩阵、10/11 hop、FTP/file redirect、NAT64、private redirect 全部 PASS；受限本地 bind 只产生有理由的 skip。

- [x] **Step 4: 提交网络边界修复**

```bash
git add src/forgeagent/ssrf_guard.py tests/test_ssrf_guard.py tests/test_web_search.py tests/test_web_file_tools.py
git commit -m "fix: enforce direct guarded web connections"
```

### Task 3A: 完成 confirmer URL 组件脱敏

**Existing checkpoint:** 初始类型安全 formatter、TTY 注入和拒绝原因已在 `a370811`、`72a1585`、`66612f6` 实现并通过 484 tests；本任务只完成最终 blocked review 指出的 hostname/组件交互与字符数契约。

**Files:**
- Modify: `src/forgeagent/cli.py`
- Modify: `tests/test_cli.py`
- Verify: `tests/test_tools.py`
- Verify: `tests/test_web_file_tools.py`

**Interfaces:**
- Produces: `_mask_confirmation_hostname(hostname: str, secret_values: set[str]) -> str`；确定性的 `_redact_confirmation_url(url: str) -> str`；FileWrite `characters` 摘要。
- Consumes: `REDACTED`、`is_secret_name()`、`mask_secrets()`、`sensitive_env_values()`、`urllib.parse` 结构化 API。

- [x] **Step 1: 写 hostname、IPv6 和组件交互 RED 测试**

在 `tests/test_cli.py` 增加参数化断言，至少包含：

```python
@pytest.mark.parametrize(
    ("secret", "url"),
    [
        ("OPAQUE-VALUE-12345", "https://opaque-value-12345.example.com/public"),
        ("opaque-value-12345", "https://%6fpaque-value-12345.example.com/public"),
    ],
)
def test_confirmation_summary_masks_case_and_percent_encoded_hostname(
    secret, url, monkeypatch
):
    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: {secret})
    summary = _confirmation_summary(WebFetchArgs(url=url))
    assert secret.casefold() not in unquote(summary).casefold()
    assert "REDACTED" in unquote(summary)


@pytest.mark.parametrize("encoded", ["%40", "%2F", "%3F", "%23", "%3A"])
def test_confirmation_summary_does_not_reinterpret_encoded_hostname_delimiters(encoded):
    summary = _confirmation_summary(WebFetchArgs(url=f"https://safe{encoded}host/public"))
    assert summary == "WebFetch <redacted malformed URL>"


def test_confirmation_summary_handles_ipv6_zone_and_masks_each_component_once(monkeypatch):
    secret = "opaque-value-12345"
    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: {secret})
    summary = _confirmation_summary(
        WebFetchArgs(
            url=(
                "https://[fe80::1%25en0]/opaque-value-12345"
                "?q=opaque-value-12345#discard-me"
            )
        )
    )
    rendered = unquote(summary)
    assert "[fe80::1%en0]" in rendered
    assert secret not in rendered
    assert rendered.count("***REDACTED***") == 2
    assert "discard-me" not in rendered


def test_filewrite_confirmation_labels_unicode_character_count():
    summary = _confirmation_summary(FileWriteArgs(path="out.txt", content="你好"))
    assert summary.endswith("(2 characters)")
```

另加 overlapping secret 测试，证明最长值优先且不做重叠二次替换：

```python
def test_confirmation_summary_prefers_longest_overlapping_hostname_secret(monkeypatch):
    monkeypatch.setattr(
        "forgeagent.cli.sensitive_env_values",
        lambda: {"opaque-value-12345", "value-12345"},
    )
    rendered = unquote(
        _confirmation_summary(
            WebFetchArgs(url="https://opaque-value-12345.example.com/public")
        )
    )
    assert rendered.count("***REDACTED***") == 1
    assert "value-12345" not in rendered
```

- [x] **Step 2: 运行 RED 测试并记录失败**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_cli.py -q
```

预期：percent-encoded/case hostname、encoded delimiter 和 `characters` 标签至少一项 FAIL。

- [x] **Step 3: 实现单次 hostname 匹配和结构化重建**

在 `cli.py` 导入 `ipaddress`、`re` 和 `REDACTED`。局部 helper 只处理已经解码的 hostname：

```python
def _mask_confirmation_hostname(hostname: str, secret_values: set[str]) -> str:
    candidates = sorted(
        (value for value in secret_values if value),
        key=lambda value: (-len(value), value.casefold(), value),
    )
    if not candidates:
        return hostname
    pattern = re.compile(
        "|".join(re.escape(value) for value in candidates),
        flags=re.IGNORECASE | re.ASCII,
    )
    return pattern.sub(REDACTED, hostname)
```

`_redact_confirmation_url()` 必须一次读取 `secret_values`，先丢弃 userinfo/fragment。用原始 `netloc.rsplit("@", 1)[-1].startswith("[")` 判断 bracketed IPv6；先验证 `ipaddress.IPv6Address(decoded_hostname)`，再掩码并把 zone `%` 重编码为 `%25`。非 bracketed hostname 若解码后含 `@/:?#`，直接返回 malformed；否则 quote 掩码后的 hostname component。path/query 各调用一次全局 `mask_secrets()`，重建后不得对完整 URL 再掩码。

FileWrite 摘要固定为：

```python
return f"FileWrite {safe_path} ({len(args.content)} characters)"
```

- [x] **Step 4: 运行 confirmer 回归**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_cli.py tests/test_tools.py tests/test_web_file_tools.py -q
```

预期：formatter、TTY/non-TTY、autoApprove、Survey `--interactive` 和新 URL matrix 全部 PASS。

- [x] **Step 5: 提交 confirmer 完成修复**

```bash
git add src/forgeagent/cli.py tests/test_cli.py
git commit -m "fix: complete confirmation URL redaction"
```

### Task 3B: 收敛 WebFetch 与 search 消费端异常

**Files:**
- Modify: `src/forgeagent/tools.py`
- Modify: `src/forgeagent/web_search.py`
- Modify: `tests/test_web_file_tools.py`
- Modify: `tests/test_web_search.py`
- Modify: `tests/test_step.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: WebFetch 固定 details `WebFetch blocked by network policy`、`WebFetch request failed`、`WebFetch response save failed`；`/search` unknown-charset UTF-8 fallback。
- Consumes: `http.client.HTTPException`、`SSRFGuardError`、`ERROR_UNAVAILABLE`、`Step._render_feedback()`、`render_outcome()`。

- [x] **Step 1: 写 HTTPException、artifact 和反馈路径 RED 测试**

在 `tests/test_web_file_tools.py` 用 fake response 的 open/read/exit 注入代表性异常：

```python
class _RaisingResponse(_FakeResponse):
    def __init__(self, exc: Exception, *, stage: str = "read") -> None:
        super().__init__(b"")
        self._exc = exc
        self._stage = stage

    def read(self, n: int = -1) -> bytes:
        if self._stage == "read":
            raise self._exc
        return super().read(n)

    def __exit__(self, *exc_info) -> bool:
        if self._stage == "exit":
            raise self._exc
        return False


@pytest.mark.parametrize("stage", ["open", "read", "exit"])
@pytest.mark.parametrize(
    "exc",
    [
        http.client.InvalidURL("nonnumeric port"),
        http.client.BadStatusLine("secret-host.invalid"),
        http.client.LineTooLong("status line"),
        http.client.IncompleteRead(b"partial", 10),
        http.client.RemoteDisconnected("secret-host.invalid closed connection"),
    ],
)
def test_webfetch_http_protocol_failures_are_fixed_and_do_not_raise(
    stage, exc, monkeypatch
):
    def fake_open(url, **kwargs):
        if stage == "open":
            raise exc
        return _RaisingResponse(exc, stage=stage)

    monkeypatch.setattr("forgeagent.tools.guarded_urlopen", fake_open)
    outcome = WebFetchTool().run(WebFetchArgs(url="https://secret-host.invalid/"), _webfetch_ctx())
    assert outcome.success is False
    assert outcome.detail == "WebFetch request failed"
```

open 阶段让 monkeypatched `guarded_urlopen()` 直接抛异常；read/exit 阶段由 response 抛出。三处消费边界都有明确 RED 证据。

用 `patch.object(Path, "write_text", side_effect=OSError("/host/private/path"))` 断言 `WebFetch response save failed`。在 `tests/test_web_search.py` 断言代表性 `HTTPException` 返回 `([], ERROR_UNAVAILABLE)`，未知 charset 使用 UTF-8 replacement 后继续解析。

在 `tests/test_step.py` 构造带固定 failure detail 的 `RoundResult`，断言 `_render_feedback()` 不含 secret URL；在 `tests/test_cli.py` 用 `render_outcome()` 断言普通 CLI 输出同样不含异常文本。

- [x] **Step 2: 运行网络消费端 RED 测试**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_web_file_tools.py tests/test_web_search.py tests/test_step.py tests/test_cli.py -q
```

预期：HTTPException 或 artifact OSError 逃逸，search unknown charset 抛 `LookupError`，固定 feedback 断言 FAIL。

- [x] **Step 3: 实现局部固定错误类别**

在 `tools.py` 导入 `http.client`，保持 SSRF 分类优先：

```python
try:
    response = guarded_urlopen(args.url)
    with response:
        content_type = response.headers.get_content_type()
        raw = response.read(_MAX_FETCH_BYTES + 1)
except SSRFGuardError:
    return ToolOutcome(tool="WebFetch", success=False, detail="WebFetch blocked by network policy")
except (OSError, http.client.HTTPException, ValueError):
    return ToolOutcome(tool="WebFetch", success=False, detail="WebFetch request failed")
```

artifact 写入使用独立 try/except，避免误报网络失败：

```python
try:
    dest.write_text(masked, encoding="utf-8", errors="replace")
except OSError:
    return ToolOutcome(tool="WebFetch", success=False, detail="WebFetch response save failed")
```

`web_search.py` 捕获 `(OSError, http.client.HTTPException)`；decode 仅对 `LookupError` 回退：

```python
try:
    html = raw.decode(charset, errors="replace")
except LookupError:
    html = raw.decode("utf-8", errors="replace")
```

不得增加覆盖整个函数的 `except Exception`。

- [x] **Step 4: 运行网络消费端回归**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_web_file_tools.py tests/test_web_search.py tests/test_step.py tests/test_cli.py -q
```

预期：代表性 HTTPException、invalid URL、artifact save、search unavailable/fallback、Step/CLI 最小披露全部 PASS。

- [x] **Step 5: 提交网络消费端修复**

```bash
git add src/forgeagent/tools.py src/forgeagent/web_search.py tests/test_web_file_tools.py tests/test_web_search.py tests/test_step.py tests/test_cli.py
git commit -m "fix: contain guarded web consumer failures"
```

### Task 3C: 修复文件路径边界和失败披露

**Files:**
- Modify: `src/forgeagent/tools.py`
- Modify: `src/forgeagent/_sandbox_worker.py`
- Modify: `tests/test_web_file_tools.py`
- Modify: `tests/test_restricted_backend.py`
- Modify: `tests/test_step.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: root-safe `_validate_path(path: str, allowed_root: str) -> Path`；FileRead/FileList 固定失败 detail；FileWrite canonical project-relative success detail。
- Consumes: `os.path.realpath()`、`os.path.commonpath()`、`os.path.normcase()`、restricted audit hook。

- [x] **Step 1: 写 root、NUL、固定错误和 canonical success RED 测试**

在 `tests/test_web_file_tools.py` 增加：

```python
def test_validate_path_accepts_descendant_when_allowed_root_is_filesystem_root(tmp_path):
    assert _validate_path(str(tmp_path / "file.txt"), os.path.abspath(os.sep)) == (
        tmp_path / "file.txt"
    ).resolve()


@pytest.mark.parametrize(
    ("tool", "args", "detail"),
    [
        (FileReadTool(), FileReadArgs(path="bad\x00path"), "FileRead failed"),
        (FileWriteTool(), FileWriteArgs(path="bad\x00path", content="x"), "FileWrite failed"),
        (FileListTool(), FileListArgs(path="bad\x00path"), "FileList failed"),
    ],
)
def test_file_tools_contain_invalid_path_value_error(tool, args, detail, tmp_path):
    outcome = tool.run(args, _file_ctx(allowed_root=str(tmp_path)))
    assert outcome.success is False
    assert outcome.detail == detail
```

再覆盖：越界和 monkeypatched OSError 不含模型路径/root；`allowed_root="."` 与绝对项目内 FileWrite 成功均只返回 `wrote nested/file.txt`；静态 symlink 指向外部仍拒绝。`tests/test_restricted_backend.py` 用 `RestrictedBackend(allowed_root=os.path.abspath(os.sep))` 只读取测试创建的 tmp 文件，证明 audit hook 不再因 `//` predicate 误拒绝。

- [x] **Step 2: 运行文件边界 RED 测试**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_web_file_tools.py tests/test_restricted_backend.py tests/test_step.py tests/test_cli.py -q
```

预期：filesystem root 和 NUL 测试 FAIL；FileRead/List 仍回显绝对路径；FileWrite success 仍回显原始 args.path。

- [x] **Step 3: 实现 commonpath 和固定 outcome**

`tools.py` 与 `_sandbox_worker.py` 保持独立的小判定，不新增模块：

```python
def _is_within_root(root: str, target: str) -> bool:
    try:
        common = os.path.commonpath((root, target))
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(root)
```

`_validate_path()` 在 `realpath()` 或 commonpath 失败时抛不含路径的 `PermissionError`/`ValueError`。FileRead/FileList 对 `(PermissionError, OSError, ValueError)` 分别返回 `FileRead failed` / `FileList failed`；FileWrite 保留越界 detail `FileWrite path is outside project root`，对 invalid/write failure 返回 `FileWrite failed`。

FileWrite success 只能由 canonical 值生成：

```python
base = Path(os.path.realpath(ctx.allowed_root))
relative = resolved.relative_to(base).as_posix()
return ToolOutcome(tool="FileWrite", success=True, detail=f"wrote {relative}")
```

restricted audit hook 使用相同 commonpath/normcase 逻辑，拒绝消息固定为 `restricted: file access outside allowed root denied`，不附带 path。

- [x] **Step 4: 运行文件边界和反馈回归**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_web_file_tools.py tests/test_restricted_backend.py tests/test_step.py tests/test_cli.py -q
```

预期：root-safe containment、静态 symlink 拒绝、NUL 收敛、固定失败消息、canonical success 和 Step/CLI 无路径泄漏全部 PASS。

- [x] **Step 5: 提交文件边界修复**

```bash
git add src/forgeagent/tools.py src/forgeagent/_sandbox_worker.py tests/test_web_file_tools.py tests/test_restricted_backend.py tests/test_step.py tests/test_cli.py
git commit -m "fix: harden file tool path boundaries"
```

### Task 3D: 收口 CLI 确认通道与 M9 命令迁移

**Files:**
- Modify: `src/forgeagent/cli.py`
- Modify: `tests/test_cli.py`
- Verify later: `README.md`（Task 10 统一同步用户文档）

**Interfaces:**
- Produces: REPL 显式 terminal-capability 注入；MCP identifier/FileWrite safe-path 已知 secret 脱敏；仅 slash-prefixed REPL command 路由。
- Consumes: `sys.stdin.isatty()`、`Console.is_terminal`、`mask_secrets()`、`sensitive_env_values()`、现有 `_confirmation_summary()` 和 slash handlers。

- [ ] **Step 1: 写非 TTY、identifier/path 脱敏和裸词迁移 RED 测试**

在 `tests/test_cli.py` 增加：

- 非 TTY REPL 的 scripted response 请求 WebFetch/FileWrite 或非 auto-approved MCP 时，confirmation reader 若被调用就立即失败；断言工具返回 `rejected: no interactive confirmation channel available`，而 goal reader 仍可完成后续轮次。
- TTY REPL 显式 terminal-capability 为真时仍调用同一个 `read_line` 完成 y/N 确认。
- 已知环境 secret 出现在 MCP server、MCP tool、FileWrite 项目相对路径和外部 basename 时，summary 不包含原值；FileWrite content 仍不显示。
- 参数化输入 `models`、`reload`、`mcp`、`mcp status` 都完整进入 `run_once()`，无 deprecation 文本；`/model`、`/reload`、`/mcp` 仍只走 handler。现有顶层 `main(["models"])` 测试继续通过。

- [ ] **Step 2: 运行 RED 测试**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_cli.py -q
```

预期：非 TTY REPL 会读取确认输入、identifier/path 泄漏 secret，裸词仍被 compat 分支截获，新增测试 FAIL。

- [ ] **Step 3: 实施最小 CLI 收口**

`repl()` 增加 `confirmation_available: bool | None = None`；未提供时按 `console.is_terminal and sys.stdin.isatty()` 计算。只在该值为真时创建 confirmer，否则向 `run_once()` 传 `None`。测试可显式传 true/false，不把注入的 `read_line` 自动视为 TTY。

`_confirmation_summary()` 一次读取已知 secret values：MCP server/tool、非敏感 arguments string 和 FileWrite 安全路径分别使用现有 `mask_secrets()`；结构化敏感键仍直接 `<redacted>`。不得新增通用 sanitizer。

删除 REPL 的 bare-word compatibility rewrite；不修改 argparse 的顶层 `models` subcommand，也不改变 slash handler。

- [ ] **Step 4: 运行 CLI 与工具确认回归**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_cli.py tests/test_tools.py tests/test_web_file_tools.py -q
```

预期：TTY/non-TTY、autoApprove、Survey 分离、identifier/path 脱敏、裸词目标与 slash command 全部 PASS。

- [ ] **Step 5: 提交 CLI 收口**

```bash
git add src/forgeagent/cli.py tests/test_cli.py
git commit -m "fix: close CLI confirmation and command-routing gaps"
```

### Task 3E: 阻断 WebFetch artifact 静态 symlink 逃逸

**Files:**
- Modify: `src/forgeagent/tools.py`
- Modify: `tests/test_web_file_tools.py`

**Interfaces:**
- Produces: WebFetch artifact canonical root containment；固定 `WebFetch response save failed` 越界结果。
- Consumes: 现有 `_validate_path()`、URL digest artifact name、`ToolContext.allowed_root`。

- [ ] **Step 1: 写 artifact symlink RED 测试**

根据测试 URL 计算现有 digest artifact 文件名，在 `allowed_root` 内预置同名 symlink 指向 root 外文件；fake response 返回已知 body。断言 WebFetch 返回 `WebFetch response save failed`，外部文件内容不变。当前 artifact 直接位于 root，不虚构不存在的中间目录测试；`_validate_path()` 既有 file-tool symlink ancestor 用例继续覆盖通用祖先解析。

- [ ] **Step 2: 运行 RED 测试**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_web_file_tools.py -q
```

预期：当前 `Path.write_text()` 跟随预置 symlink，外部目标被覆盖，新增断言 FAIL。

- [ ] **Step 3: 写入前复用 canonical path guard**

仅把生成的相对 artifact filename 交给 `_validate_path(filename, ctx.allowed_root)`，并使用返回的 canonical `Path` 写入。`PermissionError`、`ValueError` 和 write `OSError` 都收敛为既有 `WebFetch response save failed`；不得引入新 helper、随机文件名或平台专用 fd API。

- [ ] **Step 4: 运行 WebFetch/File 回归并提交**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_web_file_tools.py tests/test_step.py tests/test_cli.py -q
git add src/forgeagent/tools.py tests/test_web_file_tools.py
git commit -m "fix: contain WebFetch artifact paths"
```

### Task 4: 实施严格两阶段完成门控

**Files:**
- Modify: `src/forgeagent/step.py`
- Modify: `tests/test_step.py`
- Modify: `tests/test_task.py`

**Interfaces:**
- Produces: `_apply_declared_status(..., allow_completed: bool)`。
- Consumes: `ParseResult.tool_calls/errors`、现有 Termination 和 feedback loop。

- [x] **Step 1: 写工具成功、失败和 parse error RED 测试**

每个测试用两条或三条 MockClient response：第一条携带 `completed: true` 与工具/错误，最后一条是独立完成。断言第一轮 `completed=False`、有 outcome/parse error，最终轮才 `Termination.COMPLETED`。另写 max_rounds=1 断言不伪造完成。

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_step.py tests/test_task.py -q
```

预期：至少同轮工具失败 + completed 测试在现实现上 FAIL。

- [x] **Step 2: 增加最小资格参数**

```python
self._apply_declared_status(
    rr,
    parsed.task_status,
    allow_completed=not parsed.tool_calls and not parsed.errors,
)


def _apply_declared_status(
    self,
    rr: RoundResult,
    status: TaskStatus | None,
    *,
    allow_completed: bool,
) -> None:
    if status is None:
        return
    if status.completed:
        if allow_completed:
            rr.completed = True
            rr.stopped_reason = Termination.COMPLETED
        return
    declared = _DECLARED_STATUS.get(status.status or "")
    if declared is not None:
        rr.stopped_reason = declared
```

不得根据工具成功、autoApprove 或 confirmer 状态恢复同轮完成。

- [x] **Step 3: 运行 Step/Task/回放测试**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_step.py tests/test_task.py tests/test_mock_replay_e2e.py -q
```

预期：严格门控和现有 prose/refused/need_info/failed 分类全部 PASS。

- [x] **Step 4: 提交完成语义修复**

```bash
git add src/forgeagent/step.py tests/test_step.py tests/test_task.py
git commit -m "fix: require standalone task completion responses"
```

### Task 5: 增加 MCP required 启动语义

**Files:**
- Modify: `src/forgeagent/mcp_manager.py`
- Modify: `src/forgeagent/cli.py`
- Modify: `tests/test_mcp_manager.py`
- Modify: `tests/test_cli.py`
- Modify: `src/forgeagent/res/mcp.yaml`

**Interfaces:**
- Produces: `MCPServerConfig.required: bool`、`MCPManager.required_failures() -> dict[str, str]`、`MCPStartupError`。
- Consumes: 现有 `server_status()`、`enabled`、`connect_timeout=15.0`、CLI exit code 2 路径。

- [x] **Step 1: 写配置、optional/required 和运行期 RED 测试**

覆盖 omitted required=False、required+disabled 不阻断、optional timeout 降级、required unavailable 关闭 manager 后 exit 2、REPL enable/disable required 不退出。

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_mcp_manager.py tests/test_cli.py -q
```

预期：required 字段或 required_failures 不存在导致 FAIL。

- [x] **Step 2: 增加配置字段和只读失败查询**

```python
class MCPStartupError(RuntimeError):
    """Required MCP services were unavailable during CLI startup."""


class MCPServerConfig(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    required: bool = False
```

```python
def required_failures(self) -> dict[str, str]:
    return {
        name: state.status
        for name, state in self._states.items()
        if state.config.enabled and state.config.required and state.status != "available"
    }
```

- [x] **Step 3: 在 CLI 组装层执行启动裁决**

`build_mcp_manager()` 连接后收集 failures；非空时调用 close，再抛包含排序后 `name: status` 的 `MCPStartupError`。`main()` 捕获该异常、打印 `[red]MCP startup error[/red]` 并返回 2。optional unavailable 继续黄色输出。

- [x] **Step 4: 更新内置 MCP 示例并运行回归**

在 `src/forgeagent/res/mcp.yaml` 的注释示例加入 `required: false` 及语义，不改变默认空配置。

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_mcp_manager.py tests/test_cli.py tests/test_tools.py -q
```

- [x] **Step 5: 提交 MCP 启动策略**

```bash
git add src/forgeagent/mcp_manager.py src/forgeagent/cli.py src/forgeagent/res/mcp.yaml tests/test_mcp_manager.py tests/test_cli.py
git commit -m "feat: support required MCP services"
```

### Task 6A: 用 generation token 重建 MCP holder/session ownership

**Files:**
- Modify: `src/forgeagent/mcp_manager.py`
- Modify: `tests/test_mcp_manager.py`

**Interfaces:**
- Produces: `_ServerState.generation`、`tearing_down_generation`、`restart_after_generation`；`_holders: dict[str, tuple[int, asyncio.Task, asyncio.Event]]`；`_sessions: dict[str, tuple[int, object]]`；loop-owned `_start_holder()`、`_finalize_holder_slot()` 和 generation-aware `_holder()`。
- Consumes: existing `MCPServerConfig`, `MCPToolInfo`, `mask_secrets()`, `_render_content()` and synchronous manager API.

- [x] **Step 1: Add the preserved RED regressions and generation-specific RED cases**

Keep these existing assertions unchanged:

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest \
  tests/test_mcp_manager.py::test_connect_interrupt_releasing_publication_gate_stops_running_loop \
  tests/test_mcp_manager.py::test_enable_during_timed_out_disable_restarts_after_old_holder_cleanup \
  -q -W error::RuntimeWarning
```

Add tests for `test_re_enable_old_holder_finally_does_not_delete_replacement_session`, `test_call_failure_does_not_invalidate_replacement_session`, `test_call_selection_occurs_on_loop_for_current_generation`, `test_enable_racing_failed_holder_finalizer_starts_one_replacement`, `test_enable_after_failed_holder_finalized_starts_one_generation`, and `test_disable_during_holder_initialization_never_publishes_available`. Make each test assert the externally visible status/tools/session behavior, not only private dict shape. Run the focused file and confirm the new tests fail against the name-keyed implementation.

- [x] **Step 2: Replace name-only state with exact generation slots**

Change `_ServerState` and manager fields to the exact shapes above. Remove all uses of `_ServerState.stop` and direct main-thread `_sessions.pop()`/`_holders.pop()`. Allocate `state.generation + 1` only inside loop-owned `_start_holder()`. Create `(generation, task, stop)` before the task can run, and close the coroutine if task creation fails; that failure sets a fixed unavailable status and an already-set ready event without leaving a partial slot.

Implement `_finalize_holder_slot(name, generation, task)` as the only holder-slot remover. It must compare the current tuple including task/stop before clearing session, tools or status. Clear `tearing_down_generation` only for the matching generation. Start a replacement only when `restart_after_generation == generation`, `config.enabled` is true, and neither `_closed` nor loop-owned `_closing` is true; clear the restart intent before allocating the next generation. The done callback must consume ordinary task exceptions and call this function on the loop thread.

Update the existing pre-Task-6C shutdown code and all test fixtures to unpack exact holder slots instead of assuming dict values are bare tasks. This is a compatibility bridge only: keep its existing deadline behavior until Task 6C, but all stop/cancel/finalize operations must already use the slot generation and stop event so the generation tests can pass without a mixed representation.

- [x] **Step 3: Make holder publication and failure cleanup generation-safe**

Change the holder signature to receive `generation`, `ready`, and its generation-specific `stop`. After every initialize/list-tools await, verify the exact slot, enabled desired state, stop flag and closing barrier before publishing the session tuple, tools and `available` status. On failure, expose only `unavailable: <ExceptionType>`, set ready, and do not include exception text. In `finally`, remove only the matching `(generation, session)` and never overwrite a newer generation. Active call failure must mark the exact generation unavailable and stop it, but must not set `restart_after_generation`; explicit `enable()` is required for retry.

- [x] **Step 4: Route enable/disable/retry through loop-owned reconcile**

When the loop exists, `enable()` and `disable()` submit loop coroutines; they do not mutate config, slots, sessions or status from the caller thread. `enable()` starts a holder when no slot exists even if `config.enabled` was already true; for an unavailable/finishing exact slot it sets desired enabled, `tearing_down_generation`, `restart_after_generation`, status `restarting`, clears tools, and signals only that stop event. `disable()` sets desired disabled, clears restart intent, keeps the holder slot until its task is done, clears catalog state and signals only that generation. Before initial connect, direct config mutation remains allowed; an all-disabled `connect()` leaves the manager pre-start with no loop.

Close the already-preserved publication-gate RED in this task by requesting `loop.stop()` before the rollback join when gate release throws after the worker entered `run_forever()`. Preserve the primary `KeyboardInterrupt`/`SystemExit` object. Task 6B will extend this from the current set-then-raise case to gate failure before set and the full startup transaction.

- [x] **Step 5: Make call selection loop-owned and verify generation behavior**

Implement a loop-owned call wrapper that selects the current `(generation, session)` immediately before invoking `session.call_tool(...)`. The synchronous facade only submits that wrapper and receives the existing structured result contract. A call exception invalidates only the captured matching session/status/tools and signals its exact holder; it cannot remove or mark a replacement. Preserve the SDK inner read timeout before the outer facade timeout.

- [x] **Step 6: Run the generation-focused GREEN suite and commit**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_mcp_manager.py -q -W error::RuntimeWarning
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run ruff check src/forgeagent/mcp_manager.py tests/test_mcp_manager.py
```

Expected: the preserved gate and timed-out disable regressions plus generation, stale-finalizer, current-call, failed-holder retry and initialization-disable cases pass with no RuntimeWarning. Commit:

```bash
git add src/forgeagent/mcp_manager.py tests/test_mcp_manager.py
git commit -m "fix: make MCP holder ownership generation-safe"
```

### Task 6B: Make MCP startup and synchronous lifecycle waiters transactional

**Files:**
- Modify: `src/forgeagent/mcp_manager.py`
- Modify: `src/forgeagent/cli.py`
- Modify: `tests/test_mcp_manager.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: publication-gated startup rollback; must-deliver loop-owned lifecycle operations with cancelable synchronous waiters; shared-deadline initial holder startup; fixed public MCP status diagnostics.
- Consumes: Task 6A generation slots and `MCPStartupError`/CLI construction from Task 5.

- [x] **Step 1: Add startup, waiter, timeout-race and disclosure RED tests**

Add `test_timed_out_disable_then_close_leaves_no_lifecycle_waiter`, `test_connect_gate_release_before_set_preserves_exception_and_stops_worker`, `test_connect_initial_submission_control_exception_preserves_identity`, `test_multiple_hung_initial_holders_share_ready_deadline`, `test_ready_publish_cannot_be_overwritten_by_timeout`, `test_holder_task_creation_failure_closes_coroutine`, and `test_optional_status_does_not_expose_secret_exception_text`. Run them against Task 6A and verify each fails for the missing behavior or wrong state transition.

- [x] **Step 2: Implement cancel-aware publication-gated startup**

Use local `loop`, `startup_gate`, and `startup_cancelled` objects. The worker waits for publication with short timed waits while also checking cancellation; it never enters `run_forever()` before manager `_loop`, `_thread`, and `_started` are published. On any `Thread.start()`, publication, or gate-release `BaseException`, preserve the primary exception, set cancellation, best-effort release the gate, request `loop.stop()` whether the worker has started the loop or not, bounded-join, and close/reset only when the thread is stopped. If still alive, retain refs, set closed/started conservatively, mark startup cleanup complete because no holder was published, and rethrow the primary exception. Cleanup exceptions are logged by type and never replace the primary control exception. `build_mcp_manager()` 的 startup/required-failure cleanup 同样只传播新的 `KeyboardInterrupt`/`SystemExit`；`asyncio.CancelledError` 等其他 `BaseException` 不得替换 primary `MCPStartupError`。

- [x] **Step 3: Implement shared initial ready deadline and waiter cancellation**

Start every enabled holder before the first await. Use one monotonic start deadline and concurrent ready waiters; a timeout writes `unavailable: connect timeout` only after checking the exact generation and `ready.is_set()`. `_submit()` must separate a must-deliver loop-owned lifecycle operation from its concurrent waiter: timeout/control cancellation cancels the waiter, then a loop callback idempotently ensures the operation starts even when the loop had not entered the wrapper. Track only lifecycle operation tasks until their done callbacks consume results. Disable operations await `asyncio.shield(holder_task)` so waiter cancellation cannot cancel holder cleanup; enable/connect operations only await generation-specific ready and never own the holder slot. Add a blocked-loop regression proving a timed-out disable intent still executes.

- [x] **Step 4: Sanitize public MCP diagnostics**

Make `server_status()` return fixed status categories/types passed through `mask_secrets()`, matching `required_failures()`. Keep server names and cause type, but never expose exception strings, command, args, env or server-returned content in optional diagnostics, required startup errors or close warnings. Add tests through both `build_mcp_manager()` and REPL status rendering.

- [x] **Step 5: Run Task 6B GREEN tests and commit**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_mcp_manager.py tests/test_cli.py -q -W error::RuntimeWarning
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run ruff check src/forgeagent/mcp_manager.py tests/test_mcp_manager.py tests/test_cli.py
```

Expected: startup control exceptions preserve object identity, no live startup worker remains in the normal injected cases, multiple hung servers do not multiply the ready timeout, no pending lifecycle waiter warnings appear, and public status is secret-safe. Commit:

```bash
git add src/forgeagent/mcp_manager.py tests/test_mcp_manager.py tests/test_cli.py
git commit -m "fix: make MCP startup and lifecycle waits transactional"
```

### Task 6C: Implement one loop-owned shutdown drain with absolute deadline

**Files:**
- Modify: `src/forgeagent/mcp_manager.py`
- Modify: `src/forgeagent/cli.py`
- Modify: `tests/test_mcp_manager.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/mcp_fixture_server.py`

**Interfaces:**
- Produces: `shutdown_timeout=10.0`、`thread_join_timeout=2.0`；fixed `forgeagent-mcp-loop`；`_shutdown_future` as first-call facade；unique loop-owned `_shutdown_task` with retry event and exact slot snapshot；idempotent `close() -> None` for ordinary cleanup failures.
- Consumes: Task 6A exact slots, Task 6B startup/submit behavior, SDK stdio process-tree cleanup and `_remaining()`.

- [ ] **Step 1: Add shutdown RED matrix before changing close behavior**

Add/retain tests for normal close, holder ignoring stop until cancel, delayed async context cleanup, loop thread hard-stuck, internal shutdown exception, repeated close after a canceled facade, repeated close after cleanup completion, result preservation, warning sanitization, and exact `(name, generation, task, stop)` snapshot. Add targeted RED cases for: dead thread with empty maps but unproven completion/pending facade; close racing a partially-started initial holder loop must not allocate the next generation; lifecycle `cancel()` ordinary failure must not kill the authoritative drain; mismatched holder/session/state generations must not call SDK; current call failure sets teardown generation; timed-out disable overlaps close before holder release; holder stop signal is observed before lifecycle cancellation; drain completion during join is consumed by the same close; startup cleanup `CancelledError` preserves the primary startup error. Use PID files for real fixture process assertions and distinguish graceful-stop and cancel markers. Confirm the focused matrix fails against the existing shutdown implementation without loosening the two preserved regressions.

- [ ] **Step 2: Add shutdown state and exact loop snapshot ownership**

Add `_closing`, `_lifecycle_tasks`, `_shutdown_task`, `_shutdown_retry`, exact holder/lifecycle snapshots, `_shutdown_complete`, and the configured budgets. The first loop-owned shutdown entry sets `_closing` and snapshots every current `(name, generation, task, stop)` plus lifecycle operation before its first await. Every queued reconcile and every iteration that can call `_start_holder()` rechecks `_closed`/`_closing` before allocating a generation. A call wrapper verifies session generation against both `state.generation` and the current holder slot; active-generation call failure sets `tearing_down_generation` before signalling stop. Main-thread fallback stores only server names for diagnostics; it never copies or mutates live holder/session containers.

- [ ] **Step 3: Implement shielded authoritative drain**

The loop-owned task signals exact snapshot stop events before any potentially blocking lifecycle cleanup, then cancels snapshot lifecycle operations and exact pending holders, and waits gracefully using `_remaining(deadline, reserve=thread_join_timeout)`. Tests record this order, not merely eventual events. Every stop/cancel/result/finalizer operation isolates ordinary `Exception`; a lifecycle task whose `cancel()` fails cannot terminate the sole drain or prevent retry. No unbounded lifecycle gather may prevent holder stop/cancel or make the retry event unreachable. Async context finalizers may continue past the public deadline. The drain invokes the same idempotent generation finalizer after `asyncio.wait()` because done callbacks are not ordered before wait return. Ordinary holder/finalizer exceptions are collected by type; the task does not stop the loop or set completion until all snapshot tasks are done, exact holder/session cleanup holds, and `_lifecycle_tasks` is empty. If an invariant remains false, the same task waits on `_shutdown_retry` without busy looping; repeated close signals that event with a new deadline and never creates a second task or snapshot.

- [ ] **Step 4: Implement absolute-deadline public close and delayed retry**

First `close()` sets `_closed=True`, creates `deadline = monotonic() + shutdown_timeout + thread_join_timeout`, submits `_wait_for_shutdown()` and shields the authoritative task. Timeout/cancel of the concurrent facade cancels only the facade and retains the future for diagnostics. Repeated close signals the existing retry event, waits on the thread-safe `_shutdown_complete` event for the remaining shutdown budget, then performs bounded `thread.join()`. Only when completion and thread stop are both proven may the main thread close the loop and clear future/task/holder/session/lifecycle/loop/thread refs. A dead thread with unproven completion remains incomplete even when holder/session/lifecycle maps are empty or `_shutdown_task` is absent/done; `close()` cannot synthesize `_shutdown_complete` from those containers. After join, re-read `_shutdown_complete` so completion during join is cleared in the same close. A live or cleanup-incomplete thread keeps all refs and receives a fixed warning containing thread identity, sanitized pending names and timeout, never args/env/content. Catch ordinary `Exception` per operation; do not swallow `KeyboardInterrupt` or `SystemExit`. Wall-clock assertions use a narrow scheduling allowance, while fake future/thread tests assert the exact facade/join timeout arguments derived from the single deadline.

- [ ] **Step 5: Run full MCP/CLI, fixture PID and static validation**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_mcp_manager.py tests/test_cli.py tests/test_tools.py -q -W error::RuntimeWarning
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest -q -ra
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run ruff check src tests
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run ruff format --check src tests
```

Expected: all MCP shutdown/startup/generation tests pass, fixture PIDs disappear on normal and holder-stuck paths, hard-stuck retains only documented residual refs/warning, full pytest has no new failures or warnings, and Ruff is clean.

- [ ] **Step 6: Commit the complete MCP lifecycle implementation**

```bash
git add src/forgeagent/mcp_manager.py tests/test_mcp_manager.py tests/test_cli.py tests/mcp_fixture_server.py
git commit -m "fix: harden MCP lifecycle ownership and shutdown"
```

### Task 7: 建立黄金 manifest、runner 和报告协议

**Files:**
- Create: `tests/golden/__init__.py`
- Create: `tests/golden/manifest.py`
- Create: `tests/golden/cases.py`
- Create: `tests/golden/runner.py`
- Create: `tests/test_golden_runner.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `GoldenScenario`、`GoldenEvidence`、`GoldenResult`、`validate_manifest()`、`run_suite()`、`main()`。
- Consumes: MockClient/real ModelClient、Task/CLI entrypoints、独立临时目录。

- [ ] **Step 1: 写 manifest 和报告 RED 测试**

测试固定 20 ID、唯一性、精确 5 real callable、未知/重复 ID preflight exit 2、两项 fake suite 的 0/1 exit、JSON/Markdown 同一 summary、preflight 不写报告、原子覆盖。

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_golden_runner.py -q
```

预期：`tests.golden` 模块不存在导致 collection ERROR。

- [ ] **Step 2: 定义类型化 manifest 接口**

```python
@dataclass(frozen=True)
class GoldenEvidence:
    detail: str
    evidence: dict[str, object]


OfflineRunner = Callable[[Path], GoldenEvidence]
RealRunner = Callable[[Path, ModelClient], GoldenEvidence]


@dataclass(frozen=True)
class GoldenScenario:
    scenario_id: str
    title: str
    run_offline: OfflineRunner
    run_real: RealRunner | None = None
```

manifest 中显式列出设计文档批准的 20 ID；只有 G01/G03/G08/G11/G43 设置 real callable。

- [ ] **Step 3: 实现 runner preflight 和结果模型**

`validate_manifest()` 比较精确 frozenset、数量和 real set，并读取 `docs/golden-tasks-seed.md`，使用行首 heading/table 正则证明每个 ID 有定义。失败抛 `GoldenPreflightError`。

`run_suite()` 对每项使用 `TemporaryDirectory`，捕获 `GoldenCheckError` 和 Exception 为失败结果但继续执行。preflight 在输出目录创建前完成。

- [ ] **Step 4: 实现同源报告和 exit code**

JSON schema 固定 `forgeagent.golden.v1`；Markdown 从同一个 suite result 渲染。每个文件先写同目录临时文件，再 `os.replace()`。默认目录为 `artifacts/golden/offline` 或 `artifacts/golden/real/<sanitized-model>`；并发调用要求不同 `--output-dir`。

- [ ] **Step 5: 运行 runner 合约测试并提交**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_golden_runner.py -q
```

```bash
git add .gitignore tests/golden tests/test_golden_runner.py
git commit -m "test: add executable golden validation runner"
```

### Task 8: 实现 10 项通用黄金任务和 5 项真实模型入口

**Files:**
- Modify: `tests/golden/cases.py`
- Modify: `tests/golden/manifest.py`
- Modify: `tests/test_mock_replay_e2e.py`
- Modify: `tests/test_golden_runner.py`

**Interfaces:**
- Produces: G01/G03/G05/G08/G11/G13/G15/G17/G27/G43 offline callables；G01/G03/G08/G11/G43 real callables。
- Consumes: `GoldenEvidence`、MockClient scripted AssistantMessage、RestrictedBackend、TaskOutcome。

- [ ] **Step 1: 把现有 G01/G05/G13 迁移为共享 case**

case 必须创建自己的输入，执行 Task，并显式检查：G01 sum=60/mean=20；G05 side effect 一次且 state=42/output=50；G13 failed tool 与 successful tool 轮都携带提前 completed，最终第三轮独立完成。

- [ ] **Step 2: 实现其余 7 项通用 offline case**

逐项判定固定为：G03 深层 JSON 字段和值精确匹配；G08 给定失败测试转 PASS；G11 合并去重集合与顺序匹配；G15 block version+1 且 old 消失/new 出现；G17 join 后键集合与字段值匹配；G27 给定回归测试从 FAIL 到 PASS；G43 Top-N 词和计数精确匹配。

所有 check 使用显式 helper：

```python
def require(condition: bool, message: str) -> None:
    if not condition:
        raise GoldenCheckError(message)
```

- [ ] **Step 3: 实现 5 项 real callable**

real callable 与 offline 使用同一 fixture 和 judge，只替换 client。`runner --real-model` 在执行前调用现有 `build_real_client(model_id)`；解析/凭证失败转 preflight exit 2 且不创建报告。

- [ ] **Step 4: 让旧回放测试调用共享 case**

`tests/test_mock_replay_e2e.py` 不再复制脚本，按 ID 从 manifest 取 offline callable，在 `tmp_path` 或 case 自身目录执行，断言不抛 `GoldenCheckError`。

- [ ] **Step 5: 运行 10 项通用核心**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-golden-common
```

在 Task 9 完成前 runner 会报告未实现边界 case；本步骤另用 pytest 选择通用 ID，预期 10/10 PASS：

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_mock_replay_e2e.py tests/test_golden_runner.py -q
```

- [ ] **Step 6: 提交通用黄金任务**

```bash
git add tests/golden/cases.py tests/golden/manifest.py tests/test_mock_replay_e2e.py tests/test_golden_runner.py
git commit -m "test: implement trusted golden task core"
```

### Task 9: 实现 10 项加固边界黄金任务

**Files:**
- Modify: `tests/golden/cases.py`
- Modify: `tests/golden/manifest.py`
- Modify: `tests/test_golden_runner.py`

**Interfaces:**
- Produces: G06/G14/G58/G59/G324/G329/G330/G332/G333/G355 offline callables；完整 20 项离线 runner。
- Consumes: RestrictedBackend、ToolContext、guarded_urlopen、CLI/MCP test doubles、TaskOutcome。

- [ ] **Step 1: 实现 sandbox/project-root 五项判定**

G06 restricted 越权返回结构化失败且未读取目标；G14 timeout 轮失败后后续任务仍成功；G58 项目外读被 audit hook 拦截；G59 项目外写未生成文件；G324 FileWrite 越界返回 escapes project root 且目标不存在。

- [ ] **Step 2: 实现 SSRF/确认四项判定**

G329 private/metadata 在 socket connect 前拒绝；G330 public-first-hop double 的第二跳 private 被拒；G332 无 confirmer 时不发网络、true confirmer 时成功；G333 false confirmer 不写文件但后续 Exec 可在 allowed_root 内写入，证明确认门不是文件安全边界。

- [ ] **Step 3: 实现 MCP G355 产品级冒烟**

使用一个可用 fixture server 和一个 optional 失败 server。判定状态输出同时包含 available/unavailable、工具目录只含可用 server、manager 在 case finally 中 close 且 PID 消失。required/absolute deadline 的故障矩阵继续由 Task 5/6 单测承担。

- [ ] **Step 4: 运行完整离线 runner**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run python -m tests.golden.runner
```

预期：进程退出 0；`artifacts/golden/offline/results.json` 和 `report.md` 均报告 total=20、passed=20、failed=0、pass_rate=100.0。

- [ ] **Step 5: 验证失败与 real preflight**

pytest 注入一个 failing scenario，断言仍运行后续项、退出 1、报告含失败 ID。以不存在模型运行：

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run python -m tests.golden.runner --real-model nonexistent-model
```

预期：退出 2，real 输出目录下不存在通过率报告。

- [ ] **Step 6: 提交边界黄金任务**

```bash
git add tests/golden/cases.py tests/golden/manifest.py tests/test_golden_runner.py
git commit -m "test: cover hardened runtime boundaries in golden core"
```

### Task 10: 同步协议、威胁模型和 ACTION_PLAN

**Files:**
- Modify: `docs/model-client-contract.md`
- Modify: `docs/text-protocol-spec.md`
- Modify: `docs/threat-model.md`
- Modify: `docs/golden-tasks-seed.md`
- Modify: `docs/m7-tools-mcp-survey.md`
- Modify: `docs/m10-usage-observability-and-tools.md`
- Modify: `README.md`
- Modify: `ACTION_PLAN.md`

**Interfaces:**
- Produces: 与运行时和验证证据一致的公开契约；`[SECURITY][BREAKING]` 环境代理说明；20/360/5 黄金口径；`ACTION_PLAN.md` 中明确的 M13 加固行。
- Consumes: 最终测试命令、黄金 JSON/Markdown、现有 M11/M12 用户规划。

- [ ] **Step 1: 更新模型与文本协议契约**

`model-client-contract.md` 准确记录 complete/stream 和 TextItem/ImageItem；`text-protocol-spec.md` 增加 WebFetch/FileRead/FileWrite/FileList/MCP，并写明工具/parse error 轮次不能完成。

- [ ] **Step 2: 更新安全与 MCP 文档**

`threat-model.md` 写入以下已批准边界：

- `ProxyHandler({})` 禁用大小写环境代理，`NO_PROXY` 不能重新启用代理；HTTP(S) redirect 最多 10 跳且每跳重新校验。
- 未来显式代理只能选择 trusted-forward-proxy 或 guarded-tunnel trust model，本 change 不实现 `network.proxy`。
- `realpath + commonpath` 阻止静态 symlink alias escape，但不能消除攻击者并发替换 canonical ancestor 的 TOCTOU；restricted tier 仍假设 host/trusted code/MCP 不并发改写 `allowed_root` 祖先。
- fixed outcome message 主动牺牲底层诊断文本，避免 URL、hostname 和宿主路径回流到 Step/CLI。
- event-loop thread 完全卡死时 MCP transport、FD 或 child process 可能暂留；CLI 按 deadline 返回、保留引用并输出 `shutdown incomplete; resources may remain`，不声称能强杀 Python thread。

README 的 release-facing compatibility note 必须使用 `[SECURITY][BREAKING]`，明确依赖企业环境代理的部署会直连失败，且不得建议用 `NO_PROXY` 或恢复环境 `ProxyHandler` 规避。只列三条可操作迁移路径：允许 ForgeAgent 进程直连；由外部可信进程预取到 `allowed_root` 后用 FileRead；改用用户显式信任的 MCP fetch 工具。

README 同时删除“裸 `models`/`reload`/`mcp ...` 仍可用”的过期说明，明确 REPL 内嵌命令必须带 `/`；保留并区分顶层 `forgeagent models` 子命令。

`docs/m10-usage-observability-and-tools.md` 同步 direct-only WebFetch、固定 WebFetch/FileRead/FileWrite/FileList outcome、WebFetch artifact canonical containment、静态 symlink 阻断和 ancestor-swap residual；`docs/m7-tools-mcp-survey.md` 加入 `required`、optional degrade、absolute deadline、固定 thread 诊断和 incomplete-shutdown residual。TTY/non-TTY、autoApprove 和不抓取线程堆栈的理由也写入对应边界说明。

- [ ] **Step 3: 重写黄金验证口径**

`golden-tasks-seed.md` 增加可信核心区块，列出精确 20 ID、5 real ID 和 runner 命令；明确其余 360 只是 candidate。README 展示离线命令、报告路径、exit 0/1/2 和 real opt-in。

- [ ] **Step 4: 将加固范围登记为 ACTION_PLAN M13**

填充现有空置的 M13 行，记录本 change 的交付物、Ruff/完整 pytest/20 项离线黄金核心/CodeGraph 复审验证和三次评审门禁。保留用户 M11/M12 的内容与顺序，不修改或重编号它们。此步骤不创建里程碑文件、不更新 `milestones/latest`；`MILESTONE_GUIDE.md` 要求门禁全部通过后一次性产出收尾记录。

- [ ] **Step 5: 运行文档一致性测试**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_golden_runner.py -q
rg -n "380.*validated|380.*已验证|complete\(\).*only|不支持.*stream|裸词命令.*仍可用" README.md docs ACTION_PLAN.md milestones
```

预期：黄金 ID 同步测试 PASS；rg 不再命中过时的“380 已验证”和旧客户端契约，或每个命中都属于明确的历史说明。

- [ ] **Step 6: 提交文档同步**

```bash
git add README.md ACTION_PLAN.md docs
git commit -m "docs: align runtime contracts and golden validation"
```

### Task 11: 综合验证、CodeGraph 复审和任务收尾

**Files:**
- Modify: `openspec/changes/hardening-core-correctness/tasks.md`
- Create: `milestones/milestone_013.md`
- Modify: `milestones/latest`
- Generated only: `artifacts/golden/offline/results.json`, `artifacts/golden/offline/report.md`

**Interfaces:**
- Produces: 40/40 tasks 勾选、实证里程碑、完整离线报告、可进入 Comet verify 的提交状态。
- Consumes: 所有实现提交、OpenSpec specs、Design Doc、base ref。

- [ ] **Step 1: 运行静态检查**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run ruff check src tests
```

预期：`All checks passed!`。

- [ ] **Step 2: 运行专项测试**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest \
  tests/test_ssrf_guard.py \
  tests/test_web_search.py \
  tests/test_web_file_tools.py \
  tests/test_cli.py \
  tests/test_step.py \
  tests/test_task.py \
  tests/test_mcp_manager.py \
  tests/test_golden_runner.py -q -ra
```

预期：全部可运行测试 PASS；环境能力 skip 带明确原因。

- [ ] **Step 3: 运行隔离全量测试**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest -q -ra
```

预期：无人工 deselect；所有失败必须先按 systematic-debugging 修复，不能进入下一步。

- [ ] **Step 4: 运行 20 项离线黄金核心**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run python -m tests.golden.runner
```

预期：20/20、100.0%、退出 0；核对 JSON 与 Markdown summary 一致。没有显式模型和凭证时不运行 real 模式。

- [ ] **Step 5: 使用 CodeGraph 做最终调用面复审**

查询 `guarded_urlopen`, `make_console_confirmer`, `_apply_declared_status`, `MCPManager.connect/close`, `GoldenScenario` 的调用方。确认 WebFetch/search、run/REPL、Task/Step、MCP CLI 和测试入口均覆盖。若 CodeGraph 报 different-worktree/stale，记录警告及原因，并以当前 worktree 的直接源码、diff 和测试复核所有受影响文件；不把主 checkout 索引误当作当前实现，也不自行运行 `codegraph init`。

- [ ] **Step 6: 执行三道独立评审门禁**

1. 技术方案一致性评审：逐项对照 `spec.md`、五份 delta spec、Design Doc、计划和实现，修复错误、遗漏或漂移，并重新运行 `openspec validate hardening-core-correctness --strict`。
2. 对抗性代码评审：用 merge-base 到 HEAD 的完整 review package 派发独立 whole-branch reviewer，覆盖正确性、安全、并发、资源生命周期和测试可信度；Critical/Important 发现必须由单一 fix worker 收敛并重新评审、重跑受影响测试。
3. 验收证据评审：独立核对 Ruff、专项 pytest、全量 pytest、20 项黄金 JSON/Markdown/exit code 与文档声明，禁止把旧输出或预期值当成实测结果。

- [ ] **Step 7: 创建实证里程碑并回填 40 项 tasks**

全部门禁通过后，按 `MILESTONE_GUIDE.md` 一次性创建 `milestones/milestone_013.md`，把实际命令、pass/skip 数、黄金通过率和三次评审结论写入文件，并将 `milestones/latest` 更新为唯一一行 `milestone_013.md`。M11/M12 仍是未完成规划，因此 M13 的“前置里程碑”链接写为最后已完成的 `milestone_010.md`，并在正文说明编号跳跃原因。逐条核对本计划末尾映射后，将 `tasks.md` 的 40 个 checkbox 定向改为 `[x]`；不能一次性盲目全选。

- [ ] **Step 8: 提交验证收尾**

```bash
git add openspec/changes/hardening-core-correctness/tasks.md milestones
git commit -m "chore: record hardening verification evidence"
```

## OpenSpec Tasks Coverage Map

| OpenSpec tasks.md | Plan task |
| --- | --- |
| 1.1 | 2, 3, 4, 5, 6A-6C 的 RED 回归 |
| 1.2 | 1 |
| 1.3 | 1, 6C |
| 1.4 | 1 |
| 2.1-2.4 | 2, 10 |
| 3.1-3.3 | 3A |
| 3.4-3.5 | 4 |
| 3.6-3.7 | 3A, 3B, 3C |
| 3.8-3.9 | 3B, 3C |
| 3.10 | 3D |
| 3.11 | 3E |
| 4.1-4.3 | 5 |
| 4.4-4.6 | 6A, 6B, 6C |
| 5.1-5.5 | 7, 8, 9 |
| 6.1-6.5 | 10, 11 |
| 7.1-7.5 | 11 |

## Final Plan Self-Review

- Spec coverage: 五份 capability specs 和 tasks.md 40 项均在 coverage map 中有实施与验证任务。
- Type consistency: `GoldenScenario`, `GoldenEvidence`, `MCPStartupError`, `required_failures()`, `_GuardedRedirectHandler`, generation holder/session slots, `restart_after_generation` 和完成门控签名在生产者与消费者任务中一致。
- Scope: 未增加依赖、代理实现、通用策略层、并发 golden runner 或无关重构。
- Execution safety: 每个行为任务包含 RED、GREEN、定向测试和独立提交；综合验证不使用人工 deselect。
