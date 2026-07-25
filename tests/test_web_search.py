"""Tests for web_search.py (M9 Phase 4 §3.5 /search command support).

search_with_status() is tested by monkeypatching guarded_urlopen rather than hitting
a real network or a local HTTPServer: 127.0.0.1 is itself a blocked address (see
test_ssrf_guard.py), so a loopback server can never reach the "success" path without
bypassing the guard's own connection check — at which point the test would no longer
exercise search_with_status's own logic (status handling, decoding, error mapping).
The guard itself already has full coverage in test_ssrf_guard.py.
"""

import http.client
import urllib.parse

import pytest

from forgeagent.ssrf_guard import SSRFGuardError
from forgeagent.web_search import (
    DEFAULT_ENGINE,
    ERROR_BLOCKED,
    ERROR_UNAVAILABLE,
    SearchResult,
    _BingParser,
    _DuckDuckGoParser,
    _parse_results,
    load_search_engine,
    search,
    search_with_status,
)


class _FakeHeaders:
    def __init__(self, charset: str | None = None) -> None:
        self._charset = charset

    def get_content_charset(self) -> str | None:
        return self._charset


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200, charset: str | None = None) -> None:
        self.status = status
        self.headers = _FakeHeaders(charset)
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info) -> None:
        return None


BING_HTML = """
<ol>
<li class="b_algo">
  <h2><a href="https://example.com/1">Example Title 1</a></h2>
  <div class="b_caption"><p>Snippet text one.</p></div>
</li>
<li class="b_algo">
  <h2><a href="https://example.com/2">Example Title 2</a></h2>
  <div class="b_caption"><p>Snippet text two.</p></div>
</li>
</ol>
"""

DUCKDUCKGO_HTML = """
<div class="result">
  <a class="result__a" href="https://example.com/1">DDG Title 1</a>
  <a class="result__snippet">DDG snippet one.</a>
</div>
<div class="result">
  <a class="result__a" href="https://example.com/2">DDG Title 2</a>
  <a class="result__snippet">DDG snippet two.</a>
</div>
"""


def test_load_search_engine_missing_file_returns_default(tmp_path):
    assert load_search_engine(tmp_path / "missing.yaml") == DEFAULT_ENGINE


