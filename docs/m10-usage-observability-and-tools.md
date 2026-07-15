# M10 设计草稿：用量可观测性 + WebFetch/File 工具生态 + SSRF Guard

> **Current runtime addendum (hardening):** This M10 design record is historical; the current network mode is direct-only. `guarded_urlopen()` uses `ProxyHandler({})`, so uppercase/lowercase environment proxies are disabled and `NO_PROXY` cannot restore them. It accepts HTTP(S) only, validates every address and redirect hop, connects to an already-vetted sockaddr, and permits at most 10 redirects. There is no `network.proxy` configuration. A future explicit proxy must be a trusted-forward-proxy or guarded-tunnel design.

> WebFetch and FileRead/FileWrite/FileList use fixed outcomes for sensitive failure paths, preventing URL, hostname, absolute-path, and underlying-exception disclosure in feedback. File containment uses canonical `realpath()` plus `commonpath()` and blocks static symlink escapes. It does not eliminate the residual pathname TOCTOU in which an external actor replaces the validated target or an ancestor component before open. WebFetch approval is a real `restricted`/`container` network boundary; FileWrite approval is UX only because Exec can already write under `allowed_root`.

> 状态：**已定稿**（全部裁决已完成，见 §五 已裁决事项 共 12 条；Phase 0 spike 已完成,记录见 §八；下一步是 §七 实施 Phase 划分）。
> 范围（ACTION_PLAN.md M10 行，2026-07-11 用户裁决跳过 M9 直接做）：(a) 用量/计费可观测性——CLI 状态栏、token 用量（input/output/cached）、多模态用量计数（images 现在做，声音/视频留后）；(b) golden 任务集随任务扩展；(c) 工具生态扩展——WebFetch + FileRead/FileWrite/FileList，SSRF 逐跳复检 + project-root 锁定，零新依赖；`restricted` 档下 WebFetch/FileWrite 必须过确认门，FileRead 可仅记录日志。
> 契约基准：不改 `text-protocol-spec.md` 的整体机制（新工具走已有 `_build_tool_call()` 共享校验路径，同 M7 MCP/Survey 的接入方式）；`model-client-contract.md` 的 `TokenUsage` 需扩展一个 `cached_tokens` 字段（新增可选字段，向后兼容，不是破坏性变更）。
> 参考来源：`resource/agent/` 没有对应物——它没有 SSRF 防护、没有 WebFetch/File 工具、没有用量状态栏（诚实声明：本里程碑两块都是本项目自己的设计，非借鉴）。SSRF Guard 的 hop-by-hop 复检机制、project-root 锁定的既有先例（`_sandbox_worker.py::_install_audit_hook` 与 `RestrictedBackend`/`ContainerBackend` 的 `allowed_root`）、确认门机制的既有先例（M7 `MCPTool.run()` 的 confirmer 模式）均来自本项目自身既有代码。

## 一、结论先行

M10 是两条正交增量，共享同一个落点（`ToolRegistry`/`Tool` 体系）：

1. **用量可观测性**：`TokenUsage` 加 `cached_tokens: int = 0`，两个 client 的 `_parse_response` 各加一行映射（Anthropic 的 `cache_creation_input_tokens + cache_read_input_tokens`；OpenAI 兼容的 `prompt_tokens_details.cached_tokens`）；`RoundResult`/`TaskOutcome` 各加一个跨轮/跨任务的用量累加字段；CLI 用 `rich.status.Status` 在 REPL 每轮结束后刷新一行状态栏文字（不是常驻 `Live` 面板——REPL 是逐行 print 的同步循环，常驻 Live 会和已有的 `console.print` 输出打架，简单状态行更契合现有交互模型）。多模态用量本里程碑只做**计数**（模型返回的 image 用量数字原样累加），不做多模态**输入**（那是 M9 的范围，明确不动）。
2. **工具生态扩展**：新增 `WebFetchTool`/`FileReadTool`/`FileWriteTool`/`FileListTool` 四个 `Tool` 子类，注册进 `default_registry()`。核心安全机制两块：
   - **SSRF Guard**（WebFetch 专属，用户本次明确强调的重点）：已完成 Phase 0 级别的实测收敛（见 §八），结论是在 `_create_connection`（stdlib 留的实例级钩子）上做 IP 校验 + stdlib `urllib.request` 的重定向语义自动带来逐跳复检，零新依赖。**实测过程纠正了初稿一个致命 bug**——校验若放类级会被 `__init__` 的实例属性遮蔽、guard 从不运行（详见 §八.1），必须在 `__init__` 里覆写实例属性。
   - **project-root 锁定**（三个 File 工具共用）：与执行后端的 `allowed_root` 概念一致但架构独立实现——File 工具是主进程 `Tool`，不经过 executor 后端，需要自己的 realpath 前缀校验。
   - **确认门**：复用 M7 `MCPTool` 的确认门模式，把当前 MCP-only 的 `Confirmer` 类型泛化；`restricted`/`container` 档下 WebFetch 和 FileWrite 强制过确认门，FileRead/FileList 默认放行但记录日志（读比写风险低，且 T1 的 secret 保护已经在别处兜底——见 §四）。
   - **内容处理模型（评审拍板，替换掉一个被否决的方案）**：WebFetch 抓到的内容（尤其要翻译/摘要的网页）**不**引入任何"生成代码里直接调 LLM"的机制——曾评审一个 `agent_runtime.llm_infer()` 式方案（代码里 `subprocess` 出去调净化脚本、再 import 一个 LLM 句柄同步推理），因三点被否决：(1) 生成代码若 `subprocess.check_output` 出去，在 `restricted`/`container` 档会被审计钩子直接拒绝（`_sandbox_worker.py:39` 的 `PermissionError: restricted: process spawn denied`）；(2) 沙箱内回调 LLM 需要网络+凭据，而两者在 restricted 档都被主动切断（`socket.*` 全禁、`scrub_environment()` 已把密钥从子进程环境里抹掉），物理上做不到；(3) 更根本地，这违反本 Agent 的 code-as-action identity——LLM 是外层循环本身，不是能被沙箱代码同步调用的一个函数。**用户已拍板采纳的正确模型是既有的 Step 反馈环**：WebFetch 落盘（见 §3.4 的混合返回设计）→ 下一轮 LLM 生成 Exec 代码块读文件/抽文本 → 抽出的文本作为 feedback 回到对话 → LLM **在自己下一轮的输出里直接做翻译/摘要**（模型本来就在对话里，文本已经在它的上下文中，不需要额外调用）。翻译/摘要发生在 LLM 的认知层，不是代码调用；已知局限（大文档受 `max_rounds` 天花板约束，M10 不做 broker）已由用户拍板接受，记录见 §五"已裁决事项"。

