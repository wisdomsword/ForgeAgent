"""Web search for the REPL `/search` command (M9 Phase 4, spike S4).

Best-effort HTML scraping — the search engines' HTML pages are NOT a contract
interface: a markup change on their side will silently break parsing (we then
return zero results, never crash). Default engine is Bing (spike S4: DuckDuckGo
is unreachable from some networks); DuckDuckGo remains available as a fallback,
selectable via the `search_engine` key in ~/.forgeagent/config.yaml.

Security (threat-model T11a): the query is percent-encoded via urllib.parse.quote
and substituted into a fixed URL template, so the host can never be rewritten by
query content; the request itself goes through ssrf_guard.guarded_urlopen, which
re-checks every resolved address. Failures are never raised to the caller: search
returns an empty list and logs the detail (user ruling — no raw tracebacks).
"""

from __future__ import annotations

import http.client
import logging
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import yaml

from .ssrf_guard import SSRFGuardError, guarded_urlopen

logger = logging.getLogger(__name__)

# Fixed URL templates keyed by engine name. The query is always quote()-encoded
# before substitution, so it cannot alter the host or path (T11a).
SEARCH_ENGINES: dict[str, str] = {
    "bing": "https://www.bing.com/search?q={query}",
    "duckduckgo": "https://html.duckduckgo.com/html/?q={query}",
}
DEFAULT_ENGINE = "bing"
DEFAULT_USER_CONFIG_PATH = Path.home() / ".forgeagent" / "config.yaml"

# Error kinds reported by _search_with_status (CLI maps these to friendly lines).
ERROR_BLOCKED = "blocked"  # SSRF guard rejected the request
ERROR_UNAVAILABLE = "unavailable"  # network failure / non-200 response


@dataclass
class SearchResult:
    """One search hit: title, URL, and a short snippet."""

    title: str
    url: str
    snippet: str = ""


def load_search_engine(config_path: Path | None = None) -> str:
    """Read the `search_engine` override from ~/.forgeagent/config.yaml.

    Missing file, malformed YAML, or an unknown engine name all fall back to the
    default engine (config is opt-in; a broken override must not kill /search).
    """
    path = DEFAULT_USER_CONFIG_PATH if config_path is None else config_path
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except OSError:
        return DEFAULT_ENGINE
    except yaml.YAMLError:
        logger.warning("malformed config.yaml at %s; using default search engine", path)
        return DEFAULT_ENGINE
    engine = data.get("search_engine") if isinstance(data, dict) else None
    if engine in SEARCH_ENGINES:
        return engine
    if engine is not None:
        logger.warning("unknown search_engine %r in config; using %s", engine, DEFAULT_ENGINE)
    return DEFAULT_ENGINE


class _BingParser(HTMLParser):
    """Extract results from Bing's HTML (spike S4 anchors: li.b_algo holds one
    result; its h2 > a is title+URL; text inside .b_caption is the snippet)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchResult] = []
        self._in_result = False
        self._depth = 0  # tag depth inside the current li.b_algo
        self._in_h2 = False
        self._in_title_link = False
        self._caption_depth = 0  # >0 while inside .b_caption
        self._title: list[str] = []
        self._url = ""
        self._snippet: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        if tag == "li" and "b_algo" in classes:
            self._in_result = True
            self._depth = 1
            self._in_h2 = False
            self._in_title_link = False
            self._caption_depth = 0
            self._title, self._url, self._snippet = [], "", []
            return
        if not self._in_result:
            return
        self._depth += 1
        if self._caption_depth:
            self._caption_depth += 1
        elif "b_caption" in classes:
            self._caption_depth = 1
        if tag == "h2":
            self._in_h2 = True
        elif tag == "a" and self._in_h2 and not self._url:
            self._in_title_link = True
            self._url = dict(attrs).get("href") or ""

    def handle_endtag(self, tag: str) -> None:
        if not self._in_result:
            return
        if tag == "a":
            self._in_title_link = False
        if tag == "h2":
            self._in_h2 = False
        if self._caption_depth:
            self._caption_depth -= 1
        self._depth -= 1
        if self._depth <= 0:
            title = "".join(self._title).strip()
            if title and self._url:
                self.results.append(
                    SearchResult(
                        title=title, url=self._url, snippet=" ".join(self._snippet).strip()
                    )
                )
            self._in_result = False

    def handle_data(self, data: str) -> None:
        if not self._in_result:
            return
        if self._in_title_link:
            self._title.append(data)
        elif self._caption_depth and data.strip():
            self._snippet.append(data.strip())


class _DuckDuckGoParser(HTMLParser):
    """Extract results from the DuckDuckGo HTML endpoint (anchors: a.result__a is
    title+URL; elements with class result__snippet hold the snippet)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchResult] = []
        self._in_title = False
        self._snippet_depth = 0
        self._current: SearchResult | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            self._flush()
            self._in_title = True
            self._current = SearchResult(title="", url=dict(attrs).get("href") or "")
        elif "result__snippet" in classes and self._current is not None:
            self._snippet_depth = 1
        elif self._snippet_depth:
            self._snippet_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        elif self._snippet_depth:
            self._snippet_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        if self._in_title:
            self._current.title += data
        elif self._snippet_depth:
            self._current.snippet += data

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        if self._current is not None and self._current.title.strip() and self._current.url:
            self._current.title = self._current.title.strip()
            self._current.snippet = self._current.snippet.strip()
            self.results.append(self._current)
        self._current = None


_PARSERS: dict[str, type[HTMLParser]] = {"bing": _BingParser, "duckduckgo": _DuckDuckGoParser}


def _parse_results(html: str, engine: str) -> list[SearchResult]:
    parser = _PARSERS[engine]()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # malformed HTML must never crash /search (best effort)
        logger.warning("search result parsing failed for engine %s", engine, exc_info=True)
    return parser.results  # type: ignore[attr-defined]


def search_with_status(
    query: str, *, max_results: int = 5, engine: str | None = None
) -> tuple[list[SearchResult], str | None]:
    """Run a search; return (results, error_kind). error_kind is None on success
    (even with zero hits), ERROR_BLOCKED on SSRF rejection, ERROR_UNAVAILABLE on
    network failure or a non-200 response. Never raises.

    Public (unlike `search`) because the REPL `/search` command needs the error_kind
    to print a friendly one-liner (blocked vs. unavailable vs. zero hits) instead of
    collapsing every failure into an empty list."""
    engine = engine or load_search_engine()
    if engine not in SEARCH_ENGINES:
        engine = DEFAULT_ENGINE
    url = SEARCH_ENGINES[engine].format(query=urllib.parse.quote(query))
    try:
        with guarded_urlopen(url) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                logger.warning("search engine %s returned HTTP %s", engine, status)
                return [], ERROR_UNAVAILABLE
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read()
    except SSRFGuardError as exc:
        logger.warning("search request blocked by SSRF guard: %s", exc)
        return [], ERROR_BLOCKED
    except (OSError, http.client.HTTPException) as exc:  # incl. URLError/HTTPError/timeouts
        logger.warning("search request to %s failed: %s", engine, exc)
        return [], ERROR_UNAVAILABLE
    try:
        html = raw.decode(charset, errors="replace")
    except LookupError:
        html = raw.decode("utf-8", errors="replace")
    return _parse_results(html, engine)[:max_results], None


def search(query: str, *, max_results: int = 5) -> list[SearchResult]:
    """Search the web; return up to max_results hits. Never raises — every
    failure (SSRF block, network error, non-200, parse failure) returns an empty
    list with the detail logged."""
    return search_with_status(query, max_results=max_results)[0]
