"""SSRF guard for outbound HTTP(S) fetches (M10 §3.3).

Validates every resolved address of an outbound request against a public/global
predicate before connecting, and closes the check-then-connect (DNS-rebinding) window
by connecting to the exact vetted sockaddr rather than re-resolving the hostname.
"""

import http.client
import ipaddress
import socket
import urllib.parse
import urllib.request

_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
_ALLOWED_SCHEMES = {"http", "https"}


class SSRFGuardError(Exception):
    """A candidate address for the target host is not allowed to be fetched."""


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip in _NAT64_PREFIX:
        embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if _is_blocked(embedded):
            return True
    return (not ip.is_global) or ip.is_multicast


def _guarded_create_connection(
    address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None
):
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


def guarded_urlopen(url: str, *, timeout: float = 10.0):
    """Perform a GET request through the SSRF guard.

    Rejects non-http/https schemes up front (e.g. `file://`, which would bypass the
    guard entirely since it never goes through HTTPHandler/HTTPSHandler).
    """
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SSRFGuardError(f"scheme {scheme!r} is not allowed, only http/https")
    opener = urllib.request.build_opener(_GuardedHTTPHandler, _GuardedHTTPSHandler)
    return opener.open(url, timeout=timeout)