两块加起来不改变现有架构形状：`Tool`/`ToolRegistry`/`ToolContext`/`_build_tool_call()` 都是原样复用的既有扩展点，M7 已经为"加新工具"铺好了路。

## 二、借鉴判定

无外部借鉴对象（见文档头）。本节改为记录**沿用哪些既有自家机制**：

| 既有机制 | M10 处置 | 理由 |
|---|---|---|
| `Tool` ABC + `ToolRegistry` + `_build_tool_call()` | **原样复用** | M7 已经把"加新工具"变成纯注册动作，WebFetch/File 四个工具走完全相同的路径，不改协议解析层 |
| `MCPTool.run()` 的确认门模式（autoApprove 检查 → confirmer 兜底 → 拒绝即结构化 outcome，从不静默执行） | **模式复用，类型泛化** | WebFetch/FileWrite 的确认逻辑与 MCP side-effecting 调用同构；`Confirmer` 类型需从 `Callable[[MCPArgs], bool]` 泛化为能接受多种 Args 的形式（§三.6） |
| `_sandbox_worker.py::_install_audit_hook` 的 realpath 白名单模式（`os.path.realpath(allowed_root)`，`rp == base or rp.startswith(base + os.sep)`） | **模式复用，架构独立实现** | File 工具是主进程 Tool、不经执行后端，无法复用 audit hook 本身（那是子进程 bootstrap 里装的），但校验谓词逐字复刻 |
| `secret_policy.mask_secrets()` | **复用于 WebFetch 返回内容与 FileRead 内容** | 防御深度——即便 WebFetch 抓到的页面或读到的文件恰好包含看起来像密钥的字符串，回显前仍按值掩码一次；FileWrite 写入内容不掩码（用户主动要求的写入内容，掩码反而破坏写入正确性） |
| `TokenUsage`（`input_tokens`/`output_tokens`） | **加字段，不改现有字段语义** | 新增 `cached_tokens: int = 0`，默认值保证现有测试/调用点零改动 |

## 三、架构设计

### 3.1 `TokenUsage` 扩展与 client 映射

```python
class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
```

映射点（各加一行，`_parse_response` 其余逻辑不变）：

- `anthropic_client.py`：`cached_tokens=(getattr(usage, "cache_creation_input_tokens", 0) or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0)`。两个字段都算"缓存相关"用量，合并成一个数字对状态栏展示足够，不需要区分写入缓存与读取缓存（细分留给以后真有计费对账需求时再拆）。
- `openai_compatible_client.py`：`cached_tokens=getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0`。`prompt_tokens_details` 本身可能是 `None`（部分网关不返回），双重 `getattr` 兜底。

多模态用量计数：Anthropic/OpenAI 的 usage payload 目前不总是带 image 计数字段（这取决于具体 API 版本），本里程碑**不在 `TokenUsage` 里加占位字段去猜一个可能不存在的形状**——留给 Phase 0 spike 实测两个 provider 的真实 usage payload 后再定字段名，避免像 `is_global` 那样先写了错的假设。若 spike 发现字段确实存在，加 `image_count: int = 0`；若发现两个 provider 形状不一致或字段不稳定，退而记录"暂不支持，等 provider 稳定后再做"，不强行拼一个不可靠的数字。

### 3.2 CLI 状态栏

用量的归属层级：`RoundResult` 加 `usage: TokenUsage | None = None`（每轮从 `AssistantMessage.usage` 直接搬过来），`TaskOutcome`/`TaskStatus` 层不加汇总字段——累加在 CLI 层做（状态栏是 CLI 关切，不该污染 Task/Step 的返回值模型）。`run_once`/`repl` 里维护一个跨轮（`run_once`）或跨整个 REPL session（`repl`）的 `TokenUsage` 累加器，每次 `Task.run()` 返回后把 `outcome.rounds` 里各轮的 `usage` 累加进去，然后 `console.print` 一行状态：

```
[dim]usage: in=1234 out=567 cached=89 (session total)[/dim]
```

用 `rich.status.Status`（`console.status(...)` 的简单文字状态）而不是 `rich.live.Live` 常驵面板——理由见 §一.1。状态行在每次 `run_once`/REPL 一轮任务完成后打印一次，不是逐 token 刷新（那需要 streaming，M9 范围，本里程碑不做）。

### 3.3 SSRF Guard（WebFetch 专属，重点收敛）

**结论（已通过 Phase 0 级实测验证，见 §八 完整记录）**：

