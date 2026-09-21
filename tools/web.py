"""
tools/web.py — Web search + URL fetch tools for ALIX-Agent.

Read-only, no API key required. Search uses a provider chain
(DuckDuckGo HTML -> DuckDuckGo Lite -> Bing HTML): the first provider
returning results wins. The chain exists because DDG intermittently
serves empty/challenge pages to automated traffic (HTTP 200 with
0 parsed results), which a single-provider design reports as failure.

Security properties:
  - SSRF guard: only http/https; no credentials in URL; the host must
    resolve exclusively to public IPs (private, loopback, link-local,
    multicast, reserved and unspecified ranges are rejected). Every
    redirect hop is re-validated (max 5 hops).
  - Timeouts on every request; response bodies are size-capped.
  - Only textual content-types are returned; binaries are refused.
  - Results are untrusted external data: they flow through the agent's
    prompt_guard (scan + redact + tag neutralization) like any tool output.

Return contract: ExecutionResult.to_dict(), matching the other tools.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time
import html as _html
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs, urljoin, unquote

import requests

from core.executor import ExecutionResult

_DDG_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
_DDG_LITE_ENDPOINT = "https://lite.duckduckgo.com/lite/"
_BING_ENDPOINT = "https://www.bing.com/search"
_USER_AGENT = "ALIX-Agent/1.0 (personal assistant; contact: local)"

_SEARCH_TIMEOUT = 15
_FETCH_TIMEOUT = 20
_MAX_REDIRECTS = 5
_MAX_BODY_BYTES = 200_000  # hard download cap; text is truncated below this

_DEFAULT_MAX_RESULTS = 5
_DEFAULT_MAX_CHARS = 8000
_HARD_MAX_CHARS = 50_000


# ---------------------------------------------------------------------------
# HTML -> text (stdlib only; Termux has no bs4)
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    _SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
    _BLOCK_TAGS = {
        "p", "div", "br", "li", "ul", "ol", "tr", "table",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "article", "section", "header", "footer", "blockquote", "pre",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t\u00a0]+", " ", raw)
        raw = re.sub(r"\n[ \t]*\n+", "\n\n", raw)
        return raw.strip()


def _strip_tags(fragment: str) -> str:
    """Remove tags from a small HTML fragment (titles, snippets)."""
    text = re.sub(r"<[^>]+>", "", fragment or "")
    text = _html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------

def _resolve_ips(host: str) -> set[str] | None:
    try:
        infos = socket.getaddrinfo(
            host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
    except (socket.gaierror, UnicodeError):
        return None
    return {info[4][0] for info in infos}


def _ip_is_public(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_url(url: str) -> tuple[bool, str]:
    """
    Return (True, "") when *url* is safe to fetch, else (False, reason).
    NOTE: DNS is resolved at validation time; a hostile DNS that changes
    answers between validation and connect (rebinding) is a residual risk
    documented here. Direct private/loopback URLs and redirect chains into
    private space are blocked.
    """
    if not isinstance(url, str) or not url.strip():
        return False, "empty URL"
    url = url.strip()
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return False, f"unparseable URL: {exc}"
    if parsed.scheme not in ("http", "https"):
        return False, f"scheme '{parsed.scheme}' not allowed (http/https only)"
    if parsed.username or parsed.password:
        return False, "credentials in URL are not allowed"
    host = parsed.hostname
    if not host:
        return False, "no hostname"
    ips = _resolve_ips(host)
    if not ips:
        return False, f"DNS resolution failed for '{host}'"
    for ip in sorted(ips):
        if not _ip_is_public(ip):
            return False, f"host '{host}' resolves to non-public IP {ip}"
    return True, ""


# ---------------------------------------------------------------------------
# DuckDuckGo result parsing
# ---------------------------------------------------------------------------

_DDG_RESULT_RX = re.compile(
    r'<a(?=[^>]*class="result__a")[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
    r".*?"
    r'<a(?=[^>]*class="result__snippet")[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)


def _ddg_target_url(href: str) -> str:
    """Unwrap DuckDuckGo's //duckduckgo.com/l/?uddg=... redirect links."""
    href = (href or "").strip()
    if href.startswith("//"):
        href = "https:" + href
    if "duckduckgo.com/l/" in href:
        try:
            qs = parse_qs(urlparse(href).query)
            uddg = qs.get("uddg", [""])[0]
            if uddg:
                return unquote(uddg)
        except Exception:
            pass
    return href


def _parse_ddg_results(html_text: str) -> list[dict]:
    results = []
    for href, title_frag, snippet_frag in _DDG_RESULT_RX.findall(html_text or ""):
        url = _ddg_target_url(_html.unescape(href))
        title = _strip_tags(title_frag)
        snippet = _strip_tags(snippet_frag)
        if not url or not title:
            continue
        results.append({"title": title, "url": url, "snippet": snippet})
    return results


