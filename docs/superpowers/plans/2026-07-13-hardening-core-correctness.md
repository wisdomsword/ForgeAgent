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

**已实施复审回归登记（不扩展 capability）：** redirect 的最小修复是先 `urljoin` 相对 `Location`，再验证最终 HTTP(S) scheme，保留 max-10 和逐跳 SSRF；验收覆盖相对 Location、非 HTTP(S)、第 11 跳和私网 redirect。模型注册表的根因是 `ModelEntry` 未将既有 YAML `supports_images` 传给 `ModelCapability`；最小修复为默认 `false` 字段加原样透传，验收锁定六个内置 `true`、两个 `false` 与用户 override 显式 `false`。

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

已实施复审补充：`_GuardedRedirectHandler` 必须先以 `urljoin(request.full_url, location)` 得到最终 URL，再检查 HTTP(S) scheme；不能对原始相对 Location 做 scheme 决策。最终评审补充进一步要求 guard 覆盖 urllib 真实共享 30x `http_error_302` 管线，并显式绑定 301/302/303/307/308，使 file/FTP/unsupported scheme 在 stdlib scheme gate、destination handler 或 socket 构造前统一抛 `SSRFGuardError`；`redirect_request()` 继续保留 max-10 和 defense-in-depth scheme check。每跳 SSRF 校验保持不变，定向回归覆盖相对 Location、真实 opener pipeline 的 file/FTP、非 HTTP(S)、第 11 跳和 redirect 后私网目标。

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
- Produces: REPL 显式 terminal-capability 注入；MCP identifier/argument key/FileWrite safe-path 已知 secret 脱敏与单行 literal-safe Rich 渲染；仅 slash-prefixed REPL command 路由。
- Consumes: `sys.stdin.isatty()`、`Console.is_terminal`、`mask_secrets()`、`sensitive_env_values()`、现有 `_confirmation_summary()` 和 slash handlers。

- [x] **Step 1: 写非 TTY、literal-safe confirmation、identifier/path 脱敏和裸词迁移 RED 测试**

在 `tests/test_cli.py` 增加：

- 非 TTY REPL 的 scripted response 请求 WebFetch/FileWrite 或非 auto-approved MCP 时，confirmation reader 若被调用就立即失败；断言工具返回 `rejected: no interactive confirmation channel available`，而 goal reader 仍可完成后续轮次。
- TTY REPL 显式 terminal-capability 为真时仍调用同一个 `read_line` 完成 y/N 确认。
- 已知环境 secret 出现在 MCP server、MCP tool、嵌套 arguments mapping key、FileWrite 项目相对路径和外部 basename 时，summary 不包含原值；结构化 secret-name 判断仍使用未脱敏原 key，FileWrite content 仍不显示。
- 参数化 `bad[/red]`、`[bold]fake[/bold]`、ANSI/C0/C1、CR/LF、U+2028/U+2029、U+202E、U+2066/U+2069、U+200E 等 Unicode `Cf` 格式控制符，以及未配对 `\\ud800` surrogate 到 MCP identifier、嵌套 arguments mapping key/string value 与 FileWrite path：确认输出不抛 `MarkupError`/`UnicodeEncodeError`、不改变 `approve` 样式、不产生注入行或双向重排，控制/格式/surrogate 字符以可见转义呈现，整个摘要作为 Rich literal segments 渲染，且 `read_line` 只调用一次。
- 参数化输入 `models`、`reload`、`mcp`、`mcp status` 都完整进入 `run_once()`，无 deprecation 文本；`/model`、`/reload`、`/mcp` 仍只走 handler。现有顶层 `main(["models"])` 测试继续通过。

- [x] **Step 2: 运行 CLI RED 测试**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_cli.py -q
```

预期：非 TTY REPL 会读取确认输入、identifier/path 泄漏 secret、畸形 Rich tag 可在询问前抛错或控制文本可伪造行，裸词仍被 compat 分支截获，新增测试 FAIL。

- [x] **Step 3: 实施最小 CLI 收口**

`repl()` 增加 `confirmation_available: bool | None = None`；未提供时按 `console.is_terminal and sys.stdin.isatty()` 计算。只在该值为真时创建 confirmer，否则向 `run_once()` 传 `None`。测试可显式传 true/false，不把注入的 `read_line` 自动视为 TTY。

`_confirmation_summary()` 一次读取已知 secret values并递归传给 arguments formatter：MCP server/tool、每个展示用 mapping key、非敏感 arguments string value 和 FileWrite 安全路径分别使用现有 `mask_secrets()`；结构化敏感键判断仍使用原 key并把对应 value 直接替换为 `<redacted>`。masked display key 碰撞时只给展示标签追加确定性非敏感数字后缀，保留未碰撞标签，不能改变 raw arguments、不能用 dict 覆盖丢值，也不能扩展为通用 sanitizer。完整摘要通过 Rich `Text` literal segment 输出，并用一个 confirmation-only single-line formatter把 C0/C1、DEL、CR/LF、U+2028/U+2029，以及 `unicodedata.category(ch) in {"Cf", "Cs"}` 的格式控制符/未配对 surrogate 转成可见 `\\xNN`/`\\uNNNN`/`\\UNNNNNNNN`；不得仅 escape markup 后让终端控制、bidi 或不可编码 surrogate 原样通过，也不得扩展为通用 sanitizer。

删除 REPL 的 bare-word compatibility rewrite；不修改 argparse 的顶层 `models` subcommand，也不改变 slash handler。

- [x] **Step 4: 运行 CLI 与工具确认回归**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_cli.py tests/test_tools.py tests/test_web_file_tools.py -q
```

预期：TTY/non-TTY、autoApprove、Survey 分离、identifier/path 脱敏、literal-safe 单行确认、裸词目标与 slash command 全部 PASS。

- [x] **Step 5: 提交 CLI 收口**

```bash
git add src/forgeagent/cli.py tests/test_cli.py
git commit -m "fix: close CLI confirmation and command-routing gaps"
```

### Task 3E: 阻断 WebFetch artifact 静态 symlink 逃逸

**Files:**
- Modify: `src/forgeagent/tools.py`
- Modify: `tests/test_web_file_tools.py`

**Interfaces:**
- Produces: WebFetch artifact canonical root containment；artifact naming/path/write 的固定 `WebFetch response save failed` 结果。
- Consumes: 现有 `_validate_path()`、URL digest artifact name、`ToolContext.allowed_root`。