```python
import http.client
import ipaddress
import socket
import urllib.request

_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")

class SSRFGuardError(Exception):
    """A candidate address for the target host is not allowed to be fetched."""

def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if this resolved address must not be connected to.

    `ip.is_global` already correctly excludes private/loopback/link-local/reserved/
    unspecified — VERIFIED against a full matrix (10/172.16/192.168, 127.0.0.1, 0.0.0.0,
    169.254.169.254 cloud-metadata, 100.64.0.0/10 CGN, 100.100.100.200 alt-metadata,
    ::1, fe80::1, fc00::1, plus the IPv4-mapped (::ffff:.../96) and 6to4 (2002::/16,
    via .sixtofour) forms of the above — ipaddress unwraps both automatically).

    Two things `is_global` does NOT catch, both confirmed by direct testing:
    1. Multicast (224.0.0.1, ff02::1) reports is_global=True. Must check is_multicast
       explicitly alongside is_global.
    2. NAT64 (64:ff9b::/96, RFC 6052) embeds an IPv4 address in the low 32 bits but
       ipaddress does NOT unwrap it (unlike 6to4's .sixtofour) -- 64:ff9b::7f00:1
       (embeds 127.0.0.1) reports is_global=True. Must unwrap and recheck by hand.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip in _NAT64_PREFIX:
        embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if _is_blocked(embedded):
            return True
    return (not ip.is_global) or ip.is_multicast

def _guarded_create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                               source_address=None):
    """Drop-in replacement for socket.create_connection: resolve `address` once,
    validate every resolved candidate, and connect only to a vetted sockaddr. It never
    re-resolves the hostname after validation — connecting to the exact sockaddr we
    checked closes the check-then-connect (TOCTOU) DNS-rebinding window."""
    host, port = address
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    vetted = []
    for family, socktype, proto, _canonname, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked(ip):
            raise SSRFGuardError(f"blocked non-public address {ip} for host {host!r}")
        vetted.append((family, socktype, proto, sockaddr))
    last_err: OSError | None = None
    for family, socktype, proto, sockaddr in vetted:
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_err = exc
            if sock is not None:
                sock.close()
    raise last_err if last_err else SSRFGuardError(f"no address resolved for host {host!r}")

class _GuardedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # MUST override here, not as a class attribute: HTTPConnection.__init__ assigns
        # self._create_connection = socket.create_connection as an INSTANCE attribute,
        # which shadows any class-level override (verified — see §八.1). Overriding after
        # super().__init__() is the only injection point that actually takes effect.
        self._create_connection = _guarded_create_connection

class _GuardedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _guarded_create_connection

class _GuardedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_GuardedHTTPConnection, req)

class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_GuardedHTTPSConnection, req)
```

**为什么校验点是 `_create_connection` 而不是 `connect()`**（评审修正，实测驱动）：初稿把校验放在覆写 `connect()` 里，这有两个问题——(1) `HTTPConnection.connect()` 除了建 socket 还设 `TCP_NODELAY`、处理 `_tunnel_host` 代理隧道,整段覆写会静默丢掉这些;(2) `HTTPSConnection.connect()` 还要做 TLS wrap + SNI,覆写它等于重写 TLS 握手,极易出错。正确的注入点是 stdlib 自己留的钩子 `self._create_connection`（http.client 源码注释原文："stored as an instance variable to allow unit tests to replace it"）——只换"建 socket"这一步,`TCP_NODELAY`/tunnel/TLS wrap 全部由未改动的基类 `connect()` 负责。**关键陷阱（实测发现,见 §八.1）**：它是 `__init__` 里赋的**实例属性**,类级 `_create_connection = staticmethod(...)` 会被实例属性遮蔽、根本不生效——初稿若照写会编译通过、`localhost` 测试还"看起来"被挡（其实是端口未开的 ConnectionRefused,不是 guard 拦的），上线一个**从不运行的 guard**。必须在 `super().__init__()` 之后覆写实例属性。

**逐跳复检与显式重定向策略的分工**：实测证明（§八.1）`urllib.request` 对重定向链的每一跳都会重新调用 `http_open()`/`https_open()` → `do_open()` → 新建 connection 实例 → 新实例的 `_create_connection`。用两个本地 `http.server.HTTPServer`（一个 302 到另一个,端口不同）实测到：一次 2 跳重定向触发了 2 次独立的 `_create_connection` 调用,每次带着**那一跳自己的** host/port。因此 SSRF 地址复检继续复用 stdlib 的逐跳建连路径；ForgeAgent 的 `_GuardedRedirectHandler` 只承担安全策略层工作：先把相对 `Location` 解析为最终 URL，再限制为 HTTP(S)，并显式执行最多 10 跳的计数。它不自行实现 HTTP 跳转或连接逻辑。

**DNS rebinding 防护**：`_guarded_create_connection` 在同一次 `getaddrinfo` 里把每个候选地址校验完就直接 `socket.connect(sockaddr)` 那个**已校验的 sockaddr**,不会再调用一次会重新解析域名的 `socket.create_connection(host, ...)`——避免"校验时解析到公网 IP,真正连接时（TOCTOU 窗口）DNS 记录已被换成私网 IP"的经典绕过。

