"""Tests for the SSRF guard (M10 §3.3 / §八 spike).

Local HTTPServer instances are used instead of real network calls so the suite stays
fully offline. 127.0.0.1 itself is a blocked address, so the guard's own loopback
rejection doubles as the "blocked target never connects" test; a monkeypatched
pass-through stub is used to verify hop-by-hop redirect revalidation without needing
an allowed non-loopback address to bind to.
"""

import http.server
import io
import ipaddress
import socket
import threading
import urllib.request
import urllib.response
from email.message import Message

import pytest

from forgeagent import ssrf_guard
from forgeagent.headless import HeadlessConfirmer, operation_key
from forgeagent.protocol import WebFetchArgs
from forgeagent.ssrf_guard import (
    SSRFGuardError,
    _guarded_create_connection,
    _GuardedHTTPConnection,
    _is_blocked,
    guarded_urlopen,
)


def _network_available() -> bool:
    try:
        with socket.create_connection(("8.8.8.8", 53), timeout=2):
            return True
    except OSError:
        return False


network_required = pytest.mark.skipif(
    not _network_available(), reason="no outbound network access in this environment"
)

BLOCKED_ADDRESSES = [
    "127.0.0.1",
    "10.0.0.1",
    "172.16.0.1",
    "192.168.1.1",
    "169.254.169.254",  # cloud metadata
    "0.0.0.0",
    "100.64.0.1",  # CGNAT
    "224.0.0.1",  # multicast
    "255.255.255.255",
    "192.0.2.1",  # TEST-NET
    "::1",
    "fe80::1",  # link-local
    "fc00::1",  # unique local
    "ff02::1",  # multicast
    "64:ff9b::7f00:1",  # NAT64-wrapped 127.0.0.1
    "::ffff:127.0.0.1",  # IPv4-mapped
]

ALLOWED_ADDRESSES = [
    "8.8.8.8",
    "1.1.1.1",
    "2001:4860:4860::8888",
    "64:ff9b::808:808",  # NAT64-wrapped 8.8.8.8
]


@pytest.mark.parametrize("address", BLOCKED_ADDRESSES)
def test_is_blocked_true_for_blocked_matrix(address):
    assert _is_blocked(ipaddress.ip_address(address)) is True


@pytest.mark.parametrize("address", ALLOWED_ADDRESSES)
def test_is_blocked_false_for_allowed_matrix(address):
    assert _is_blocked(ipaddress.ip_address(address)) is False


def test_create_connection_hook_is_instance_attribute_not_shadowed():
    """Regression test for the design-doc bug: a class-level override would be
    silently shadowed by HTTPConnection.__init__ setting the same-named instance
    attribute. Assert the instance attribute is exactly our guarded function."""
    conn = _GuardedHTTPConnection("example.invalid")
    assert conn._create_connection is _guarded_create_connection


def test_guarded_urlopen_rejects_file_scheme():
    with pytest.raises(SSRFGuardError):
        guarded_urlopen("file:///etc/passwd")


def test_guarded_urlopen_rejects_other_non_http_schemes():
    with pytest.raises(SSRFGuardError):
        guarded_urlopen("ftp://example.com/")


def test_guarded_urlopen_blocks_loopback_target_without_connecting(monkeypatch):
    """Loopback is rejected before any socket is constructed or connected."""

    def _unexpected_socket(*args, **kwargs):
        pytest.fail("blocked loopback URL attempted a socket connection")

    monkeypatch.setattr("forgeagent.ssrf_guard.socket.socket", _unexpected_socket)
    with pytest.raises(SSRFGuardError):
        guarded_urlopen("http://127.0.0.1:9/", timeout=2)


_PROXY_ENV_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
)


@pytest.mark.parametrize(
    ("proxy_name", "url"),
    [
        ("HTTP_PROXY", "http://127.0.0.1/resource"),
        ("HTTPS_PROXY", "https://127.0.0.1/resource"),
        ("ALL_PROXY", "http://127.0.0.1/resource"),
        ("http_proxy", "http://127.0.0.1/resource"),
        ("https_proxy", "https://127.0.0.1/resource"),
        ("all_proxy", "http://127.0.0.1/resource"),
    ],
)
def test_environment_proxy_does_not_replace_guarded_target(monkeypatch, proxy_name, url):
    for name in _PROXY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(proxy_name, "http://8.8.8.8:9999")
    monkeypatch.setenv("NO_PROXY", "example.com")

    with pytest.raises(SSRFGuardError, match="127.0.0.1"):
        guarded_urlopen(url, timeout=0.1)


