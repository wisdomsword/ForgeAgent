"""Tests for the SSRF guard (M10 §3.3 / §八 spike).

Local HTTPServer instances are used instead of real network calls so the suite stays
fully offline. 127.0.0.1 itself is a blocked address, so the guard's own loopback
rejection doubles as the "blocked target never connects" test; a monkeypatched
pass-through stub is used to verify hop-by-hop redirect revalidation without needing
an allowed non-loopback address to bind to.
"""

import http.server
import ipaddress
import socket
import threading

import pytest

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


def test_guarded_urlopen_blocks_loopback_target():
    """127.0.0.1 is itself a blocked address, so a local HTTPServer round-trip must
    be refused before any socket connects out."""
    server = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with pytest.raises(SSRFGuardError):
            guarded_urlopen(f"http://127.0.0.1:{port}/", timeout=2)
    finally:
        server.shutdown()
        thread.join(timeout=5)


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
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


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