- [x] **Step 1: 写 artifact symlink RED 测试**

根据测试 URL 计算现有 digest artifact 文件名，在 `allowed_root` 内预置同名 symlink 指向 root 外文件；fake response 返回已知 body。断言 WebFetch 返回 `WebFetch response save failed`，外部文件内容不变。当前 artifact 直接位于 root，不虚构不存在的中间目录测试；`_validate_path()` 既有 file-tool symlink ancestor 用例继续覆盖通用祖先解析。

再增加三个 mutation-sensitive 边界：mock `_validate_path()` 返回与默认 artifact 不同但仍在 root 内的 canonical target，断言只写该返回值；save-stage `Path.write_text()` 抛含敏感绝对路径的 plain `ValueError`，断言固定失败且不泄漏；fake response 成功而 URL fragment 含未配对 surrogate 时，digest 的 UTF-8 编码失败也收敛为同一固定结果。临时丢弃 validator 返回值、移除 `ValueError` 捕获或把 digest 留在 try 外都必须使对应测试 RED。

- [x] **Step 2: 运行 RED 测试**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_web_file_tools.py -q
```

预期：当前 `Path.write_text()` 跟随预置 symlink，外部目标被覆盖，新增断言 FAIL。

- [x] **Step 3: 写入前复用 canonical path guard**

response 读取成功后，把 digest/filename 推导、`_validate_path(filename, ctx.allowed_root)` 和返回 canonical `Path` 的写入放入同一 artifact failure boundary。`PermissionError`、digest/path/write `ValueError` 和 write `OSError` 都收敛为既有 `WebFetch response save failed`；不得用 `surrogatepass` 接受畸形 URL，也不得引入新 helper、随机文件名或平台专用 fd API。

- [x] **Step 4: 运行 WebFetch/File 回归并提交**

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
- Produces: `_apply_declared_status(..., allow_completed: bool)`；资格参数只门控显式 `completed: true`，不改变 `completed: false` 的既有 `refused`/`need_info`/`failed` 映射。
- Consumes: `ParseResult.tool_calls/errors`、现有 Termination 和 feedback loop。

- [x] **Step 1: 写工具成功、失败和 parse error RED 测试**

每个测试用两条或三条 MockClient response：第一条携带 `completed: true` 与工具/错误，最后一条是独立完成。断言第一轮 `completed=False`、有 outcome/parse error，最终轮才 `Termination.COMPLETED`。另写 max_rounds=1 断言不伪造完成，并覆盖 `completed: false` 的 `refused`、`need_info`、`failed` 即使伴随工具/parse error 也保持现有终态。

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

覆盖 omitted required=False、required+disabled 不阻断、optional timeout 降级、required unavailable 后有界 close 且 exit 2/no task start、正常 close 释放已启动资源、hard-stuck required CLI cleanup 保留证据/脱敏 warning且排队 shutdown work 在 loop 恢复后创建或复用唯一 drain，以及直接持有 manager 引用时的后续 bounded close retry；已有至少一个 enabled server/manager 时 REPL enable/disable required 不退出。全 disabled 配置的真实 CLI 组装在调用 `MCPManager` 构造器前返回 `None`。运行期 enable 测试不得用 fake manager 暗示 manager-less REPL 支持；构造器 spy 必须证明 manager 和 loop 都未创建。

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

- [x] **Step 1: Add shutdown RED matrix before changing close behavior**

Add/retain tests for normal close, holder ignoring stop until cancel, delayed async context cleanup, loop thread hard-stuck, internal shutdown exception, repeated close after a canceled facade, repeated close after cleanup completion, result preservation, warning sanitization, and exact `(name, generation, task, stop)` snapshot. Add targeted RED cases for: dead thread with empty maps but unproven completion/pending facade; shutdown facade submission rejection with an alive loop, apparently empty maps and pending loop work leaves completion unset and evidence retained; close injected between the first holder barrier check and `create_task()` return is atomically ordered so it leaves either no generation/task or one fully tracked slot with done-finalizer registered; lifecycle `cancel()` ordinary failure must not kill the authoritative drain; mismatched holder/session/state generations must not call SDK; current call failure sets teardown generation and after finalization does not create replacement without explicit enable; timed-out disable overlaps close before holder release; holder stop signal is observed before lifecycle cancellation; drain completion during join is consumed by the same close; startup rollback with a stopped worker and failing `loop.close()` retains stopped-loop evidence for a later close retry; startup cleanup `CancelledError` preserves the primary startup error; CLI startup/required-failure cleanup logs the fixed type of non-control `BaseException` without replacing the primary. Parameterize lifecycle `_submit`, startup rollback, and shutdown facade ordinary-primary/control-cleanup reverse combinations plus control-primary/secondary-cleanup combinations: caller paths propagate the first process-control identity while continuing bounded cleanup. A real `run_forever()` thread test must inject process control from both lifecycle operation body and owned-operation task-creation cleanup, prove it crosses the facade as a private value, is re-raised only on the caller thread, leaves the loop usable, and emits no thread/unretrieved-task warning. Separate real-loop tests inject process control into explicit holder allocation, done-finalizer replacement startup and current-generation SDK `call_tool`, proving those loop-local paths become fixed unavailable/structured failure with exact teardown, no partial slot/restart loop, exception text, thread death or warning; `CancelledError` remains cancellation. Use PID files for real fixture process assertions and distinguish graceful-stop and cancel markers. Confirm the focused matrix fails against the existing shutdown implementation without loosening the two preserved regressions.

- [x] **Step 2: Add shutdown state and exact loop snapshot ownership**

Add `_closing`, `_lifecycle_tasks`, `_shutdown_task`, `_shutdown_retry`, exact holder/lifecycle snapshots, `_shutdown_complete`, and the configured budgets. The first loop-owned shutdown entry sets `_closing` and snapshots every current `(name, generation, task, stop)` plus lifecycle operation before its first await. Every queued reconcile and every iteration that can call `_start_holder()` rechecks `_closed`/`_closing` before allocating a generation. Add one internal `threading.Lock` held only across caller-thread first-close publication and loop-thread holder allocation plus lifecycle-operation task/operation-set/finalizer publication or removal sequences. It must never cover an await or SDK operation. Close-first leaves generation unchanged and creates no operation task; start-first leaves a complete tracked holder or operation registration visible to the later loop shutdown snapshot. The authoritative lifecycle snapshot remains loop-owned and takes the same lock. A call wrapper verifies session generation against both `state.generation` and the current holder slot; active-generation call failure sets `tearing_down_generation` before signalling stop. Main-thread fallback stores only server names for diagnostics; it never copies or mutates live holder/session containers.

- [x] **Step 3: Implement shielded authoritative drain**

The loop-owned task signals exact snapshot stop events before any potentially blocking lifecycle cleanup, then cancels snapshot lifecycle operations and exact pending holders, and waits gracefully using `_remaining(deadline, reserve=thread_join_timeout)`. Tests record this order, not merely eventual events. Every stop/cancel/result/finalizer operation isolates ordinary `Exception`; a lifecycle task whose `cancel()` fails cannot terminate the sole drain or prevent retry. No unbounded lifecycle gather may prevent holder stop/cancel or make the retry event unreachable. Async context finalizers may continue past the public deadline. The drain invokes the same idempotent generation finalizer after `asyncio.wait()` because done callbacks are not ordered before wait return. Ordinary holder/finalizer exceptions are collected by type; the task does not stop the loop or set completion until all snapshot tasks are done, exact holder/session cleanup holds, and `_lifecycle_tasks` is empty. If an invariant remains false, the same task waits on `_shutdown_retry` without busy looping; repeated close signals that event with a new deadline and never creates a second task or snapshot.

- [x] **Step 4: Implement absolute-deadline public close and delayed retry**

First `close()` acquires the lifecycle barrier to set `_closed=True`, creates `deadline = monotonic() + shutdown_timeout + thread_join_timeout`, submits `_wait_for_shutdown()` and shields the authoritative task. Timeout/cancel of the concurrent facade cancels only the facade and retains the future for diagnostics. Facade submission failure closes its coroutine and requests the same loop-owned drain but never sets completion from caller-thread observations of empty containers. Repeated close signals the existing retry event, waits on the thread-safe `_shutdown_complete` event for the remaining shutdown budget, then performs bounded `thread.join()`. Only when completion and thread stop are both proven may the main thread attempt to close the loop, and it clears future/task/holder/session/lifecycle/loop/thread refs only after loop closure succeeds. An ordinary loop-close failure, including startup rollback after a stopped worker, is recorded and retains stopped-loop evidence for repeated retry. A dead thread with unproven completion remains incomplete even when holder/session/lifecycle maps are empty or `_shutdown_task` is absent/done; `close()` cannot synthesize `_shutdown_complete` from those containers. After join, re-read `_shutdown_complete` so completion during join is cleared in the same close. A live or cleanup-incomplete thread keeps all refs and receives a fixed warning containing thread identity, sanitized pending names and timeout, never args/env/content. Caller-thread cleanup uses one process-control precedence rule per synchronous `close()` invocation: preserve that invocation's first `KeyboardInterrupt`/`SystemExit` object over later cleanup controls or ordinary errors, continue every bounded cleanup site, and never let ordinary cleanup replace primary; once delivered to the caller, the control object is not persisted for a later `close()` call. Background holder BaseException remains fixed server-unavailable isolation so an SDK anomaly cannot kill the loop thread. CLI `/mcp enable|disable` catches facade `TimeoutError`, prints a fixed pending status and keeps the REPL alive. Wall-clock assertions use a narrow scheduling allowance, while fake future/thread tests assert the exact facade/join timeout arguments derived from the single deadline.

- [x] **Step 5: Run full MCP/CLI, fixture PID and static validation**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_mcp_manager.py tests/test_cli.py tests/test_tools.py -q -W error::RuntimeWarning
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest -q -ra
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run ruff check src tests
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run ruff format --check \
  src/forgeagent/mcp_manager.py src/forgeagent/cli.py \
  tests/test_mcp_manager.py tests/test_cli.py tests/mcp_fixture_server.py
```