def test_no_proxy_loopback_bypass_still_uses_guard(monkeypatch):
    for name in _PROXY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://8.8.8.8:9999")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")

    with pytest.raises(SSRFGuardError, match="127.0.0.1"):
        guarded_urlopen("http://127.0.0.1/resource", timeout=0.1)


def test_guarded_urlopen_uses_explicit_empty_proxy_handler(monkeypatch):
    created_proxy_mappings = []
    real_proxy_handler = urllib.request.ProxyHandler

    class RecordingProxyHandler(real_proxy_handler):
        def __init__(self, proxies=None):
            created_proxy_mappings.append(proxies)
            super().__init__(proxies)

    monkeypatch.setattr("forgeagent.ssrf_guard.urllib.request.ProxyHandler", RecordingProxyHandler)

    with pytest.raises(SSRFGuardError, match="127.0.0.1"):
        guarded_urlopen("http://127.0.0.1/resource", timeout=0.1)

    assert created_proxy_mappings == [{}]


def test_redirect_handler_allows_tenth_hop():
    handler = ssrf_guard._GuardedRedirectHandler()
    request = urllib.request.Request("https://example.com/0")
    request._forgeagent_redirect_count = 9

    redirected = handler.redirect_request(request, None, 302, "Found", {}, "https://example.com/10")

    assert redirected is not None
    assert redirected._forgeagent_redirect_count == 10


def test_redirect_handler_resolves_relative_http_location_against_original_url():
    handler = ssrf_guard._GuardedRedirectHandler()
    request = urllib.request.Request("https://public.example/start")

    redirected = handler.redirect_request(request, None, 302, "Found", {}, "/next")

    assert redirected is not None
    assert redirected.full_url == "https://public.example/next"


def test_redirect_handler_rejects_eleventh_hop():
    handler = ssrf_guard._GuardedRedirectHandler()
    request = urllib.request.Request("https://example.com/0")
    request._forgeagent_redirect_count = 10

    with pytest.raises(SSRFGuardError, match="redirect limit exceeded"):
        handler.redirect_request(request, None, 302, "Found", {}, "https://example.com/11")


@pytest.mark.parametrize("url", ["ftp://example.com/a", "file:///etc/passwd"])
def test_redirect_handler_rejects_non_http_scheme(url):
    handler = ssrf_guard._GuardedRedirectHandler()
    request = urllib.request.Request("https://example.com/start")

    with pytest.raises(SSRFGuardError, match="scheme"):
        handler.redirect_request(request, None, 302, "Found", {}, url)


