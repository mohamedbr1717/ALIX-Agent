"""
Tests for tools/web.py — web_search provider chain + web_fetch SSRF guard.

All network access is mocked; no real HTTP is performed.
Run from the repo root:
    python -m pytest test_web_tools.py -q
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest import mock

import pytest
import requests

import tools.web as webmod
from tools.web import (
    WebTools,
    _validate_url,
    _parse_ddg_results,
    _parse_ddg_lite_results,
    _parse_bing_results,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeResp:
    def __init__(self, status=200, text="", headers=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}
        self.encoding = "utf-8"
        self._content = text.encode("utf-8")
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=16384):
        data = self._content
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]

    def close(self):
        self.closed = True


DDG_HTML = """
<html><body>
<div class="result">
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2Fdownloads%2F&amp;rut=aa">Python.org downloads</a>
<a class="result__snippet">Download Python 3.14.7</a>
</div>
<div class="result">
<a class="result__a" href="https://docs.python.org/">Python docs</a>
<a class="result__snippet">Documentation</a>
</div>
</body></html>
"""

DDG_EMPTY = '<html><body><div class="no-results">No results</div></body></html>'

LITE_HTML = """
<html><body><table>
<tr><td>1.</td><td>
<a rel="nofollow" href='//duckduckgo.com/l/?uddg=https%3A%2F%2Flite.example.com%2Fpage&amp;rut=bb'>Lite result title</a>
</td></tr>
<tr><td><a href="/lite/?q=more">More results</a></td></tr>
</table></body></html>
"""

BING_HTML = """
<html><body><ol>
<li class="b_algo"><h2><a href="https://bing.example.com/a">Bing first</a></h2>
<div class="b_caption"><p>First snippet text.</p></div></li>
<li class="b_algo"><h2><a href="https://bing.example.org/b">Bing second</a></h2></li>
<li class="b_ad"><h2><a href="https://ads.example.com/">Ad</a></h2></li>
</ol></body></html>
"""

BING_CONSENT = '<html><body><form id="consent">consent</form></body></html>'


def _patch_transport(post=None, get=None):
    """Patch requests.Session.get/post with URL-dispatched fakes."""
    def fake_post(self, url, **kw):
        return post(url, kw)

    def fake_get(self, url, **kw):
        return get(url, kw)

    patches = []
    if post is not None:
        patches.append(mock.patch.object(requests.Session, "post", fake_post))
    if get is not None:
        patches.append(mock.patch.object(requests.Session, "get", fake_get))
    return patches


# ---------------------------------------------------------------------------
# Parser unit tests
# ---------------------------------------------------------------------------

def test_parse_ddg_results_unwraps_uddg():
    out = _parse_ddg_results(DDG_HTML)
    assert len(out) == 2
    assert out[0]["url"] == "https://www.python.org/downloads/"
    assert out[0]["title"] == "Python.org downloads"
    assert out[0]["snippet"] == "Download Python 3.14.7"


def test_parse_ddg_lite_results():
    out = _parse_ddg_lite_results(LITE_HTML)
    assert len(out) == 1
    assert out[0]["url"] == "https://lite.example.com/page"
    assert out[0]["title"] == "Lite result title"


def test_parse_bing_results_skips_ads():
    out = _parse_bing_results(BING_HTML)
    assert len(out) == 2
    assert out[0]["url"] == "https://bing.example.com/a"
    assert out[0]["title"] == "Bing first"
    assert out[0]["snippet"] == "First snippet text."
    assert out[1]["snippet"] == ""


def test_parse_bing_consent_page_empty():
    assert _parse_bing_results(BING_CONSENT) == []


# ---------------------------------------------------------------------------
# Provider chain tests
# ---------------------------------------------------------------------------

def _run_chain(ddg_post=None, ddg_get=None, lite_get=None, bing_get=None):
    def post(url, kw):
        assert "duckduckgo.com/html" in url
        return ddg_post(url, kw)

    def get(url, kw):
        if "lite.duckduckgo.com" in url:
            return lite_get(url, kw)
        if "bing.com" in url:
            return bing_get(url, kw)
        assert "duckduckgo.com/html" in url
        return ddg_get(url, kw)

    patches = _patch_transport(post=post, get=get)
    for p in patches:
        p.start()
    try:
        return WebTools().web_search("latest python", max_results=5)
    finally:
        for p in patches:
            p.stop()


def _boom(msg):
    def _f(url, kw):
        raise AssertionError(msg)
    return _f


def test_chain_ddg_wins_when_it_has_results():
    calls = []

    def ddg_post(url, kw):
        calls.append("ddg-post")
        return FakeResp(text=DDG_HTML)

    out = _run_chain(
        ddg_post=ddg_post,
        ddg_get=_boom("no GET expected"),
        lite_get=_boom("no lite expected"),
        bing_get=_boom("no bing expected"),
    )
    assert out["ok"] is True
    assert len(out["evidence"]["results"]) == 2
    assert out["evidence"]["provider"] == "duckduckgo"
    assert calls == ["ddg-post"]


def test_chain_falls_back_to_lite_on_ddg_empty():
    out = _run_chain(
        ddg_post=lambda u, k: FakeResp(text=DDG_EMPTY),
        ddg_get=lambda u, k: FakeResp(text=DDG_EMPTY),
        lite_get=lambda u, k: FakeResp(text=LITE_HTML),
        bing_get=_boom("no bing expected"),
    )
    assert out["ok"] is True
    assert out["evidence"]["provider"] == "duckduckgo-lite"
    assert out["evidence"]["results"][0]["url"] == "https://lite.example.com/page"
    assert out["evidence"]["providers_tried"] == ["duckduckgo", "duckduckgo-lite"]


def test_chain_ddg_202_then_lite():
    out = _run_chain(
        ddg_post=lambda u, k: FakeResp(status=202, text="challenge"),
        ddg_get=lambda u, k: FakeResp(status=202, text="challenge"),
        lite_get=lambda u, k: FakeResp(text=LITE_HTML),
        bing_get=_boom("no bing expected"),
    )
    assert out["ok"] is True
    assert out["evidence"]["provider"] == "duckduckgo-lite"


def test_chain_falls_back_to_bing():
    out = _run_chain(
        ddg_post=lambda u, k: FakeResp(text=DDG_EMPTY),
        ddg_get=lambda u, k: FakeResp(text=DDG_EMPTY),
        lite_get=lambda u, k: FakeResp(text=DDG_EMPTY),
        bing_get=lambda u, k: FakeResp(text=BING_HTML),
    )
    assert out["ok"] is True
    assert out["evidence"]["provider"] == "bing"
    assert len(out["evidence"]["results"]) == 2


def test_chain_all_empty_is_failure():
    out = _run_chain(
        ddg_post=lambda u, k: FakeResp(text=DDG_EMPTY),
        ddg_get=lambda u, k: FakeResp(text=DDG_EMPTY),
        lite_get=lambda u, k: FakeResp(text=DDG_EMPTY),
        bing_get=lambda u, k: FakeResp(text=BING_CONSENT),
    )
    assert out["ok"] is False
    assert "كل المصادر" in out["message"]
    assert out["evidence"]["results"] == []


def test_chain_network_error_skips_provider():
    def _down(url, kw):
        raise requests.ConnectionError("down")

    out = _run_chain(
        ddg_post=_down,
        ddg_get=_down,
        lite_get=lambda u, k: FakeResp(text=LITE_HTML),
        bing_get=_boom("no bing expected"),
    )
    assert out["ok"] is True
    assert out["evidence"]["provider"] == "duckduckgo-lite"


def test_empty_query_rejected():
    out = WebTools().web_search("   ")
    assert out["ok"] is False


def test_max_results_clamped():
    out = _run_chain(
        ddg_post=lambda u, k: FakeResp(text=DDG_HTML),
        ddg_get=lambda u, k: FakeResp(text=DDG_HTML),
        lite_get=lambda u, k: FakeResp(text=LITE_HTML),
        bing_get=lambda u, k: FakeResp(text=BING_HTML),
    )
    # DDG fixture has 2 results; max_results=5 keeps both
    assert len(out["evidence"]["results"]) == 2


# ---------------------------------------------------------------------------
# SSRF guard (unchanged behavior)
# ---------------------------------------------------------------------------

def test_validate_url_rejects_private_ip_literal():
    ok, reason = _validate_url("http://192.168.1.1/admin")
    assert ok is False


def test_validate_url_rejects_loopback():
    ok, _ = _validate_url("http://127.0.0.1:8080/")
    assert ok is False


def test_validate_url_rejects_non_http_scheme():
    ok, _ = _validate_url("file:///etc/passwd")
    assert ok is False


def test_validate_url_rejects_credentials():
    ok, _ = _validate_url("https://user:pass@example.com/")
    assert ok is False


def test_validate_url_accepts_public_host():
    with mock.patch.object(
        webmod, "_resolve_ips", return_value={"93.184.216.34"}
    ):
        ok, reason = _validate_url("https://example.com/")
    assert ok is True, reason


def test_fetch_redirect_to_private_blocked():
    def fake_get(self, url, **kw):
        if url == "http://example.com/":
            return FakeResp(status=302, headers={"Location": "http://10.0.0.1/"})
        raise AssertionError(f"unexpected fetch of {url}")

    def fake_resolve(host):
        return {"93.184.216.34"} if host == "example.com" else {"10.0.0.1"}

    with mock.patch.object(requests.Session, "get", fake_get), \
         mock.patch.object(webmod, "_resolve_ips", side_effect=fake_resolve):
        out = WebTools().web_fetch("http://example.com/")
    assert out["ok"] is False
    assert "مرفوض" in out["message"]