Expected: all MCP shutdown/startup/generation tests pass, fixture PIDs disappear on normal and holder-stuck paths, hard-stuck retains only documented residual refs/warning, full pytest has no new failures or warnings, repository-wide lint passes, and every Task 6-owned Python file is formatted. Unchanged repository-wide format debt is diagnosed at the final base-ref-aware gate instead of being silently pulled into this task.

- [x] **Step 6: Commit the complete MCP lifecycle implementation**

```bash
git add src/forgeagent/mcp_manager.py src/forgeagent/cli.py tests/test_mcp_manager.py tests/test_cli.py tests/mcp_fixture_server.py
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
- Consumes: MockClient/real ModelClient、Task/CLI entrypoints、独立临时目录；offline entry 在配置敏感 import 前安装的临时 HOME/USERPROFILE/XDG_CONFIG_HOME。

- [x] **Step 1: 写 manifest 和报告 RED 测试**

测试固定 20 ID、唯一性、精确 5 real callable、未知/重复 ID preflight exit 2、两项 fake suite 的 0/1 exit、JSON/Markdown 同一 summary、preflight 不写报告、原子覆盖、单个 fake scenario 分别返回 `Path`、tuple、非字符串 mapping key、NaN/Infinity 以及 `IntEnum` 或自定义内建类型子类 evidence 时只将该项记为固定失败且不强制转换并继续生成有效报告，以及含 `/`、`..`、Unicode/标点和规范化碰撞的 model id 始终映射到 root 内不同目录。另以 standalone 子进程把 HOME/USERPROFILE 指向含恶意 `.forgeagent/mcp.yaml` 的目录，断言 offline runner 在 manifest/cases/CLI/MCP 等配置敏感 import 前切换到自己的临时 home，20 项不读取该文件；再直接调用 `main()`，覆盖正常和失败 cleanup，断言 HOME/USERPROFILE/XDG_CONFIG_HOME 恢复原值或 unset 状态，并验证 embedded `main()` 显式把临时 HOME 派生的 `user_path` 传给 `load_mcp_config`，即使 `mcp_manager` 预先导入也不使用旧 bound default。

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_golden_runner.py -q
```

预期：`tests.golden` 模块不存在导致 collection ERROR。

- [x] **Step 2: 定义类型化 manifest 接口**

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

- [x] **Step 3: 实现 runner preflight 和结果模型**

`tests/golden/__init__.py` 保持无副作用；`runner.py` module top-level 只导入标准库，并以 `TYPE_CHECKING` 保留类型。offline `main()` 先解析参数，创建临时 home，临时设置 HOME、USERPROFILE、XDG_CONFIG_HOME，再 local-import manifest/cases 及可能读取配置的 CLI/MCP/model 模块；suite 和报告完成后恢复环境。该临时 home 分支不得包住 `--real-model`：real opt-in 保留调用者原始 HOME/USERPROFILE/XDG_CONFIG_HOME，再 local-import 并读取用户模型配置与凭证环境；同时不得为 offline 路径提前 import 配置敏感模块。