def _parse_ddg_lite_results(html_text: str) -> list[dict]:
    """Parse DuckDuckGo Lite: simpler markup, rarely bot-challenged.

    Result links look like <a href="//duckduckgo.com/l/?uddg=<url>&...">.
    """

    class _LiteParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.results: list[dict] = []
            self._href: str | None = None
            self._title_parts: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                href = dict(attrs).get("href", "")
                if "uddg=" in href:
                    self._href = href
                    self._title_parts = []

        def handle_data(self, data):
            if self._href is not None:
                self._title_parts.append(data)

        def handle_endtag(self, tag):
            if tag == "a" and self._href is not None:
                url = _ddg_target_url(self._href)
                title = _strip_tags("".join(self._title_parts))
                if url.startswith(("http://", "https://")) and title:
                    self.results.append(
                        {"title": title, "url": url, "snippet": ""}
                    )
                self._href = None
                self._title_parts = []

    parser = _LiteParser()
    try:
        parser.feed(html_text or "")
    except Exception:
        pass
    # de-duplicate by URL, keep order
    seen: set[str] = set()
    out: list[dict] = []
    for item in parser.results:
        if item["url"] not in seen:
            seen.add(item["url"])
            out.append(item)
    return out


class _BingParser(HTMLParser):
    """Parse Bing HTML result blocks (<li class="b_algo">)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._in_result = False
        self._in_h2 = False
        self._in_a = False
        self._in_p = False
        self._cur: dict | None = None

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "li" and "b_algo" in attrs_d.get("class", ""):
            self._in_result = True
            self._cur = {"title": "", "url": "", "snippet": ""}
        elif self._in_result and tag == "h2":
            self._in_h2 = True
        elif self._in_result and self._in_h2 and tag == "a":
            href = attrs_d.get("href", "").strip()
            if href.startswith(("http://", "https://")):
                self._cur["url"] = href
                self._in_a = True
        elif self._in_result and tag == "p" and self._cur["url"]:
            # first paragraph after the title link ~= snippet
            if not self._cur["snippet"]:
                self._in_p = True

    def handle_data(self, data):
        if self._in_a:
            self._cur["title"] += data
        elif self._in_p:
            self._cur["snippet"] += data

    def handle_endtag(self, tag):
        if tag == "a":
            self._in_a = False
        elif tag == "h2":
            self._in_h2 = False
        elif tag == "p":
            self._in_p = False
        elif tag == "li" and self._in_result:
            self._in_result = False
            title = _strip_tags(self._cur["title"])
            snippet = _strip_tags(self._cur["snippet"])
            if self._cur["url"] and title:
                self.results.append(
                    {"title": title, "url": self._cur["url"],
                     "snippet": snippet}
                )
            self._cur = None


def _parse_bing_results(html_text: str) -> list[dict]:
    parser = _BingParser()
    try:
        parser.feed(html_text or "")
    except Exception:
        pass
    return parser.results


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class WebTools:
    """Read-only web tools: web_search + web_fetch."""

    # -- helpers ------------------------------------------------------

    @staticmethod
    def _fail(action: str, message: str, started: float,
              evidence: dict | None = None) -> dict:
        return ExecutionResult(
            ok=False,
            action=action,
            message=message,
            evidence=evidence or {},
            duration=time.monotonic() - started,
        ).to_dict()

    @staticmethod
    def _clamp_int(value, default: int, lo: int, hi: int) -> int:
        try:
            # bool is an int subclass; reject it explicitly
            if isinstance(value, bool):
                return default
            number = int(value)
        except (TypeError, ValueError):
            return default
        return max(lo, min(hi, number))

    def _session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({"User-Agent": _USER_AGENT})
        return session

    # -- web_search providers -----------------------------------------

    def _search_ddg(self, session: requests.Session, query: str) -> list[dict]:
        """DuckDuckGo HTML endpoint: POST, then GET as fallback."""
        attempts = [
            lambda: session.post(
                _DDG_HTML_ENDPOINT,
                data={"q": query},
                timeout=_SEARCH_TIMEOUT,
            ),
            lambda: session.get(
                _DDG_HTML_ENDPOINT,
                params={"q": query},
                timeout=_SEARCH_TIMEOUT,
            ),
        ]
        for attempt in attempts:
            resp = attempt()  # RequestException propagates to the caller
            # DDG answers automated traffic with 202 + challenge page.
            if resp.status_code == 202:
                continue
            resp.raise_for_status()
            return _parse_ddg_results(resp.text)
        return []

    def _search_ddg_lite(self, session: requests.Session,
                         query: str) -> list[dict]:
        """DuckDuckGo Lite: simpler markup, rarely challenged."""
        resp = session.get(
            _DDG_LITE_ENDPOINT,
            params={"q": query},
            timeout=_SEARCH_TIMEOUT,
        )
        resp.raise_for_status()
        return _parse_ddg_lite_results(resp.text)

    def _search_bing(self, session: requests.Session, query: str) -> list[dict]:
        """Bing HTML: last-resort provider, no API key."""
        resp = session.get(
            _BING_ENDPOINT,
            params={"q": query},
            timeout=_SEARCH_TIMEOUT,
        )
        resp.raise_for_status()
        return _parse_bing_results(resp.text)

    # -- web_search ----------------------------------------------------

    def web_search(self, query: str, max_results: int = 5) -> dict:
        started = time.monotonic()
        if not isinstance(query, str) or not query.strip():
            return self._fail("web_search", "query فارغ.", started)
        max_results = self._clamp_int(
            max_results, _DEFAULT_MAX_RESULTS, 1, 10
        )
        session = self._session()
        query = query.strip()

        # Provider chain: DDG intermittently serves empty/challenge pages
        # to automated traffic (HTTP 200 with 0 parsed results), so fall
        # through to Lite then Bing instead of failing outright.
        providers = [
            ("duckduckgo", self._search_ddg),
            ("duckduckgo-lite", self._search_ddg_lite),
            ("bing", self._search_bing),
        ]
        tried: list[str] = []
        last_error = ""
        winner: str | None = None
        results: list[dict] = []
        for name, provider in providers:
            tried.append(name)
            try:
                found = provider(session, query)
            except requests.RequestException as exc:
                last_error = f"{name}: {exc}"
                continue
            if found:
                winner = name
                results = found
                break
            last_error = f"{name}: 0 results"
        if not results:
            return self._fail(
                "web_search",
                "تعذّر البحث: كل المصادر أعادت صفر نتائج"
                + (f" (آخر حالة: {last_error})" if last_error else ""),
                started,
                evidence={
                    "query": query,
                    "results": [],
                    "providers_tried": tried,
                },
            )
        results = results[:max_results]
        return ExecutionResult(
            ok=True,
            action="web_search",
            message=f"تم العثور على {len(results)} نتيجة.",
            evidence={
                "query": query,
                "results": results,
                "provider": winner,
                "providers_tried": tried,
            },
            duration=time.monotonic() - started,
        ).to_dict()

    # -- web_fetch -----------------------------------------------------

    def _fetch_once(self, session: requests.Session, url: str):
        """Single GET without following redirects. Returns (response|None, error)."""
        try:
            resp = session.get(
                url, timeout=_FETCH_TIMEOUT, allow_redirects=False, stream=True
            )
            return resp, ""
        except requests.RequestException as exc:
            return None, f"تعذر الجلب: {exc}"

    def web_fetch(self, url: str, max_chars: int = 8000) -> dict:
        started = time.monotonic()
        max_chars = self._clamp_int(max_chars, _DEFAULT_MAX_CHARS, 1000, _HARD_MAX_CHARS)

        current = url.strip() if isinstance(url, str) else ""
        session = self._session()
        final_url = current

        for _ in range(_MAX_REDIRECTS + 1):
            ok, reason = _validate_url(current)
            if not ok:
                return self._fail("web_fetch", f"رابط مرفوض: {reason}", started)

            resp, err = self._fetch_once(session, current)
            if resp is None:
                return self._fail("web_fetch", err, started)

            try:
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location", "")
                    resp.close()
                    if not location:
                        return self._fail(
                            "web_fetch", "إعادة توجيه بلا وجهة.", started
                        )
                    current = urljoin(current, location)
                    final_url = current
                    continue

                if resp.status_code != 200:
                    resp.close()
                    return self._fail(
                        "web_fetch", f"HTTP {resp.status_code}", started
                    )

                content_type = resp.headers.get("Content-Type", "").lower()
                if not (
                    "text/" in content_type
                    or "json" in content_type
                    or "xml" in content_type
                ):
                    resp.close()
                    return self._fail(
                        "web_fetch",
                        f"نوع محتوى غير مدعوم: {content_type or 'غير معروف'}",
                        started,
                    )

                # Size-capped body read (iter_content decodes gzip transparently).
                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_content(chunk_size=16384):
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= _MAX_BODY_BYTES:
                        break
                resp.close()

                raw = b"".join(chunks)
                encoding = resp.encoding or "utf-8"
                try:
                    text = raw.decode(encoding, errors="replace")
                except (LookupError, UnicodeError):
                    text = raw.decode("utf-8", errors="replace")

                if "html" in content_type:
                    extractor = _TextExtractor()
                    extractor.feed(text)
                    title_m = re.search(
                        r"<title[^>]*>(.*?)</title>", text,
                        re.DOTALL | re.IGNORECASE,
                    )
                    title = _strip_tags(title_m.group(1)) if title_m else ""
                    text = extractor.text()
                else:
                    title = ""

                if len(text) > max_chars:
                    text = text[:max_chars] + "\n…[مقتطع: الحد max_chars]"

                return ExecutionResult(
                    ok=True,
                    action="web_fetch",
                    message=f"تم جلب {len(text)} حرفًا من {final_url}",
                    evidence={
                        "url": final_url,
                        "title": title,
                        "text": text,
                    },
                    duration=time.monotonic() - started,
                ).to_dict()
            finally:
                try:
                    resp.close()
                except Exception:
                    pass

        return self._fail("web_fetch", "تجاوز حد إعادة التوجيه.", started)
