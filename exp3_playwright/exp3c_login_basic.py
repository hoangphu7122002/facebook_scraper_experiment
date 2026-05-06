"""Playwright Facebook scraper using exported cookies for an authenticated session.

Setup:
  1. cp fb_cookies.example.json fb_cookies.json
  2. Replace PASTE_REAL_VALUE_HERE with cookies exported from your browser.
     Easiest: install "Cookie-Editor" extension on facebook.com, Export -> JSON.
  3. chmod 600 fb_cookies.json   # treat it as a secret
  4. python exp6_playwright_login.py

What this proves: with a valid FB session, m.facebook.com / www.facebook.com
returns real <article> elements for a Page profile, which the anonymous
session in exp5 could not see.
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

PAGE_URL  = "https://m.facebook.com/100063916755649/"
GROUP_URL = "https://m.facebook.com/groups/1569314343856132/"
COOKIE_FILE = Path(__file__).parent.parent / "fb_cookies.json"
OUT = Path(__file__).parent / "outputs"
OUT.mkdir(exist_ok=True)

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

REQUIRED_COOKIES = {"c_user", "xs"}


def load_cookies() -> list[dict]:
    if not COOKIE_FILE.exists():
        sys.exit(f"Cookie file not found: {COOKIE_FILE}\n"
                 f"Run: cp fb_cookies.example.json fb_cookies.json and fill it in.")

    # Permissions sanity check on POSIX.
    try:
        mode = COOKIE_FILE.stat().st_mode & 0o777
        if mode & 0o077:
            print(f"WARN: {COOKIE_FILE.name} is world/group-readable (mode {oct(mode)}). "
                  f"Run: chmod 600 {COOKIE_FILE.name}")
    except Exception:
        pass

    cookies = json.loads(COOKIE_FILE.read_text())
    have = {c["name"] for c in cookies}
    missing = REQUIRED_COOKIES - have
    if missing:
        sys.exit(f"Missing required cookies: {missing}. "
                 f"Need at least c_user and xs from facebook.com.")

    # Normalize for Playwright. Cookie-Editor exports use "hostOnly" / "session"
    # which Playwright doesn't accept directly.
    out = []
    for c in cookies:
        if "PASTE_REAL_VALUE_HERE" in str(c.get("value", "")):
            sys.exit(f"Cookie {c['name']} still has placeholder value. Replace it.")
        # Cookie-Editor uses "no_restriction"/"lax"/"strict"/null; Playwright
        # only accepts "Strict"/"Lax"/"None".
        same_site_raw = (c.get("sameSite") or "").lower()
        same_site = {"lax": "Lax", "strict": "Strict",
                     "no_restriction": "None", "unspecified": "None",
                     "": "None", "none": "None"}.get(same_site_raw, "None")
        clean = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".facebook.com"),
            "path": c.get("path", "/"),
            "secure": c.get("secure", True),
            "httpOnly": c.get("httpOnly", False),
            "sameSite": same_site,
        }
        if "expirationDate" in c:
            clean["expires"] = int(c["expirationDate"])
        elif "expires" in c and isinstance(c["expires"], (int, float)):
            clean["expires"] = int(c["expires"])
        out.append(clean)
    return out


async def collect_articles(page) -> list[dict]:
    """Same idea as exp5 but here we expect <article> elements once logged in."""
    seen = set()
    rows = []
    for sel in ("article", 'div[role="article"]', 'div[data-tracking-duration-id]'):
        els = await page.query_selector_all(sel)
        if not els:
            continue
        for el in els:
            try:
                txt = (await el.inner_text()).strip()
            except Exception:
                continue
            if not txt or txt in seen:
                continue
            seen.add(txt)
            rows.append({"len": len(txt), "preview": txt[:300]})
        if rows:
            print(f"  selector that worked: {sel!r}, {len(rows)} unique blocks")
            break
    return rows


async def visit(ctx, label: str, url: str):
    print(f"\n========== {label} : {url} ==========")
    page = await ctx.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(3)
    print(f"  final url: {page.url}")
    print(f"  title:     {await page.title()}")

    # Sanity: did login actually take effect?
    body = await page.evaluate("() => (document.body && document.body.innerText) || ''")
    has_login_wall = re.search(r"\b(Log in|Đăng nhập)\b", body[:300])
    if has_login_wall:
        print("  WARN: page still shows a login link near the top — session may be invalid.")
    else:
        print("  ok: no top-level login wall")

    # Scroll to load more posts
    for i in range(8):
        await page.evaluate("window.scrollBy(0, 1800)")
        await asyncio.sleep(1.8)

    rows = await collect_articles(page)
    (OUT / f"login_{label}.html").write_text(await page.content(), encoding="utf-8")
    (OUT / f"login_{label}.json").write_text(
        json.dumps({"url": url, "final": page.url, "rows": rows},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    await page.screenshot(path=str(OUT / f"login_{label}.png"), full_page=False)
    for i, r in enumerate(rows[:3], 1):
        print(f"\n  [{i}] {r['preview'][:220]}")
    return len(rows)


async def main():
    cookies = load_cookies()
    print(f"Loaded {len(cookies)} cookies: {[c['name'] for c in cookies]}")

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=MOBILE_UA, is_mobile=True, has_touch=True, locale="en-US",
        )
        await ctx.add_cookies(cookies)

        n_page  = await visit(ctx, "page",  PAGE_URL)
        n_group = await visit(ctx, "group", GROUP_URL)
        await browser.close()

    print(f"\nResult: page={n_page} blocks, group={n_group} blocks")
    print("If page > 0, login worked. Compare with exp5 (anonymous) where page was 0.")


asyncio.run(main())