`validate_manifest()` 比较精确 core frozenset、数量和 real set，并读取 `docs/golden-tasks-seed.md`，使用行首 heading/table 正则证明每个 core ID 有定义；core manifest 的重复、缺失、额外或替换 ID 均失败并抛 `GoldenPreflightError`。完整 catalog 的唯一 `G01` 至 `G380`、core 20 项和 non-core 360 项由 `tests/test_golden_runner.py` 的文档一致性 parser 独立校验：G01-G30 来自任务 heading，G31-G380 来自候选定义表；覆盖矩阵中的重复引用不计为定义。

`run_suite()` 对每项使用 `TemporaryDirectory`，捕获 `GoldenCheckError` 和 Exception 为失败结果但继续执行。成功 evidence 在加入 suite result 前用一个局部递归函数按精确内建类型（`type(value) is ...`）只接受 `None`/bool/str/int/finite float/list/`dict[str, value]`，明确拒绝 tuple、非字符串 key、自定义对象和内建类型子类，再用 `json.dumps(..., allow_nan=False)` 做最终编码检查；验证失败按固定 detail 和空 evidence 记录该项失败，不包含对象 repr。preflight 在输出目录创建前完成。

- [x] **Step 4: 实现同源报告和 exit code**

JSON schema 固定 `forgeagent.golden.v1`；Markdown 从同一个 suite result 渲染。每个文件先写同目录临时文件，再 `os.replace()`。默认目录为 `artifacts/golden/offline` 或 `artifacts/golden/real/<sanitized-model>`；`sanitized-model` 按 Design Doc 固定为 48 字符上限的 ASCII slug 加原始 model id SHA-256 前 8 位，不得直接拼接原始 ID。并发调用要求不同 `--output-dir`。

- [x] **Step 5: 运行 runner 合约测试并提交**

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

- [x] **Step 1: 把现有 G01/G05/G13 迁移为共享 case**

case 必须创建自己的输入，执行 Task，并显式检查：G01 sum=60/mean=20 且 JSON 值为内建数值类型；G05 除 state=42/output=50 与 side effect 恰好一次外，使用 tests-only RestrictedBackend wrapper 在第二块执行前包装 `utils.get_state` 返回值，以不可由模型预知的 marker 记录读取 key/value、use 和派生结果进入 stdout sink；随后在独立临时 allowed root 内以不可预知的替代 state 因果重放同一第二块，要求输出及 sink 精确变为 `alternate_state + 8`。recorder 只存在于 wrapper closure，不进入模型代码 globals；一次无用 `get_state()`、数值转换、加法、条件分支或直接 recorder 伪造后硬编码 50 都必须失败，wrapper/marker/替代 state 不进入 `src/`、原 workdir 或持久 state；G13 failed tool 与 successful tool 轮都携带提前 completed，失败反馈必须出现在第二次 client 请求中，最终第三轮独立完成。

- [x] **Step 2: 实现其余 7 项通用 offline case**

逐项判定固定为：G03 将嵌套 JSON 按指定映射生成扁平 CSV，并精确核对列名、行数、顺序与每格内容；G08 先通过 RestrictedBackend 证明给定测试 FAIL、修复后 PASS及断言完成见证，复用受限环境和 timeout，并比较测试文件 hash 保持不变；G11 合并去重后的行数、主键集合、排序和每行内容精确匹配；G15 证明调用精确小粒度 old/new 的 Edit、版本号 +1、旧版本仍在历史、仅目标位置有 diff、目标值正确且新版本 AST 可解析；G17 inner join 后列集合、行数和每行字段值匹配；G27 证明给定测试从 FAIL 到 PASS且修复通过精确小粒度 Edit 产生版本链，最终成功 Exec 绑定目标块，不接受整块替换；G43 Top-N 词和内建整数计数精确匹配。

所有 check 使用显式 helper：

```python
def require(condition: bool, message: str) -> None:
    if not condition:
        raise GoldenCheckError(message)
```

- [x] **Step 3: 实现 5 项 real callable**

real callable 与 offline 使用同一 fixture 和 judge，只替换 client。`runner --real-model` 保留调用者 HOME/USERPROFILE/XDG_CONFIG_HOME，并在配置模块尚未被 offline 临时 home 分支导入的前提下调用现有 `build_real_client(model_id)`；模型解析或本地必需凭证缺失转 preflight exit 2 且不创建报告。增加一个注入用户自定义 model/config 的回归，证明 real preflight 能解析该模型且三个环境变量未被替换。不得为验证凭证有效性额外发送探测请求；供应商拒绝凭证属于真实场景的运行期失败，写入完整报告并退出 1。

- [x] **Step 4: 让旧回放测试调用共享 case**

`tests/test_mock_replay_e2e.py` 不再复制脚本，按 ID 从 manifest 取 offline callable，在 `tmp_path` 或 case 自身目录执行，断言不抛 `GoldenCheckError`。

- [x] **Step 5: 运行 10 项通用核心**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-golden-common
```

在 Task 9 完成前 runner 会报告未实现边界 case；本步骤另用 pytest 选择通用 ID，预期 10/10 PASS：

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_mock_replay_e2e.py tests/test_golden_runner.py -q
```

- [x] **Step 6: 提交通用黄金任务**

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

- [x] **Step 1: 实现 sandbox/project-root 五项判定**

G06 restricted 越权返回结构化失败且未读取目标；G14 timeout 轮失败后后续任务仍成功；G58 项目外读被 audit hook 拦截；G59 项目外写未生成文件；G324 FileWrite 越界返回固定 `FileWrite path is outside project root` 且目标不存在。G59/G324 的 out-of-root targets 必须像 G06/G58 一样来自唯一 `TemporaryDirectory` outside-root fixture，并在正常和 GoldenCheckError 路径清理；不得依赖 `workdir.parent` 中的 fixed sibling filename，stale sibling 不应影响判定。

- [x] **Step 2: 实现 SSRF/确认四项判定**