**Opener 组装**：`urllib.request.build_opener(ProxyHandler({}), _GuardedRedirectHandler(), _GuardedHTTPHandler(), _GuardedHTTPSHandler())`,走标准 `opener.open(url, timeout=...)`。空 `ProxyHandler` 明确禁用大小写环境代理，`NO_PROXY` 不能重新启用代理；redirect handler 显式限制 10 跳并拒绝非 HTTP(S) 目标。**下载与上下文还有两道独立上限,各管一层,互不替代**：
- **下载上限**（防响应体把进程内存吃满，也是唯一的"要不要整份内容"的裁决点）：`WebFetchTool` 用 `response.read(MAX_FETCH_BYTES + 1)` 上限读取,超过 `MAX_FETCH_BYTES`（1MB,见 §五.6）直接截断,截断的整份内容仍然落盘（§3.4 混合返回设计），只是标注"内容已截断"。
- **上下文上限**（防 `ToolOutcome.detail` 把模型上下文灌爆）：`_render_feedback` 的**成功分支**（`step.py:332-333`）当前**不过** `_truncate_tail`（只有失败分支和 exec-stdout 分支过）。若 WebFetch 像早期草稿那样把整份 body 塞进 `detail`,1MB 的下载上限完全挡不住它把上下文灌爆。**这就是 §3.4 混合返回设计存在的原因**：`detail` 里只放一个小的 preview（截到 `PREVIEW_CHARS`,与 `_FEEDBACK_TAIL_LIMIT` 同量级,约 4KB）+ 落盘路径,不放整份内容——上下文上限从"事后补截"变成"设计上就不会超"，不需要再单独给 WebFetch 加一次自截逻辑。

### 3.4 `WebFetchTool`（评审改版：混合返回——落盘 + Preview）

**结论（用户已拍板）**：WebFetch 把完整响应体落盘到 `allowed_root` 下,同时在 `detail` 里返回一个小 preview + 落盘路径 + 元信息,**不**把整份内容塞进 `detail`。理由：(1) 未经处理的不可信 HTML 不整份进 LLM 上下文,注入面和 token 都省（§3.3 的上下文上限因此从"事后补截"变成"设计上就不会超"）；(2) 大页面天然 hold 得住,不受 `_FEEDBACK_TAIL_LIMIT` 量级限制；(3) 逼出"用代码处理文件"这一步,正好是 code-as-action 的自然形态——模型下一轮生成 Exec 代码块读文件、抽文本、`print()` 结果,抽出的文本才作为下一轮 feedback 回到对话（翻译/摘要则是**再下一轮 LLM 自己在输出里做**,不调用任何 `llm_infer` 式机制——完整推理见 §一.2）。小响应（如 JSON API）直接看 preview 通常就够,不必再让模型多走一轮读文件。

落盘路径**不引入任何强制子目录**（如 `output/raw/`、`output/text/`）——沿用 §3.5 已确立的**单一 `allowed_root` 原则**：File 工具和 WebFetch 共用同一个可达范围,不额外分裂出第二套目录心智。文件名由内容自身派生（URL 的 sha256 前 12 位 + 按 content-type 猜的扩展名),直接落在 `allowed_root` 根下,模型用 `FileRead`/`Exec` 照常读它,不需要知道任何特殊路径约定。

```python
import hashlib
from pathlib import Path

_EXT_BY_CONTENT_TYPE = {"text/html": ".html", "application/json": ".json", "text/plain": ".txt"}
PREVIEW_CHARS = 2048  # small enough to stay well under _FEEDBACK_TAIL_LIMIT alongside the path/meta line

class WebFetchArgs(BaseModel):
    url: str

class WebFetchTool(Tool):
    name = "WebFetch"
    args_model = WebFetchArgs

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, WebFetchArgs)
        if ctx.tier in ("restricted", "container"):
            if ctx.confirmer is None or not ctx.confirmer(args):
                return ToolOutcome(tool="WebFetch", success=False,
                                    detail=f"WebFetch {args.url} was not approved by the user")
        try:
            body, content_type = _guarded_fetch(args.url)  # opener.open + capped read
        except SSRFGuardError as exc:
            return ToolOutcome(tool="WebFetch", success=False, detail=str(exc))
        except OSError as exc:
            return ToolOutcome(tool="WebFetch", success=False, detail=f"fetch failed: {exc}")
        masked = mask_secrets(body, sensitive_env_values())
        digest = hashlib.sha256(args.url.encode()).hexdigest()[:12]
        ext = _EXT_BY_CONTENT_TYPE.get(content_type, ".fetch")
        dest = Path(ctx.allowed_root) / f"webfetch_{digest}{ext}"
        dest.write_text(masked, encoding="utf-8", errors="replace")
        preview = masked[:PREVIEW_CHARS]
        truncated_note = " (preview truncated)" if len(masked) > PREVIEW_CHARS else ""
        detail = (
            f"saved to {dest.name} ({len(masked.encode('utf-8'))} bytes, {content_type})\n"
            f"preview{truncated_note}:\n{preview}"
        )
        return ToolOutcome(tool="WebFetch", success=True, detail=detail)
```

只支持 `http`/`https` scheme（`urllib.request` 默认就只装了这两个 handler；显式拒绝 `file://`/`ftp://`/`data:` 等——`file://` 尤其危险,等于绕过 SSRF Guard 直接读本机文件，必须在 URL 解析阶段就拒绝，不能指望 opener 层面自然挡住）。

**HTML→文本预处理定性为可用性层,不是安全层（评审拍板）**：若后续要在 WebFetch 或模型生成的读取代码里剥 `<script>`/`<style>` 标签、抽纯文本,这一步的价值是**降噪 + 省 token**,不是防注入——真正会诱导模型的是**可见正文文字本身**（"忽略之前的指令……"）,剥 HTML 标签完全拦不住,那段文字正是要喂给模型的内容。真实的安全边界与 T5/T8c 同一套：外部内容在提示词层标注"数据非指令",即便模型被带偏,生成的代码仍被沙箱限死（T1-T3 后端层兜底）。所以 v1 **不需要**为了"安全"引入 HTML 净化;需要时可以用 stdlib `html.parser`（零新依赖,已确认可用）作为模型生成代码里的一个普通处理步骤,和净化不净化都不影响任何强制层——参见 §五"已裁决事项"。

