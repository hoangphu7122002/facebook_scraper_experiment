"""Browser session setup — cookies, stealth, mobile context.

Strategy (per knowledge.md):
- Layer 1 TLS: Playwright Chromium uses real browser TLS — no extra work.
- Layer 2 HTTP: stealth + matching UA / viewport / locale / timezone.
- Layer 3 Cookies: load from fb_cookies.json. Save back after the run so any
  rotation FB performs (xs / fr / presence) is captured for next time.
- Layer 4 Fingerprint: playwright-stealth patches navigator.webdriver, plugins,
  WebGL vendor, etc.

Single entry point: `open_session()` returns (browser, ctx, save_cookies_fn).
"""
import json
import sys
from pathlib import Path
from typing import Awaitable, Callable

from playwright.async_api import Browser, BrowserContext, async_playwright
from playwright_stealth import Stealth

from config import (
    COOKIE_FILE, LOCALE, TIMEZONE,
    UA_MOBILE, VIEWPORT_MOBILE,
)

REQUIRED_COOKIES = {"c_user", "xs"}


def _normalize_cookie(c: dict) -> dict:
    """Cookie-Editor exports use lowercase 'sameSite' values that Playwright
    rejects. Strip non-Playwright fields and translate the rest.
    """
    same_site_raw = (c.get("sameSite") or "").lower()
    same_site = {"lax": "Lax", "strict": "Strict",
                 "no_restriction": "None", "none": "None",
                 "unspecified": "None", "": "None"}.get(same_site_raw, "None")
    out = {
        "name":     c["name"],
        "value":    c["value"],
        "domain":   c.get("domain", ".facebook.com"),
        "path":     c.get("path", "/"),
        "secure":   c.get("secure", True),
        "httpOnly": c.get("httpOnly", False),
        "sameSite": same_site,
    }
    if "expirationDate" in c:
        out["expires"] = int(c["expirationDate"])
    elif isinstance(c.get("expires"), (int, float)):
        out["expires"] = int(c["expires"])
    return out


def load_cookies() -> list[dict]:
    if not COOKIE_FILE.exists():
        sys.exit(f"Missing {COOKIE_FILE}. See README for cookie export steps.")
    raw = json.loads(COOKIE_FILE.read_text())
    have = {c["name"] for c in raw}
    missing = REQUIRED_COOKIES - have
    if missing:
        sys.exit(f"Cookie file is missing required keys: {missing}")
    return [_normalize_cookie(c) for c in raw]


async def open_session() -> tuple[
    Browser, BrowserContext, Callable[[], Awaitable[None]]
]:
    """Return (browser, ctx, save_cookies). Caller must close browser.

    save_cookies() writes the current context cookies back to disk so that
    rotated session tokens (xs / fr / presence) carry over to the next run.
    """
    cookies = load_cookies()
    print(f"[session] loaded {len(cookies)} cookies "
          f"({sorted({c['name'] for c in cookies})})")

    p = await async_playwright().start()
    stealth = Stealth()
    browser = await p.chromium.launch(headless=True)
    ctx = await browser.new_context(
        viewport=VIEWPORT_MOBILE,
        user_agent=UA_MOBILE,
        is_mobile=True, has_touch=True,
        locale=LOCALE,
        timezone_id=TIMEZONE,
    )
    await stealth.apply_stealth_async(ctx)
    await ctx.add_cookies(cookies)

    async def save_cookies() -> None:
        new = await ctx.cookies()
        # Re-emit in the Cookie-Editor shape so the file stays human-friendly.
        out = []
        for c in new:
            row = {
                "domain":   c.get("domain"),
                "name":     c.get("name"),
                "path":     c.get("path", "/"),
                "value":    c.get("value"),
                "secure":   c.get("secure", True),
                "httpOnly": c.get("httpOnly", False),
                "sameSite": c.get("sameSite", "None").lower(),
            }
            if "expires" in c and c["expires"] != -1:
                row["expirationDate"] = c["expires"]
            out.append(row)
        COOKIE_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2))
        print(f"[session] saved {len(out)} cookies back to {COOKIE_FILE.name}")

    return browser, ctx, save_cookies


async def dismiss_modals(page) -> None:
    """Best-effort close any login / cookie / app-promo overlay."""
    for sel in (
        'div[aria-label="Close"]',
        'div[aria-label="Đóng"]',
        'div[role="button"][aria-label="Close"]',
    ):
        try:
            await page.click(sel, timeout=1200)
            return
        except Exception:
            pass


def detect_checkpoint(url: str) -> str | None:
    """Return reason if the page redirected to a checkpoint / login wall."""
    if "/checkpoint" in url:
        return "checkpoint"
    if "/login" in url and "login.php?next=" in url:
        return "login_required"
    return None