def test_load_search_engine_malformed_yaml_returns_default(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("search_engine: [unterminated")
    assert load_search_engine(config) == DEFAULT_ENGINE


def test_load_search_engine_unknown_engine_returns_default(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("search_engine: altavista")
    assert load_search_engine(config) == DEFAULT_ENGINE


def test_load_search_engine_valid_override(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("search_engine: duckduckgo")
    assert load_search_engine(config) == "duckduckgo"


def test_bing_parser_extracts_title_url_snippet():
    results = _parse_results(BING_HTML, "bing")
    assert results == [
        SearchResult(
            title="Example Title 1", url="https://example.com/1", snippet="Snippet text one."
        ),
        SearchResult(
            title="Example Title 2", url="https://example.com/2", snippet="Snippet text two."
        ),
    ]


def test_duckduckgo_parser_extracts_title_url_snippet():
    results = _parse_results(DUCKDUCKGO_HTML, "duckduckgo")
    assert results == [
        SearchResult(title="DDG Title 1", url="https://example.com/1", snippet="DDG snippet one."),
        SearchResult(title="DDG Title 2", url="https://example.com/2", snippet="DDG snippet two."),
    ]


def test_bing_parser_ignores_malformed_fragments_without_crashing():
    """An li.b_algo whose closing tags are never fed (truncated/malformed markup)
    never drives the tag-depth counter back to 0, so no result is flushed — the
    parser degrades to zero results instead of crashing or guessing."""
    parser = _BingParser()
    parser.feed("<li class='b_algo'><h2><a href='https://example.com/x'>Title</a>")
    parser.close()
    assert parser.results == []


def test_duckduckgo_parser_close_flushes_pending_result():
    parser = _DuckDuckGoParser()
    parser.feed('<a class="result__a" href="https://example.com/y">Trailing</a>')
    parser.close()
    assert parser.results == [
        SearchResult(title="Trailing", url="https://example.com/y", snippet=""),
    ]


def test_search_with_status_encodes_query_and_uses_default_engine(monkeypatch):
    captured_urls: list[str] = []

    def fake_urlopen(url, *, timeout=10.0):
        captured_urls.append(url)
        return _FakeResponse(b"<ol></ol>")

    monkeypatch.setattr("forgeagent.web_search.guarded_urlopen", fake_urlopen)
    results, error_kind = search_with_status("a b&c", engine=DEFAULT_ENGINE)
    assert error_kind is None
    assert results == []
    encoded = urllib.parse.quote("a b&c")
    assert captured_urls == [
        f"https://www.bing.com/search?q={encoded}",
        f"https://html.duckduckgo.com/html/?q={encoded}",
    ]


@pytest.mark.parametrize("first_failure", ["network", "status", "zero"])
def test_search_falls_back_once_when_preferred_engine_has_no_results(
    monkeypatch, first_failure
):
    captured_urls: list[str] = []

    def fake_urlopen(url, *, timeout=10.0):
        captured_urls.append(url)
        if "bing.com" in url:
            if first_failure == "network":
                raise OSError("offline")
            if first_failure == "status":
                return _FakeResponse(b"", status=503)
            return _FakeResponse(b"<html>no results</html>")
        return _FakeResponse(DUCKDUCKGO_HTML.encode())

    monkeypatch.setattr("forgeagent.web_search.guarded_urlopen", fake_urlopen)

    results, error_kind = search_with_status("python", engine="bing")

    assert error_kind is None
    assert results[0].title == "DDG Title 1"
    assert len(captured_urls) == 2


def test_search_fallback_preserves_blocked_over_unavailable(monkeypatch):
    def fake_urlopen(url, *, timeout=10.0):
        if "bing.com" in url:
            raise SSRFGuardError("blocked")
        raise OSError("offline")

    monkeypatch.setattr("forgeagent.web_search.guarded_urlopen", fake_urlopen)

    assert search_with_status("python", engine="bing") == ([], ERROR_BLOCKED)


def test_search_fallback_reports_unavailable_when_both_engines_fail(monkeypatch):
    monkeypatch.setattr(
        "forgeagent.web_search.guarded_urlopen",
        lambda url, *, timeout=10.0: (_ for _ in ()).throw(OSError("offline")),
    )

    assert search_with_status("python", engine="bing") == ([], ERROR_UNAVAILABLE)


def test_search_fallback_returns_zero_without_error_after_both_engines(monkeypatch):
    captured_urls: list[str] = []

    def fake_urlopen(url, *, timeout=10.0):
        captured_urls.append(url)
        return _FakeResponse(b"<html>no results</html>")

    monkeypatch.setattr("forgeagent.web_search.guarded_urlopen", fake_urlopen)

    assert search_with_status("python", engine="bing") == ([], None)
    assert len(captured_urls) == 2


def test_search_does_not_request_fallback_after_preferred_success(monkeypatch):
    captured_urls: list[str] = []

    def fake_urlopen(url, *, timeout=10.0):
        captured_urls.append(url)
        return _FakeResponse(BING_HTML.encode())

    monkeypatch.setattr("forgeagent.web_search.guarded_urlopen", fake_urlopen)

    results, error_kind = search_with_status("python", engine="bing")

    assert error_kind is None
    assert results
    assert len(captured_urls) == 1


def test_search_with_status_unpaired_surrogate_returns_unavailable_without_request(
    monkeypatch, caplog
):
    query = "broken\ud800query"
    guarded_calls: list[str] = []

    def fake_urlopen(url, *, timeout=10.0):
        guarded_calls.append(url)
        return _FakeResponse(b"")

    monkeypatch.setattr("forgeagent.web_search.guarded_urlopen", fake_urlopen)
    results, error_kind = search_with_status(query, engine="bing")

    assert results == []
    assert error_kind == ERROR_UNAVAILABLE
    assert guarded_calls == []
    assert query not in caplog.text


def test_search_with_status_success_returns_results_and_none_error(monkeypatch):
    monkeypatch.setattr(
        "forgeagent.web_search.guarded_urlopen",
        lambda url, *, timeout=10.0: _FakeResponse(BING_HTML.encode("utf-8")),
    )
    results, error_kind = search_with_status("python", engine="bing")
    assert error_kind is None
    assert len(results) == 2
    assert results[0].title == "Example Title 1"


def test_search_with_status_zero_hits_returns_none_error(monkeypatch):
    monkeypatch.setattr(
        "forgeagent.web_search.guarded_urlopen",
        lambda url, *, timeout=10.0: _FakeResponse(b"<html><body>no results</body></html>"),
    )
    results, error_kind = search_with_status("nonsense query", engine="bing")
    assert results == []
    assert error_kind is None


def test_search_with_status_non_200_returns_unavailable(monkeypatch):
    monkeypatch.setattr(
        "forgeagent.web_search.guarded_urlopen",
        lambda url, *, timeout=10.0: _FakeResponse(b"", status=503),
    )
    results, error_kind = search_with_status("python", engine="bing")
    assert results == []
    assert error_kind == ERROR_UNAVAILABLE


def test_search_with_status_ssrf_blocked_returns_blocked(monkeypatch):
    def fake_urlopen(url, *, timeout=10.0):
        raise SSRFGuardError("blocked non-public address")

    monkeypatch.setattr("forgeagent.web_search.guarded_urlopen", fake_urlopen)
    results, error_kind = search_with_status("python", engine="bing")
    assert results == []
    assert error_kind == ERROR_BLOCKED


def test_search_with_status_oserror_returns_unavailable(monkeypatch):
    def fake_urlopen(url, *, timeout=10.0):
        raise OSError("network unreachable")

    monkeypatch.setattr("forgeagent.web_search.guarded_urlopen", fake_urlopen)
    results, error_kind = search_with_status("python", engine="bing")
    assert results == []
    assert error_kind == ERROR_UNAVAILABLE


def test_search_with_status_http_protocol_failure_returns_unavailable(monkeypatch):
    def fake_urlopen(url, *, timeout=10.0):
        raise http.client.BadStatusLine("secret-host.invalid")

    monkeypatch.setattr("forgeagent.web_search.guarded_urlopen", fake_urlopen)

    results, error_kind = search_with_status("python", engine="bing")

    assert results == []
    assert error_kind == ERROR_UNAVAILABLE


def test_search_with_status_unknown_charset_falls_back_to_utf8(monkeypatch):
    monkeypatch.setattr(
        "forgeagent.web_search.guarded_urlopen",
        lambda url, *, timeout=10.0: _FakeResponse(
            BING_HTML.encode("utf-8"), charset="unknown-charset"
        ),
    )

    results, error_kind = search_with_status("python", engine="bing")

    assert error_kind is None
    assert len(results) == 2


def test_search_with_status_respects_max_results(monkeypatch):
    monkeypatch.setattr(
        "forgeagent.web_search.guarded_urlopen",
        lambda url, *, timeout=10.0: _FakeResponse(BING_HTML.encode("utf-8")),
    )
    results, error_kind = search_with_status("python", engine="bing", max_results=1)
    assert error_kind is None
    assert len(results) == 1


def test_search_with_status_unknown_engine_falls_back_to_default(monkeypatch):
    captured_urls: list[str] = []

    def fake_urlopen(url, *, timeout=10.0):
        captured_urls.append(url)
        return _FakeResponse(b"<ol></ol>")

    monkeypatch.setattr("forgeagent.web_search.guarded_urlopen", fake_urlopen)
    search_with_status("python", engine="altavista")
    assert captured_urls[0].startswith("https://www.bing.com/")


def test_search_delegates_and_discards_error_kind(monkeypatch):
    def fake_urlopen(url, *, timeout=10.0):
        raise OSError("boom")

    monkeypatch.setattr("forgeagent.web_search.guarded_urlopen", fake_urlopen)
    assert search("python") == []