G329 通过 confirmed `WebFetchTool` 调用 private/metadata literal，精确断言 `WebFetch blocked by network policy` 且 guarded connector 计数为 0；不再断言底层 guard exception 文本。G330 使用 resolver/redirect/connection doubles 构造 public first hop → private second hop，第二跳在连接前拒绝且不绑定本地端口。G332 无 confirmer 时精确断言 `rejected: no interactive confirmation channel available` 和 fake network 计数为 0；true confirmer 对同一 URL 使用 fake public response成功，禁止真实 socket。G333 false confirmer 不写文件但后续 Exec 可在 allowed_root 内写入，证明确认门不是文件安全边界。

- [x] **Step 3: 实现 MCP G355 产品级冒烟**

使用一个可用 fixture server 和一个 optional 失败 server。通过真实 `_handle_mcp_slash("/mcp", manager, console)` 用户路径判定状态输出同时包含 available/unavailable，工具描述只含可用 server；不能只直接读取 `manager.server_status()`/`list_tools()` 绕过 CLI。manager 在 case finally 中 close 且 PID 消失。required/absolute deadline 的故障矩阵继续由 Task 5/6 单测承担。

- [x] **Step 4: 运行完整离线 runner**

先在 `tests/test_golden_runner.py` 增加一条不 monkeypatch manifest/case 的基础 CI 集成测试：以独立 `tmp_path` output 调用 offline `main()`，断言 exit 0、20/20、JSON/Markdown summary 同源且没有真实网络/Docker/凭证依赖。该测试必须被普通全量 `pytest` 自动收集，不能只保留下面的手工命令。

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run python -m tests.golden.runner
```

预期：进程退出 0；`artifacts/golden/offline/results.json` 和 `report.md` 均报告 total=20、passed=20、failed=0、pass_rate=100.0。

- [x] **Step 5: 验证失败与 real preflight**

pytest 注入一个 failing scenario，断言仍运行后续项、退出 1、报告含失败 ID。以不存在模型运行：

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run python -m tests.golden.runner --real-model nonexistent-model
```

预期：退出 2，real 输出目录下不存在通过率报告。

- [x] **Step 6: 提交边界黄金任务**

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
- Modify: `openspec/changes/hardening-core-correctness/.comet/subagent-progress.md`

**Interfaces:**
- Produces: 与运行时和验证证据一致的公开契约；`[SECURITY][BREAKING]` 环境代理说明；20/360/5 黄金口径；`ACTION_PLAN.md` 中明确的 M13 加固行。
- Consumes: 最终测试命令、黄金 JSON/Markdown、现有 M11/M12 用户规划。

- [x] **Step 1: 更新模型与文本协议契约**

`model-client-contract.md` 准确记录 complete/stream 和 TextItem/ImageItem；`text-protocol-spec.md` 增加 WebFetch/FileRead/FileWrite/FileList/MCP，并写明工具/parse error 轮次不能完成。

- [x] **Step 2: 更新安全与 MCP 文档**

`threat-model.md` 写入以下已批准边界：

- `ProxyHandler({})` 禁用大小写环境代理，`NO_PROXY` 不能重新启用代理；HTTP(S) redirect 最多 10 跳且每跳重新校验。
- 未来显式代理只能选择 trusted-forward-proxy 或 guarded-tunnel trust model，本 change 不实现 `network.proxy`。
- `realpath + commonpath` 阻止静态 symlink alias escape，但主进程 File 工具在所有 tier 都仍有 canonical target/ancestor component 的 pathname TOCTOU；restricted audit hook 也有同类 check-to-operation race，container 不能防御宿主或 MCP 并发替换。
- fixed outcome message 主动牺牲底层诊断文本，避免 URL、hostname 和宿主路径回流到 Step/CLI。
- event-loop thread 完全卡死时 MCP transport、FD 或 child process 可能暂留；CLI 按 deadline 返回、保留引用并输出 `shutdown incomplete; resources may remain`，不声称能强杀 Python thread。

README 的 release-facing compatibility note 必须使用 `[SECURITY][BREAKING]`，明确依赖企业环境代理且不具备 direct egress 的部署会直连失败，且不得建议用 `NO_PROXY` 或恢复环境 `ProxyHandler` 规避。只列三条可操作迁移路径：允许 ForgeAgent 进程 direct egress；由外部可信进程预取到 `allowed_root` 后用 FileRead；改用用户显式信任的 MCP fetch 工具。README 文档一致性测试必须正向断言此标签、`NO_PROXY` 不可恢复和这三条路径均存在。

README 同时删除“裸 `models`/`reload`/`mcp ...` 仍可用”的过期说明，明确 REPL 内嵌命令必须带 `/`；保留并区分顶层 `forgeagent models` 子命令。

`docs/m10-usage-observability-and-tools.md` 同步 direct-only WebFetch、固定 WebFetch/FileRead/FileWrite/FileList outcome、WebFetch artifact canonical containment、静态 symlink 阻断和 target/ancestor-component swap residual；`docs/m7-tools-mcp-survey.md` 加入 `required`、optional degrade、absolute deadline、固定 thread 诊断和 incomplete-shutdown residual。TTY/non-TTY、autoApprove 和不抓取线程堆栈的理由也写入对应边界说明。

- [x] **Step 3: 重写黄金验证口径**

`golden-tasks-seed.md` 增加可信核心区块，列出精确 20 ID、5 real ID 和 runner 命令；验证 catalog 只含唯一的 `G01` 至 `G380`，并明确其余精确 360 个是 non-core candidate。README 展示离线命令、报告路径、exit 0/1/2 和 real opt-in。

- [x] **Step 4: 将加固范围登记为 ACTION_PLAN M13**

开始前把当前工作树文件原样复制为 `/tmp/forgeagent-action-plan-user-before.md`。从该副本再生成 `/tmp/forgeagent-action-plan-expected-after.md`，只把现有空置 M13 行替换为本 change 的交付物、Ruff/完整 pytest/20 项离线黄金核心/CodeGraph 复审验证和三次评审门禁；用同一个 `apply_patch` 对工作树 M13 行做完全相同的定向修改。随后用 `cmp /tmp/forgeagent-action-plan-expected-after.md ACTION_PLAN.md` 证明除 M13 外所有用户字节均未变化。保留用户 M11/M12 的内容与顺序，不修改或重编号它们。此步骤不创建里程碑文件、不更新 `milestones/latest`；`MILESTONE_GUIDE.md` 要求门禁全部通过后一次性产出收尾记录。