@pytest.mark.parametrize("redirect_code", [301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    "target_url",
    ["file:///etc/passwd", "ftp://example.com/private", "gopher://example.com/private"],
)
def test_guarded_urlopen_classifies_unsupported_redirect_before_destination_access(
    monkeypatch, redirect_code, target_url
):
    real_build_opener = urllib.request.build_opener
    destination_attempts = []

    class _SyntheticRedirectPipelineHandler(urllib.request.BaseHandler):
        handler_order = 100

        def http_open(self, request):
            if request.full_url != "http://public.example/redirect":
                return None
            headers = Message()
            headers["Location"] = target_url
            response = urllib.response.addinfourl(
                io.BytesIO(), headers, request.full_url, redirect_code
            )
            response.msg = "synthetic redirect"
            return response

        def file_open(self, request):
            destination_attempts.append(request.full_url)
            pytest.fail("redirect attempted file destination handler")

        def ftp_open(self, request):
            destination_attempts.append(request.full_url)
            pytest.fail("redirect attempted FTP destination handler")

    def _build_opener_with_synthetic_redirect(*handlers):
        return real_build_opener(_SyntheticRedirectPipelineHandler(), *handlers)

    def _unexpected_socket(*args, **kwargs):
        pytest.fail("unsupported redirect attempted socket construction")

    monkeypatch.setattr(
        "forgeagent.ssrf_guard.urllib.request.build_opener",
        _build_opener_with_synthetic_redirect,
    )
    monkeypatch.setattr("forgeagent.ssrf_guard.socket.socket", _unexpected_socket)

    with pytest.raises(SSRFGuardError, match="redirect scheme"):
        guarded_urlopen("http://public.example/redirect", timeout=1)

    assert destination_attempts == []


@pytest.mark.parametrize("redirect_code", [301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    "target_url",
    ["file:///etc/passwd", "ftp://example.com/private", "gopher://example.com/private"],
)
def test_guarded_urlopen_prioritizes_redirect_limit_over_unsupported_scheme(
    monkeypatch, redirect_code, target_url
):
    real_build_opener = urllib.request.build_opener
    destination_attempts = []
    initial_url = "http://public.example/redirect"

    class _SyntheticEleventhRedirectHandler(urllib.request.BaseHandler):
        handler_order = 100

        def http_open(self, request):
            if request.full_url != initial_url:
                return None
            request._forgeagent_redirect_count = 10
            headers = Message()
            headers["Location"] = target_url
            response = urllib.response.addinfourl(
                io.BytesIO(), headers, request.full_url, redirect_code
            )
            response.msg = "synthetic eleventh redirect"
            return response

        def _unexpected_destination(self, request):
            destination_attempts.append(request.full_url)
            pytest.fail("eleventh redirect attempted destination access")

        file_open = ftp_open = gopher_open = _unexpected_destination

    def _build_opener_with_synthetic_redirect(*handlers):
        return real_build_opener(_SyntheticEleventhRedirectHandler(), *handlers)

    def _unexpected_socket(*args, **kwargs):
        pytest.fail("eleventh redirect attempted socket construction")

    monkeypatch.setattr(
        "forgeagent.ssrf_guard.urllib.request.build_opener",
        _build_opener_with_synthetic_redirect,
    )
    monkeypatch.setattr("forgeagent.ssrf_guard.socket.socket", _unexpected_socket)

    with pytest.raises(SSRFGuardError, match="redirect limit exceeded"):
        guarded_urlopen(initial_url, timeout=1)

    assert destination_attempts == []


def test_guarded_urlopen_follows_relative_http_308_with_actual_opener_offline(monkeypatch):
    real_build_opener = urllib.request.build_opener
    requests = []
    initial_url = "http://public.example/redirect"
    target_url = "http://public.example/final"

    class _SyntheticHTTP308Handler(urllib.request.BaseHandler):
        handler_order = 100

        def http_open(self, request):
            requests.append((request.full_url, request.get_method()))
            headers = Message()
            if request.full_url == initial_url:
                headers["Location"] = "/final"
                response = urllib.response.addinfourl(io.BytesIO(), headers, request.full_url, 308)
            elif request.full_url == target_url:
                response = urllib.response.addinfourl(
                    io.BytesIO(b"synthetic-308-ok"), headers, request.full_url, 200
                )
            else:
                pytest.fail(f"unexpected synthetic URL: {request.full_url}")
            response.msg = "synthetic HTTP response"
            return response

    def _build_opener_with_synthetic_http(*handlers):
        return real_build_opener(_SyntheticHTTP308Handler(), *handlers)

    def _unexpected_socket(*args, **kwargs):
        pytest.fail("offline redirect characterization attempted socket construction")

    monkeypatch.setattr(
        "forgeagent.ssrf_guard.urllib.request.build_opener",
        _build_opener_with_synthetic_http,
    )
    monkeypatch.setattr("forgeagent.ssrf_guard.socket.socket", _unexpected_socket)

    response = guarded_urlopen(initial_url, timeout=1)

    assert response.status == 200
    assert response.read() == b"synthetic-308-ok"
    assert requests == [(initial_url, "GET"), (target_url, "GET")]


@pytest.mark.parametrize(
    "target_url",
    [
        "http://other.example/allowed",
        "http://public.example/private",
    ],
)
def test_guarded_urlopen_rejects_redirect_outside_exact_allowlist_before_request(
    monkeypatch, target_url
):
    real_build_opener = urllib.request.build_opener
    initial_url = "http://public.example/allowed"
    requests = []

    class _SyntheticRedirectHandler(urllib.request.BaseHandler):
        handler_order = 100

        def http_open(self, request):
            requests.append(request.full_url)
            if request.full_url != initial_url:
                pytest.fail("unauthorized redirect destination was requested")
            headers = Message()
            headers["Location"] = target_url
            response = urllib.response.addinfourl(io.BytesIO(), headers, request.full_url, 302)
            response.msg = "synthetic redirect"
            return response

    def _build_opener(*handlers):
        return real_build_opener(_SyntheticRedirectHandler(), *handlers)

    monkeypatch.setattr("forgeagent.ssrf_guard.urllib.request.build_opener", _build_opener)

    with pytest.raises(SSRFGuardError, match="not authorized") as raised:
        guarded_urlopen(
            initial_url,
            timeout=1,
            url_validator=lambda url: url == initial_url,
        )

    assert target_url not in str(raised.value)
    assert requests == [initial_url]


def test_guarded_urlopen_rejects_same_path_redirect_with_different_query_before_request(
    monkeypatch, tmp_path
):
    real_build_opener = urllib.request.build_opener
    initial_url = "http://public.example/allowed?account=public"
    target_url = "http://public.example/allowed?account=admin&include_secrets=true"
    requests = []

    class _SyntheticRedirectHandler(urllib.request.BaseHandler):
        handler_order = 100

        def http_open(self, request):
            requests.append(request.full_url)
            if request.full_url != initial_url:
                pytest.fail("unauthorized redirect destination was requested")
            headers = Message()
            headers["Location"] = target_url
            response = urllib.response.addinfourl(io.BytesIO(), headers, request.full_url, 302)
            response.msg = "synthetic redirect"
            return response

    def _build_opener(*handlers):
        return real_build_opener(_SyntheticRedirectHandler(), *handlers)

    monkeypatch.setattr("forgeagent.ssrf_guard.urllib.request.build_opener", _build_opener)
    confirmer = HeadlessConfirmer(
        {operation_key(WebFetchArgs(url=initial_url), tmp_path)},
        audit=None,
        root=tmp_path,
    )

    with pytest.raises(SSRFGuardError, match="not authorized"):
        guarded_urlopen(initial_url, timeout=1, url_validator=confirmer.allows_web_url)

    assert requests == [initial_url]


@pytest.mark.parametrize("redirect_code", [301, 302, 303, 307, 308])
def test_guarded_urlopen_blocks_loopback_redirect_before_socket_construction(
    monkeypatch, redirect_code
):
    real_build_opener = urllib.request.build_opener

    class _SyntheticPublicRedirectHandler(urllib.request.BaseHandler):
        handler_order = 100

        def http_open(self, request):
            if request.full_url != "http://public.example/redirect":
                return None
            headers = Message()
            headers["Location"] = "http://127.0.0.1/private"
            response = urllib.response.addinfourl(
                io.BytesIO(), headers, request.full_url, redirect_code
            )
            response.msg = "synthetic redirect"
            return response

    def _build_opener_with_synthetic_redirect(*handlers):
        return real_build_opener(_SyntheticPublicRedirectHandler(), *handlers)

    def _unexpected_socket(*args, **kwargs):
        pytest.fail("redirected loopback target attempted socket construction")

    monkeypatch.setattr(
        "forgeagent.ssrf_guard.urllib.request.build_opener",
        _build_opener_with_synthetic_redirect,
    )
    monkeypatch.setattr("forgeagent.ssrf_guard.socket.socket", _unexpected_socket)

    with pytest.raises(SSRFGuardError, match="127.0.0.1"):
        guarded_urlopen("http://public.example/redirect", timeout=1)


class _RespondOKHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass


def _make_redirect_handler(target_url: str) -> type[http.server.BaseHTTPRequestHandler]:
    class _RedirectHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", target_url)
            self.end_headers()

        def log_message(self, format, *args):  # noqa: A002 - stdlib signature
            pass

    return _RedirectHandler


def _start_server(handler_cls):
    try:
        server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    except (PermissionError, OSError):
        pytest.skip("local socket bind is unavailable")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_start_server_skips_when_local_socket_bind_is_unavailable(monkeypatch):
    def _deny_bind(*args, **kwargs):
        raise PermissionError("socket bind denied")

    monkeypatch.setattr(http.server, "HTTPServer", _deny_bind)
    with pytest.raises(pytest.skip.Exception, match="local socket bind is unavailable"):
        _start_server(_RespondOKHandler)


def test_redirect_hop_by_hop_revalidation(monkeypatch):
    """Each redirect hop must independently re-enter _guarded_create_connection with
    that hop's own host/port, confirming stdlib's HTTPRedirectHandler drives
    hop-by-hop revalidation rather than a single upfront check."""
    calls: list[tuple[str, int]] = []
    real_create_connection = socket.create_connection

    def _recording_pass_through(
        address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None
    ):
        calls.append(address)
        return real_create_connection(address, timeout=timeout, source_address=source_address)

    monkeypatch.setattr("forgeagent.ssrf_guard._guarded_create_connection", _recording_pass_through)

    target_server, target_thread = _start_server(_RespondOKHandler)
    try:
        target_port = target_server.server_address[1]
        target_url = f"http://127.0.0.1:{target_port}/"
        redirect_server, redirect_thread = _start_server(_make_redirect_handler(target_url))
        try:
            redirect_port = redirect_server.server_address[1]
            response = guarded_urlopen(f"http://127.0.0.1:{redirect_port}/", timeout=5)
            assert response.status == 200
            assert response.read() == b"ok"
        finally:
            redirect_server.shutdown()
            redirect_thread.join(timeout=5)
    finally:
        target_server.shutdown()
        target_thread.join(timeout=5)

    assert len(calls) == 2
    assert calls[0][1] == redirect_port
    assert calls[1][1] == target_port


@network_required
def test_guarded_urlopen_allows_real_public_site():
    response = guarded_urlopen("https://example.com/", timeout=10)
    assert response.status == 200