### 3.5 `FileReadTool` / `FileWriteTool` / `FileListTool` + project-root 锁定

三个工具共用一个校验函数：

```python
def _validate_path(path: str, allowed_root: str) -> Path:
    """Resolve `path` (relative to allowed_root if not absolute) and require the
    realpath to be allowed_root itself or nested under it. Mirrors the predicate in
    _sandbox_worker.py::_install_audit_hook, but implemented independently here since
    File tools run in the main process, not inside the sandboxed executor."""
    base = os.path.realpath(allowed_root)
    candidate = path if os.path.isabs(path) else os.path.join(allowed_root, path)
    resolved = os.path.realpath(candidate)
    if resolved != base and not resolved.startswith(base + os.sep):
        raise PermissionError(f"path {path!r} escapes project root {allowed_root!r}")
    return Path(resolved)
```

`allowed_root` 从哪来：`ToolContext` 需要新增一个 `allowed_root: str` 字段（不是 `Path.cwd()` 内联算——要和执行后端的 `allowed_root` 保持同一个值，否则"文件工具能碰的范围"和"代码块执行能碰的范围"会不一致，造成认知负担）。`Task`/`Step` 组装 `ToolContext` 时把已经传给 `RestrictedBackend`/`ContainerBackend` 的同一个 `allowed_root` 值传进来（当前这两个 backend 各自默认 `Path.cwd()` resolved，M10 不改这个默认值，只是让 File 工具读取同一份配置）。

`FileWriteTool` 与 `restricted`/`container` 档下的确认门逻辑与 WebFetch 相同（写=有副作用）。`FileReadTool`/`FileListTool` 默认放行，仅在 `ctx.confirmer` 存在时记录一条日志行（`console.print` 一行 `[dim]FileRead: <path>[/dim]`，不阻塞执行）——读操作的风险已经由 project-root 锁定 + T1 既有的 `mask_secrets()`/`scrub_environment()` 兜底,不需要每次都打断用户。`trusted` 档下四个工具都不需要确认门（trusted 语义本来就是"用户显式选择无隔离,自担风险",见 threat-model 现有原则）。

**FileWrite 确认门的准确定性（评审修正,不要过度承诺）**：FileWrite 的确认门**不是安全边界,是 UX/知情门**——因为在 `restricted` 档下,模型完全可以用 Exec 跑一段 `open(path,"w").write(...)` 达到同样的写入效果,而 Exec 的写入只要落在 `allowed_root` 内就被 audit hook 放行、**不过 FileWrite 的确认门**。也就是说确认门拦得住"模型显式调 FileWrite",拦不住"模型改用 Exec 写文件"。所以它的价值是"把常见的写文件动作显式暴露给用户看一眼",不是"阻止一切越权写"（后者由两条真边界负责：project-root 锁定限定范围、执行后端的 audit hook 限定 Exec 写入范围,二者都是**所有档位无关确认门**都生效的应用层校验）。文档必须如实这么写,不能把它包装成安全控制。**WebFetch 的确认门则不同**:它是**真边界**——`restricted` 档下 Exec 根本联不了网（audit hook 默认禁 `socket.*`）,WebFetch 是唯一的出网通道,拦住它就真的拦住了出网。这个 WebFetch-vs-FileWrite 的不对称是 M10 安全模型的关键,§四 threat-model 增量里要讲清。

`FileReadTool` 返回内容同样经 `mask_secrets()` 过一遍。`FileWriteTool` 的写入内容不掩码（原因见 §二表格）。

### 3.6 `Confirmer` 类型泛化

当前：

```python
Confirmer = Callable[[MCPArgs], bool]
```

泛化为：

```python
Confirmer = Callable[[MCPArgs | WebFetchArgs | FileWriteArgs], bool]
```

`make_console_confirmer` 的实现不需要改分支逻辑——它已经是 `console.print(f"...{args}...")` 式的通用打印,`isinstance` 判断只在需要展示不同措辞时才需要（比如 WebFetch 显示 URL,MCP 显示 server:tool,FileWrite 显示路径）,这是一个纯展示层的小改动,不影响确认门语义。

### 3.7 `ToolContext` 增补

```python
@dataclass
class ToolContext:
    blocks: CodeBlockStore
    backend: ExecutorBackend
    runtime: Runtime
    analyzer: CodeAnalyzer
    asker: Asker | None = None
    mcp: MCPManager | None = None
    confirmer: Confirmer | None = None
    tier: Tier = "restricted"          # 新增：WebFetch/FileWrite 按档位决定是否强制确认门
    allowed_root: str = "."            # 新增：File 工具的 project-root 锁定基准
```

**循环导入陷阱（评审发现）**：`ToolContext.tier: Tier` 需要 `Tier` 类型,但 `Tier` 当前定义在 `task.py`,而 `task.py` 已经 `from .tools import Asker, Confirmer`——若 `tools.py` 反过来 `from .task import Tier` 就成环。**修法**：把 `Tier = Literal["trusted","restricted","container"]` 从 `task.py` **移到 `tools.py`**（它在依赖图里更底层,`task.py`/`cli.py` 都已经 import tools.py,方向天然正确）,`task.py`/`cli.py` 改成 `from .tools import Tier`。这是一处纯粹的定义位置迁移,不改类型本身,现有 `from .task import ... Tier` 的两个引用点（`cli.py:35`）同步改指向。