M11/M12、表格重排和空 M13 当前位于同一个未提交 hunk，不能先整体 `git add` 再反向应用旧 patch。从 `git show HEAD:ACTION_PLAN.md` 生成 `/tmp/forgeagent-action-plan-m13-only.md`，仅把 M10 后两个匿名 placeholder 中的第二个空交付物行替换为同一 M13 内容；第一个含 `HTTP` 的 placeholder 保持原样。将该临时文件写成 git blob，并用 `git update-index --cacheinfo 100644,<blob>,ACTION_PLAN.md` 只更新 index。`git diff --cached -- ACTION_PLAN.md` 必须只包含 M13，不能包含 M11/M12或表格重排。不得对工作树使用 restore/checkout，也不得整体暂存 `ACTION_PLAN.md`。

为支持会话/机器重启恢复，计算 `user_before_sha256`、`expected_after_sha256` 和 `m13_index_blob`，连同精确 M13 文本追加到 `openspec/changes/hardening-core-correctness/.comet/subagent-progress.md` 的 Task 10 preservation checkpoint。该 checkpoint 与 Task 10 文档一起提交。恢复时可从 `HEAD:ACTION_PLAN.md` 和 checkpoint 重新生成临时文件；不得依赖 `/tmp` 文件仍存在。提交前重新计算工作树 SHA-256 与 index blob并逐项匹配 checkpoint。

- [x] **Step 5: 运行文档一致性测试**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_golden_runner.py -q
rg -n "380.*validated|380.*已验证|complete\(\).*only|不支持.*stream|裸词命令.*仍可用" README.md docs ACTION_PLAN.md milestones
```

预期：黄金 ID 同步测试 PASS；rg 不再命中过时的“380 已验证”和旧客户端契约，或每个命中都属于明确的历史说明。

- [x] **Step 6: 提交文档同步**

```bash
git add README.md \
  docs/model-client-contract.md \
  docs/text-protocol-spec.md \
  docs/threat-model.md \
  docs/golden-tasks-seed.md \
  docs/m7-tools-mcp-survey.md \
  docs/m10-usage-observability-and-tools.md \
  openspec/changes/hardening-core-correctness/.comet/subagent-progress.md
action_plan_blob=$(git hash-object -w /tmp/forgeagent-action-plan-m13-only.md) # must equal checkpoint
git update-index --cacheinfo 100644,"$action_plan_blob",ACTION_PLAN.md
git diff --cached -- ACTION_PLAN.md
git commit -m "docs: align runtime contracts and golden validation"
```

### Task 10A: 收敛全方案复审发现

**Files:**
- Modify: `src/forgeagent/ssrf_guard.py`
- Modify: `src/forgeagent/model_registry.py`
- Modify: `src/forgeagent/_sandbox_worker.py`
- Modify: `src/forgeagent/tools.py`
- Modify: `src/forgeagent/web_search.py`
- Modify: `tests/test_ssrf_guard.py`
- Modify: `tests/test_model_registry.py`
- Modify: `tests/test_step.py`
- Modify: `tests/test_golden_runner.py`
- Modify: `tests/test_web_file_tools.py`
- Modify: `tests/test_web_search.py`
- Modify: Task 10 已列出的 runtime contract、Design Doc 和 OpenSpec delta files

**Interfaces:**
- Produces: 相对 redirect 兼容且最终 scheme 仍受限；YAML image capability 不丢失；完整 candidate catalog 和代理迁移文案有正向门禁；非完成终态优先级有 characterization evidence；WebFetch 字节元数据与实际 UTF-8 artifact 一致；非法 Unicode search query 不逃逸；runtime docs 不再删除或虚构当前契约。
- Consumes: Task 10 首轮技术一致性审查、当前实现源码、`G01..G380` 的 heading/table 混合文档结构。

- [x] **Step 1: 用 TDD 修复相对 redirect 与 image capability 透传**

先复现相对 `Location` 被空 scheme 错误拒绝，以及 `models.yaml` 的 `supports_images` 被 `ModelEntry` 静默丢弃；再做 `urljoin` 后 scheme 校验和字段原样透传。保留 max-10、逐跳 SSRF、六个内置 true、两个 false 和用户显式 false override 的回归。

- [x] **Step 2: 建立完整 candidate catalog 和代理迁移正向门禁**

文档一致性测试分别解析 G01-G30 heading 与 G31-G380 候选定义表，拒绝定义重复、缺失、额外和错号，并断言 non-core 恰好 360。README 测试正向锁定 `[SECURITY][BREAKING]`、`NO_PROXY` 无法恢复和三条迁移路径。

- [x] **Step 3: 锁定显式非完成终态并修正文档事实**

characterization tests 分别证明 `completed: false` 的 refused/need_info/failed 与工具或 parse error 同轮时保持既有终态；不改变 `completed: true` 的两阶段门控。威胁模型不得声称未实现的 package installer，也不得声称 restricted 设置了不存在的 file/process rlimit。

- [x] **Step 4: 恢复当前 runtime contracts 并校准 Design/OpenSpec**

模型、文本协议和威胁模型只恢复当前源码仍兑现的接口、解析、重试、信任边界与 T1-T11；required MCP hard-stuck CLI 只承诺排队 shutdown work 在 loop 恢复后创建或复用唯一 drain，不暴露不可达的 later-close handle，普通持有 manager 的调用方仍可重复 close；TOCTOU tier 边界、正式代理 Migration Plan 和 `G01..G380` 责任分工前后一致。

- [x] **Step 5: 收敛复审发现的消费端边缘行为**

用 TDD 证明 WebFetch 多字节文本的 `N bytes` 等于脱敏后实际落盘 UTF-8 字节数；证明 `/search` 对无法 URL 编码的未配对 surrogate 不发起请求、不抛异常并返回固定 unavailable。同步修正 M10 重定向 handler/opener 说明和 required MCP startup docstring，不引入通用 sanitizer、代理实现或新配置面。

- [x] **Step 6: 定向验证并完成最终 task review**

运行相关 Ruff、SSRF/Web、model registry/streaming、Step/Task、escape、golden runner 和 strict OpenSpec 验证；审查范围覆盖 Task 10/10A 全部提交，确认没有把历史草案恢复为当前契约。

### Task 11: 综合验证、CodeGraph 复审和任务收尾

**Files:**
- Modify: `openspec/changes/hardening-core-correctness/tasks.md`
- Modify: `openspec/changes/hardening-core-correctness/.comet/subagent-progress.md`
- Create: `milestones/milestone_013.md`
- Modify: `milestones/latest`
- Generated only: `artifacts/golden/offline/results.json`, `artifacts/golden/offline/report.md`

**Interfaces:**
- Produces: 45/45 tasks 勾选、实证里程碑、完整离线报告、与已验证实现 HEAD 精确关联且可进入 Comet verify 的提交状态。
- Consumes: 所有实现提交、OpenSpec specs、Design Doc、base ref。

- [ ] **Step 1: 运行静态检查**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run ruff check src tests
```

