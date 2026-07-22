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
from collections.abc import Callable

_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
_ALLOWED_SCHEMES = {"http", "https"}
_MAX_REDIRECTS = 10


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


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, url_validator: Callable[[str], bool] | None = None) -> None:
        super().__init__()
        self._url_validator = url_validator

    def http_error_302(self, req, fp, code, msg, headers):
        if "location" in headers:
            newurl = headers["location"]
        elif "uri" in headers:
            newurl = headers["uri"]
        else:
            return None

        count = getattr(req, "_forgeagent_redirect_count", 0)
        if count >= _MAX_REDIRECTS:
            raise SSRFGuardError(f"redirect limit exceeded ({_MAX_REDIRECTS})")
        resolved_url = urllib.parse.urljoin(req.full_url, newurl)
        scheme = urllib.parse.urlsplit(resolved_url).scheme.lower()
        if scheme not in _ALLOWED_SCHEMES:
            raise SSRFGuardError(f"redirect scheme {scheme!r} is not allowed")
        return super().http_error_302(req, fp, code, msg, headers)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        count = getattr(req, "_forgeagent_redirect_count", 0)
        if count >= _MAX_REDIRECTS:
            raise SSRFGuardError(f"redirect limit exceeded ({_MAX_REDIRECTS})")
        resolved_url = urllib.parse.urljoin(req.full_url, newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, resolved_url)
        if redirected is not None:
            scheme = urllib.parse.urlsplit(redirected.full_url).scheme.lower()
            if scheme not in _ALLOWED_SCHEMES:
                raise SSRFGuardError(f"redirect scheme {scheme!r} is not allowed")
            if self._url_validator is not None:
                try:
                    authorized = self._url_validator(redirected.full_url)
                except Exception:
                    authorized = False
                if not authorized:
                    raise SSRFGuardError("redirect target is not authorized")
            redirected._forgeagent_redirect_count = count + 1
        return redirected


def guarded_urlopen(
    url: str,
    *,
    timeout: float = 10.0,
    url_validator: Callable[[str], bool] | None = None,
):
    """Perform a GET request through the SSRF guard.

    Rejects non-http/https schemes up front (e.g. `file://`, which would bypass the
    guard entirely since it never goes through HTTPHandler/HTTPSHandler).
    """
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SSRFGuardError(f"scheme {scheme!r} is not allowed, only http/https")
    if url_validator is not None:
        try:
            authorized = url_validator(url)
        except Exception:
            authorized = False
        if not authorized:
            raise SSRFGuardError("request target is not authorized")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _GuardedRedirectHandler(url_validator),
        _GuardedHTTPHandler(),
        _GuardedHTTPSHandler(),
    )
    return opener.open(url, timeout=timeout)