`Step.__init__`/`Task.__init__` 各加一个对应的构造参数,原样从调用方（`run_once`/`repl`）往下传,不改变现有参数的默认行为（新参数都给了向后兼容的默认值）。**注意 `allowed_root` 默认值的一致性**：`ToolContext.allowed_root` 写 `"."` 只是 dataclass 字段占位,实际组装时必须传**与执行后端同源**的值——即 `str(Path(allowed_root or Path.cwd()).resolve())`,和 `RestrictedBackend`/`ContainerBackend.__init__` 里那行完全一致,否则 File 工具和 Exec 的可达范围会漂移。Task 层应把这个 resolved 值算一次、同时喂给 backend 和 ToolContext。

## 四、threat-model 增量

新增三个威胁场景到 `docs/threat-model.md` 的映射表（T10a-T10c）：

| # | 威胁场景 | 缓解手段（落点） | 验收方向 |
|---|---|---|---|
| T10a | WebFetch 被诱导访问内网/云 metadata 服务（SSRF） | **【流程+应用层】**SSRF Guard：`_create_connection` 钩子上用 `socket.getaddrinfo` 解析 + 逐候选地址 `is_global`/`is_multicast`/NAT64-unwrap 校验（§3.3），拒绝后不再连接；直连已校验 sockaddr 防 DNS rebinding；`ProxyHandler({})` 禁用环境代理；stdlib 每跳重新建连并复检地址，`_GuardedRedirectHandler` 解析相对目标、限制 HTTP(S) 且最多 10 跳；`restricted`/`container` 档强制确认门 | 对 127.0.0.1/169.254.169.254/224.0.0.1/NAT64-wrapped 私网地址的 fetch 断言被拒；两跳重定向（第二跳指向内网）断言在第二跳被拒，不是第一跳放行后失控；第 11 跳和非 HTTP(S) 目标明确拒绝 |
| T10b | FileWrite 越权覆盖 project-root 外文件 | **【流程+应用层】**`_validate_path` realpath 前缀校验 + `restricted`/`container` 档强制确认门 | 尝试写 `../../etc/passwd` 风格路径断言被拒;写 project-root 内路径断言成功 |
| T10c | FileRead 读出 secret 后经工具返回内容外泄 | **【应用层】**project-root 锁定（读也限定范围）+ `mask_secrets()` 对返回内容按值掩码（同 T1 既有防御深度原则） | 读一个含伪造密钥字符串的文件,断言返回内容中真值被掩码 |

这三条与 T1-T9b 的分层原则一致：WebFetch/File 是主进程 `Tool`（同 T8a 的 MCP,不经 executor 后端隔离),所以强制点是**执行前的确认门**,不是后端沙箱——`restricted`/`container` 档选择只决定"是否强制确认门",不决定"SSRF Guard/project-root 锁定是否生效"（这两个应用层校验在**所有**档位下都跑,包括 `trusted`——SSRF Guard 挡的是网络目标本身的风险,与"这次执行信不信任"无关,`trusted` 档也不该被诱导打内网 metadata 服务；project-root 锁定同理，`trusted` 档的隔离豁免针对的是代码执行,不代表 WebFetch/File 工具也豁免）。

## 五、已裁决事项（用户已拍板，不再是开放问题）

以下 12 项均为用户明确拍板的方向：前 5 项针对评审中一个被否决的替代方案（"WebFetch + Script" / `agent_runtime.llm_infer`）讨论后拍板；后 7 项是原 §六"开放裁决"的全部条目,已在最新一轮裁决中逐条定案,原 §六 因此撤销,不再单独保留"开放裁决"章节。