预期：`All checks passed!`。

然后以 plan header 的 `base-ref` 为边界列出本 change 新增或修改的 Python 文件，对该列表只运行 `ruff format --check`。若列表为空则跳过；验证步骤不得修改文件。若 changed-file format check 失败，派发单一 formatting fix worker，仅修复这些文件并提交，然后从本 Task Step 1 重新开始，不能沿用修复前的静态、测试、黄金或评审证据。不得为通过门禁而格式化未被本 change 修改的文件。

最后额外运行 `ruff format --check src tests` 作为全仓诊断。若失败，逐项与 `base-ref` diff 比对：本 change 改动文件的失败是阻塞项；仅存在于未改动文件的历史格式差异记录为 baseline debt，不扩大本 change。当前基线命令为：

```bash
git diff --name-only --diff-filter=ACMR 44456c57e2ef76990f44846eadb83bc8d5e25166 HEAD -- '*.py'
```

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
  tests/test_golden_runner.py -q -ra \
  -W error::RuntimeWarning \
  -W error::pytest.PytestUnraisableExceptionWarning
```

预期：全部可运行测试 PASS；环境能力 skip 带明确原因。

- [ ] **Step 3: 运行隔离全量测试**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest -q -ra \
  -W error::RuntimeWarning \
  -W error::pytest.PytestUnraisableExceptionWarning
```

预期：无人工 deselect；所有失败必须先按 systematic-debugging 修复，不能进入下一步。

- [ ] **Step 4: 运行 20 项离线黄金核心**

```bash
UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run python -m tests.golden.runner
```

预期：20/20、100.0%、退出 0；核对 JSON 与 Markdown summary 一致。没有显式模型和凭证时不运行 real 模式。

- [ ] **Step 5: 使用 CodeGraph 做最终调用面复审**

查询 `guarded_urlopen`, `make_console_confirmer`, `_apply_declared_status`, `MCPManager.connect/close`, `GoldenScenario` 的调用方。确认 WebFetch/search、run/REPL、Task/Step、MCP CLI 和测试入口均覆盖。若 CodeGraph 报 different-worktree/stale，记录警告及原因，并以当前 worktree 的直接源码、diff 和测试复核所有受影响文件；不把主 checkout 索引误当作当前实现，也不自行运行 `codegraph init`。

- [ ] **Step 6: 执行技术与代码两道独立评审门禁**

1. 技术方案一致性评审：逐项对照 `spec.md`、五份 delta spec、Design Doc、计划和实现，修复错误、遗漏或漂移，并重新运行 `openspec validate hardening-core-correctness --strict`。
2. 对抗性代码评审：用 plan `base-ref` 到当前候选 HEAD 的完整 review package 派发独立 whole-branch reviewer，覆盖正确性、安全、并发、资源生命周期和测试可信度；Critical/Important 发现必须由单一 fix worker 收敛并提交。这个 reviewer 同时满足 `review_mode: thorough` 的唯一 build-stage final whole-branch review，Task 11 checkoff 后不得再派发一个重复的 final code reviewer。任何源码、测试、规范或文档修复都会使本 Task 已有证据失效，必须从 Step 1 重新执行静态、专项、全量、黄金、CodeGraph 和本步骤两道评审，不能只重跑受影响测试。

首轮最终评审接受四个 Important：MCP discovery description/name 的已知 secret 可进入 prompt/CLI；真实 `connect()` 异常已清理后组装层重复执行完整 close；shutdown future `cancel()` 的 cleanup control 会跳过 retry/join；Design Doc 错把完整 G01-G380 universe 校验归给 production runner。修复必须用 TDD 锁定前三项，把 runner/pytest 职责同步到 Design/OpenSpec，并将此前 Ruff、专项、全量、golden、CodeGraph 与评审证据全部作废后从 Step 1 重跑。

第二轮最终评审在上述修复后接受两个相邻缺口：配置 server identity 本身含已知 secret 时仍会进入 catalog/status/CLI；shutdown wait 的 primary 已是控制异常且 future cancel 再抛控制异常时会跳过 drain retry。同步删除 Design Doc 中“重复 close 再次 cancel 已取消 facade”的矛盾表述。两项用 RED 回归锁定后做最小修复，且再次使此前综合证据和评审 verdict 全部失效，必须从 Step 1 重跑。

第三轮最终评审和协调者本地反馈路径复核共同确认，raw MCP identity 仍可经 `ToolOutcome.block_name/detail`、结构化 call error 和 lifecycle log 回流；简单 masked dict key 还会碰撞丢状态。全分支评审另发现 repeated close 与 `_stop_and_join()` 的 retry/wait/stop/join/state/loop-close 控制异常仍可能跳过后续 cleanup。修复升级为 manager-owned stable collision-free public label，并用独立 cleanup site + 首个 control 规则覆盖完整相邻矩阵；该修复再次使综合证据和评审 verdict 失效，仍须从 Step 1 重跑。

第四轮最终评审一致确认 `close()` 顶层 preflight `thread.is_alive()` 仍未进入 control accumulator；全分支评审另发现公开 `inputSchema` 原样保留 discovery secret。修复将首次/重复 close preflight 纳入同一首个-control 规则，并对 JSON-like schema 的字符串键/值递归脱敏，键碰撞或非 JSON-like 值降为空 schema。修复后再次从 Step 1 重跑，并只接受新的 reviewer verdict。

第五轮 final-fix 评审（implementation commit `2beca20`）确认并修复六个边界：生命周期 barrier 同时原子排序 holder allocation 与 lifecycle-operation registration/removal，覆盖 close-first 无 operation task、start-first 完整注册及 loop-owned first-close snapshot/completion；公开 MCP schema 的嵌套非有限 float 统一降为空对象；unknown/manual raw server identity 统一映射为 manager-owned、避开 configured public labels 的固定类别；重复 close 保留第一次 preflight control object，覆盖 retry ordinary/later controls 且继续 cleanup；WebFetch confirmation 的 hostname/path/query 未配对 surrogate 精确返回 ASCII `WebFetch <redacted malformed URL>`；embedded offline golden `main()` 显式传入临时 HOME 派生的 `user_path`。该轮再次使此前所有 comprehensive static/test/golden/CodeGraph/review evidence 与 verdict 全部失效，必须从 Step 1 重新执行并只接受本轮新证据。

