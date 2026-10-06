"""E2E test for interactive browser: browse_page + fill -> submit.

Runs on the VPS where Playwright + Chromium are installed.
Tests the full session-persistence flow against httpbin.org/forms/post.

Usage: cd ~/ALIX-Agent && python3 /tmp/test_browser_e2e.py
"""
import sys
import traceback


def test_browse_page():
    """Test browse_page on a real URL."""
    print("\n=== Test 1: browse_page ===")
    from features.web.composition import build_browse_page_controller
    c = build_browse_page_controller()
    result = c.handle({"url": "https://example.com", "max_chars": 1000})
    assert result.get("ok"), f"browse_page failed: {result}"
    text = result.get("text", "")
    assert len(text) > 50, f"Expected substantial text, got {len(text)} chars"
    # "Example Domain" may appear in title or text
    combined = (result.get("title", "") + " " + text).lower()
    assert "example" in combined, "Expected 'example' in page content"
    print(f"  OK: title='{result.get('title')}', text_len={len(text)}")
    return True


def test_fill_submit_session():
    """Test fill -> submit shares session (the critical integration)."""
    print("\n=== Test 2: fill -> submit (session persistence) ===")
    from features.web.composition import (
        build_browser_fill_controller,
        build_browser_submit_controller,
    )
    fill_c = build_browser_fill_controller()
    submit_c = build_browser_submit_controller()

    # Verify same runner instance
    r1 = fill_c._use_case._runner
    r2 = submit_c._use_case._runner
    assert r1 is r2, "Controllers must share runner!"
    print("  OK: controllers share runner instance")

    # Fill the httpbin test form
    url = "https://httpbin.org/forms/post"
    fill_result = fill_c.handle({
        "url": url,
        "fields": {
            "input[name='custname']": "ALIX Test",
            "input[name='custtel']": "0612345678",
            "textarea[name='comments']": "E2E session test",
        }
    })
    print(f"  Fill result: ok={fill_result.get('ok')}, filled={fill_result.get('filled')}")
    if not fill_result.get("ok"):
        print(f"  Fill failed (may be selector issue): {fill_result.get('message')}")
        return False

    # Submit should reuse the filled session
    # httpbin's form uses various submit buttons; try common selectors
    submit_result = None
    for selector in [
        "button",
        "input[type='submit']",
        "button[type='submit']",
        "[type='submit']",
    ]:
        submit_result = submit_c.handle({
            "url": url,
            "selector": selector,
            "description": "E2E test submit",
        })
        if submit_result.get("ok"):
            print(f"  Submit OK with selector: {selector}")
            break
        print(f"  Selector '{selector}' failed, trying next...")
    print(f"  Submit result: ok={submit_result.get('ok')}")
    if submit_result.get("ok"):
        reused = submit_result.get("evidence", {}).get("reused_fill_session")
        print(f"  Session reused: {reused}")
        assert reused, "Submit MUST reuse the fill session!"
        # The submitted data should appear in the result
        result_text = submit_result.get("result_text", "")
        if "ALIX Test" in result_text:
            print("  OK: filled data present in submit result (session works!)")
        else:
            print("  WARNING: filled data not found in result (check manually)")
        return True
    else:
        print(f"  Submit failed: {submit_result.get('message')}")
        return False


def test_scheduled_block():
    """Verify browser tools are blocked in scheduled mode."""
    print("\n=== Test 3: scheduled-mode block ===")
    from core.policy import Policy
    p = Policy()
    p.scheduled_mode = True
    for tool in ("browse_page", "browser_fill", "browser_submit"):
        assert not p.scheduled_tool_permitted(tool), f"{tool} should be blocked!"
        print(f"  {tool}: BLOCKED (correct)")
    return True


def main():
    print("Browser E2E Test Suite")
    print("=" * 50)
    results = {}
    for name, fn in [
        ("browse_page", test_browse_page),
        ("fill_submit_session", test_fill_submit_session),
        ("scheduled_block", test_scheduled_block),
    ]:
        try:
            results[name] = fn()
        except Exception as e:
            print(f"  FAILED: {e}")
            traceback.print_exc()
            results[name] = False

    print("\n" + "=" * 50)
    print("Results:")
    all_ok = True
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  {name}: {status}")
        all_ok = all_ok and ok

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