1. **内容处理走 Step 反馈环，彻底废弃 `llm_infer`**：见 §一.2 已述——不引入任何"生成代码同步调用 LLM"的机制，翻译/摘要类任务由 LLM 自己在下一轮输出里完成，不是代码调用出来的。
2. **大文档翻译策略：接受 `max_rounds` 上限，M10 不做 Broker**：反馈环模型有天花板——翻译发生在 LLM 的轮次里，`max_rounds`（默认 10）限制了能分几块处理。超大文档（需要拆很多块才能处理完）在这个模型下可能触顶。用户已明确接受这个局限：M10 范围内不引入主进程 LLM broker 去打破这个天花板（那需要在沙箱里开一个能回调主进程 LLM 客户端的通道,threat-model 明确 v1 不做）,够用就行,未来真有超大文档场景再评估。
3. **WebFetch 返回形态：混合返回（落盘 + Preview）**：见 §3.4 改版——完整内容落盘,`detail` 只带小 preview + 路径 + 元信息。取代了"直接把整份 body 塞进 detail"的原设计，也取代了"Script 单独下载到固定目录"的被否决方案。
4. **HTML 净化/预处理定性为可用性层，不是安全层**：见 §3.4 末段——剥标签抽文本是省 token/降噪，不是防注入；真正的注入防线是 T5/T8c 那套"数据非指令"标注 + 后端沙箱兜底，与是否净化无关。因此 v1 不必为了"安全"引入任何 HTML 解析器（净化 bs4 的方案也随此否决——且 `bs4` 本身不是本项目依赖，引入会违反 M10 的"零新依赖"要求）；需要降噪时,模型生成的处理代码可以用 stdlib `html.parser`，属于普通处理步骤,不是安全组件。
5. **目录约定：单一 `allowed_root`，废除强制子目录**：不设 `output/raw/`/`output/text/` 这类固定子目录约定。WebFetch 落盘文件与 File 工具共用同一个 `allowed_root`，与 §3.5 的 project-root 锁定原则完全一致——"文件工具能碰的范围"只有一套配置，不分裂出第二套目录心智。
6. **WebFetch 下载/预览上限的具体数值：`MAX_FETCH_BYTES = 1_048_576`（1MB）、`PREVIEW_CHARS = 2048`**：1MB 是内存安全与实用性的平衡点,超限截断落盘并在 `detail` 里标注截断状态（如 `truncated: true`）,截断的整份内容仍然落盘（§3.4 混合返回)。2048 字符的 preview 足够模型判断内容类型（"这是 JSON"还是"这是 HTML"）,又不浪费 token。混合返回方案已经让 preview 天然小于 `_FEEDBACK_TAIL_LIMIT`,不再需要 §3.3 早先讨论的"WebFetch 自截"逻辑,这条随混合返回方案一并落地。
7. **多模态用量字段：Spike 优先,无则不加**：不在里程碑中预留"猜测的字段"。Phase 0 spike 必须实测 Anthropic/OpenAI 两个 provider 的真实 usage 结构体；若字段名不稳定或无标准形状,则 M10 不加任何多模态占位字段,observability 只记录确定的 `input_tokens`/`output_tokens`/`cached_tokens`（对应 §3.1 已述的 spike-then-decide 流程,此处正式过一次裁决）。
8. **File 工具不加独立的 `--allowed-root` CLI flag,复用隐式 `Path.cwd()`**：这是保持心智模型简单的关键——用户只需理解"Agent 只能看到和执行当前目录下的东西",避免 `restricted`/`container` 档位配置与 File 工具配置漂移成两套。一套 `allowed_root`（即 cwd）,贯彻到底（§3.7 已按此假设设计,不需要改动)。
9. **FileListTool 输出形式：返回相对路径,禁止绝对路径**：安全上减少信息泄露（不暴露宿主 `/home/user/...` 之类的目录结构）;一致性上,所有 File 工具操作均基于 `allowed_root` 的相对路径。即使模型试图列 `../`,后端仍按 `_validate_path`（§3.5）解析并拒绝越界,不会因为"只是列目录"而放宽。
10. **`WebFetchTool` v1 仅支持 GET,拒绝 POST/自定义 header**：安全铁律是"SSRF 防御的核心是只读"——POST 会把 SSRF 升级为对内网服务的有效写操作（如未授权 Redis 执行命令、内网 API 的 DELETE),现有 SSRF Guard 设计以"读"为前提,不覆盖这类风险；职责分离上,通用 HTTP 客户端（Method/Headers/Body 齐全）属于 MCP 范畴,WebFetch 定位是"查看网页内容",不是"调用 API";攻击面上,自定义 header 可用于 Host 头注入等手法攻击内网服务,GET 已足够满足"查看"需求。`WebFetchArgs`（§3.4）本就只有 `url` 一个字段,不接受 method/headers 参数,这个决定与当前设计天然一致,不需要额外改动。
11. **确认门日志详细程度：仅打印路径,不打印内容摘要**：隐私保护上防止敏感数据（私钥、PII）经日志泄露;最小权限上,确认门的作用是"确认操作"而非"审计内容",内容审计应由 observability 系统在脱敏后进行。§3.5 已述的 `[dim]FileRead: <path>[/dim]` 日志行本就只含路径,不含文件片段,与此决定一致。
12. **重定向次数上限：沿用 `urllib` 默认值（`max_redirections=10`、`max_repeats=4`),不额外收紧**：既然每跳都经过 SSRF Guard（IP 校验),重定向次数本身不构成安全漏洞,只是资源消耗边界;10 次对正常 CDN/短链场景足够,若被恶意利用,攻击者最多消耗 10 次连接资源,DoS 防护应在别处（如全局速率限制）解决,不必在此收紧到影响正常网站访问。

## 六、Phase 0 spike（已完成,记录见 §八）

按项目既有纪律,涉及网络/安全边界的机制在写实现代码前先用真实环境验证。本里程碑的 spike 已经在设计阶段完成（而非拖到 Phase 0 才做),原始过程记录见 §八：

- SSRF Guard 的注入点（实测发现类级覆写被 `__init__` 的实例属性遮蔽这一致命坑,确定正确注入点是 `__init__` 里覆写 `self._create_connection`)。
- 逐跳复检机制（两个本地 HTTP server 构造真实重定向链,实测 `_create_connection` 被逐跳调用、每跳带自己的目标)。
- IP 校验谓词的完整性（20+ 地址的矩阵测试,发现并修复了 `is_global` 遗漏 multicast、NAT64 未被自动 unwrap 两个真实缺口)。
- 端到端 opener 正确性（真实访问 `https://example.com/` 验证 HTTPS 的 TLS wrap/SNI 不因 `_create_connection` 覆写而破坏、放行路径正常)。

## 七、实施 Phase 划分

- **Phase 1**：`TokenUsage.cached_tokens` + 两个 client 的映射行 + 相关单测（`test_anthropic_client.py`/`test_openai_compatible_client.py` 各加断言)。
- **Phase 2**：SSRF Guard 模块（`ssrf_guard.py` 新文件,承载 §3.3 的全部函数/类)+ 独立单测（`test_ssrf_guard.py`：地址矩阵、NAT64/6to4/IPv4-mapped 解包、本地重定向链复检)。
- **Phase 3**：`WebFetchTool` + `Confirmer` 泛化 + `ToolContext.tier`/`allowed_root` 增补 + `WebFetchArgs` 协议注册（混合返回：落盘 + preview,见 §3.4；`MAX_FETCH_BYTES`/`PREVIEW_CHARS` 取 §五.6 定案数值)。
- **Phase 4**：`FileReadTool`/`FileWriteTool`/`FileListTool` + `_validate_path` + 各自 Args 协议注册（`FileListTool` 按 §五.9 只返回相对路径)。
- **Phase 5**：CLI 状态栏（`run_once`/`repl` 累加器 + 状态行打印)+ `RoundResult.usage` 字段（多模态字段按 §五.7 的 spike-then-decide 流程处理)。
- **Phase 6**：golden task 集扩展（按 §五.9/§五.10 定的范围写新任务,保持 40/25/20/10/5% 配比不变,四个新工具主要落在"文件/数据"与"网络/API"两类)。
- **Phase 7**：`README.md`/`docs/threat-model.md` T10a-T10c 收尾、`milestones/milestone_010.md`、`ACTION_PLAN.md`/`milestones/latest` 收尾。