第六轮 final-review fix wave（base candidate `c24622d`）接受五个边界：urllib 真实 shared 30x 管线会在 `_GuardedRedirectHandler.redirect_request()` 前用 stdlib scheme gate 拒绝 file，因此必须在 guard-owned `http_error_302`/301/303/307/308 中解析并分类；MCP confirmation 的 masked dict key 碰撞会覆盖 distinct top-level/nested arguments，必须使用 deterministic collision-free display labels；G59/G324 fixed sibling targets 会受 stale global filename 影响，必须改为 unique outside-root temporary directories并在所有路径清理；MCP close 的 first process-control identity 只在单次同步 `close()` cleanup chain 内优先，已交付 control 不跨后续 close 持久化或重抛；network/tool-approval/golden/MCP specs、Design Doc test matrix、tasks 与本 Step 6 必须同步。该轮再次使此前所有 comprehensive static/test/golden/CodeGraph/review evidence 与 verdict 全部失效，必须从 Step 1 重新执行并只接受本轮新证据。

- [ ] **Step 7: 固定已验证实现 HEAD，创建证据草稿并执行第三道验收评审**

Step 1-6（包含前两道评审）通过后，立即把 `git rev-parse HEAD` 作为 `verified_head` 同时写入 `.comet/subagent-progress.md` 和 milestone 草稿；两个持久文件必须一致，后续命令每次重新读取而不依赖 shell 变量。里程碑必须标明这个精确 implementation HEAD，而不是之后的 evidence-only commit。按 `MILESTONE_GUIDE.md` 一次性创建 `milestones/milestone_013.md`，把实际命令、pass/skip 数、黄金通过率和前两道评审结论写入文件，并为第三道证据评审保留唯一、明确的 `pending` verdict/identity 槽位；将 `milestones/latest` 更新为唯一一行 `milestone_013.md`。M11/M12 仍是未完成规划；当前 `milestones/latest` 指向最后按时间完成的 `milestone_009.md`，因此 M13 的“前置里程碑”链接使用 `milestone_009.md`，正文同时说明 M9 是在 M10 后补做、M9/M10 均已完成及编号跳跃原因。逐条核对本计划末尾映射后，将 `tasks.md` 的 45 个 checkbox 定向改为 `[x]`；不能一次性盲目全选。同步更新 `.comet/subagent-progress.md`，记录最终任务、评审和验证证据，并保留同样的第三道评审 pending 槽位。

第三道验收证据评审在上述草稿全部存在后执行：由独立 reviewer 把 Ruff、专项 pytest、全量 pytest、20 项黄金 JSON/Markdown/exit code，以及 milestone/tasks/progress 中每个命令、计数、skip、commit、文档声明和 `verified_head` 逐项对照原始输出，禁止把旧输出或预期值当成实测结果。reviewer 通过时只允许把 milestone 与 progress 中预留的两个 pending 槽位改成自己的 verdict/identity，不得修改其他证据或产品文件；这样最终写入的第三道结论由 reviewer 自身产生，不需要第四次转录复核。只发现 evidence-only 转录错误时，reviewer 不填写通过槽位，由协调者修正证据文件并只重复本次证据评审；若发现源码、测试、规范或公开文档问题，则候选实现发生实质变化，必须从 Step 1 重新开始。未经该评审通过不得发布里程碑。

此 change 的预期工作树状态不是绝对 clean：允许且只允许保留 Task 10 开始前已有的 `ACTION_PLAN.md` 用户差异中除 M13 placeholder 外的内容。提交收尾前重新计算 `ACTION_PLAN.md` SHA-256 并与持久 checkpoint 的 `expected_after_sha256` 比较；`/tmp` 文件仍存在时再补充 `cmp`，但它不是唯一证据。除此之外不得有未提交文件。

- [ ] **Step 8: 提交验证收尾**

```bash
git add openspec/changes/hardening-core-correctness/tasks.md \
  openspec/changes/hardening-core-correctness/.comet/subagent-progress.md \
  milestones/milestone_013.md \
  milestones/latest
git commit -m "chore: record hardening verification evidence"
```

提交后从 milestone 与 progress 重新读取并比较 `verified_head`，运行 `git diff --check`、strict OpenSpec validation，并验证 `git diff --name-only "$verified_head"..HEAD` 只包含 `tasks.md`、`.comet/subagent-progress.md` 和 milestone evidence 文件。最终报告同时列出 `verified_head` 与 evidence-only final HEAD；因为最后提交已证明只含验收记录，不用重跑产品测试。

## OpenSpec Tasks Coverage Map

| OpenSpec tasks.md | Plan task |
| --- | --- |
| 1.1 | 2, 3, 4, 5, 6A-6C 的 RED 回归 |
| 1.2 | 1 |
| 1.3 | 1, 6C |
| 1.4 | 1 |
| 2.1-2.4 | 2, 10 |
| 2.5 | 10A |
| 3.1-3.3 | 3A |
| 3.4-3.5 | 4 |
| 3.6-3.7 | 3A, 3B, 3C |
| 3.8-3.9 | 3B, 3C |
| 3.10 | 3D |
| 3.11 | 3E |
| 3.12 | 10A |
| 4.1-4.3 | 5 |
| 4.4-4.6 | 6A, 6B, 6C |
| 5.1-5.5 | 7, 8, 9 |
| 5.6 | 10A |
| 6.1-6.4 | 10 |
| 6.5 | 10, 11 |
| 6.6-6.7 | 10A |
| 7.1-7.5 | 11 |

## Final Plan Self-Review

- Spec coverage: 五份 capability specs 和 tasks.md 45 项均在 coverage map 中有实施与验证任务。
- Type consistency: `GoldenScenario`, `GoldenEvidence`, `MCPStartupError`, `required_failures()`, `_GuardedRedirectHandler`, generation holder/session slots, `restart_after_generation` 和完成门控签名在生产者与消费者任务中一致。
- Scope: 未增加依赖、代理实现、通用策略层、并发 golden runner 或无关重构。
- Execution safety: 每个行为任务包含 RED、GREEN 和定向测试；共享 worktree 的提交边界竞态必须在 progress 中记录并由协调者按最终 diff 复核，不能把混合提交误报为独立提交；综合验证不使用人工 deselect。