## 八、Phase 0 spike 实测记录

### 8.1 注入点与逐跳复检——真实验证（含一个初稿会踩的坑）

**坑（初稿设计的致命 bug,实测才暴露）**：初稿把校验放在类级覆写 `connect()`,或（更隐蔽）用类级 `_create_connection = staticmethod(...)`。实测发现后者**根本不生效**——`HTTPConnection.__init__` 里有一行 `self._create_connection = socket.create_connection`,把它赋成**实例属性**,遮蔽掉任何类级同名属性。用这个错误写法跑 `opener.open("http://localhost:9/")` 时,报的是 stdlib `socket.py` 抛的 `ConnectionRefusedError`（端口 9 没开),**不是** `SSRFGuardError`——也就是 guard 从没运行,只是碰巧端口没开显得"像被挡了"。若目标端口恰好开着（如 `localhost:80`),这个写法会**放行连接**。这正是"未经实测的安全代码会带着一个从不运行的 guard 上线"的典型。**修法**（已实测通过）：在 `_GuardedHTTPConnection.__init__` 里 `super().__init__()` 之后覆写 `self._create_connection = _guarded_create_connection`。改后 `opener.open("http://localhost:80/")`/`http://127.0.0.1:80/`/`http://169.254.169.254/` 全部抛 `SSRFGuardError`（且 `localhost` 被正确解析到 `::1` 也一并挡住),`https://example.com/` 正常 200。

**逐跳复检**：用两个本地 `http.server.HTTPServer`（redir 端口返回 302 到 victim 端口,victim 返回 200),把 `_create_connection` 换成一个**放行但记录每次调用 (host,port)** 的插桩版本,`opener.open(redir)`。**实测结果：记录到 2 次调用**,分别是 redir 端口和 victim 端口——证实 `HTTPRedirectHandler` 每跳都重新触发 `http_open()` → `do_open()` → 新建 connection 实例 → 新实例的 `_create_connection`。因此校验点放在 `_create_connection`（每跳必经、每跳带自己的目标）,hop-by-hop 复检是 stdlib 自带行为:即使 hop-1 是公网、hop-2 被 302 指向私网,hop-2 那次 `_create_connection` 会用私网目标重跑校验、在建 TCP 连接前抛 `SSRFGuardError`。

### 8.2 IP 校验谓词——完整矩阵实测

对以下地址跑 `is_global`/`is_multicast`/`is_private`/`is_reserved`/`is_link_local`/`is_unspecified`/`is_loopback`：

`127.0.0.1`、`10.0.0.1`、`172.16.0.1`、`192.168.1.1`、`169.254.169.254`（云 metadata)、`0.0.0.0`、`100.64.0.1`（CGN)、`100.100.100.200`（部分云厂商 metadata 备用地址)、`224.0.0.1`（IPv4 多播)、`255.255.255.255`、`192.0.0.1`、`192.0.2.1`（TEST-NET)、`::1`、`fe80::1`、`fc00::1`、`ff02::1`（IPv6 多播)、`8.8.8.8`、`1.1.1.1`、`2001:4860:4860::8888`。

**发现 1**：`is_global` 单独使用对上述所有私网/环回/链路本地/CGN/metadata/reserved 地址都正确返回 `False`——除了 `224.0.0.1`/`ff02::1` 两个多播地址返回 `True`。修复：`blocked = (not is_global) or is_multicast`,补测同一矩阵全部通过（多播被挡,公网地址不受影响)。

**发现 2**（补测,针对地址嵌入形式)：`::ffff:127.0.0.1`（IPv4-mapped)与 `2002:7f00:0001::`（6to4,内嵌 127.0.0.1)都被 `is_global`/`is_private` **正确**判定为非公网——Python `ipaddress` 对这两种嵌入格式做了自动解包（`.ipv4_mapped`/`.sixtofour` 属性可验证解包出的正确地址)。但 `64:ff9b::7f00:1`（NAT64,RFC 6052,同样内嵌 127.0.0.1)**未被正确挡住**——报告 `is_global=True`,且 `ipaddress.IPv6Address` 没有对应的自动解包属性（`dir()` 枚举确认只有 `ipv4_mapped`/`sixtofour`,没有 NAT64 相关属性)。修复：手动检测地址是否落在 `64:ff9b::/96` 网段内,若是则取低 32 位还原成 IPv4 地址递归校验。修复后用 `64:ff9b::7f00:1`（应挡)与 `64:ff9b::808:808`（内嵌 8.8.8.8,应放行)两个用例验证谓词行为正确。

### 8.3 端到端放行路径验证

用同一个 `_GuardedHTTPHandler` opener 真实访问 `http://example.com/`,断言 `status == 200` 且能正常读到响应体——确认校验逻辑本身不会误伤合法的公网请求（不是只测出"挡得住",也测了"没挡错")。
