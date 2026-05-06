"""DIY Facebook scrape with Playwright + stealth, against m.facebook.com.

Targets:
  - Page : m.facebook.com/100063916755649
  - Group: m.facebook.com/groups/1569314343856132
"""
import asyncio
import json
import sys
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

OUT = Path(__file__).parent / "outputs"
OUT.mkdir(exist_ok=True)

TARGETS = {
    "page":  "https://m.facebook.com/100063916755649/",
    "group": "https://m.facebook.com/groups/1569314343856132/",
}

# Mobile-Safari UA matches the m.facebook.com layout the script is parsing.
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


async def scrape(label: str, url: str, headless: bool = True, scrolls: int = 5):
    print(f"\n========== {label.upper()} : {url} ==========")
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=MOBILE_UA,
            is_mobile=True,
            has_touch=True,
            locale="en-US",
        )
        page = await context.new_page()

        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(3)
        print(f"Final URL: {page.url}")

        # Dismiss any login/cookie modal if it shows up.
        for sel in [
            'div[aria-label="Close"]',
            'div[role="button"][aria-label="Close"]',
            'div[aria-label="Decline optional cookies"]',
        ]:
            try:
                await page.click(sel, timeout=1500)
                print(f"  closed modal via {sel}")
                break
            except Exception:
                pass

        for i in range(scrolls):
            await page.evaluate("window.scrollBy(0, 1800)")
            await asyncio.sleep(2)
            print(f"  scroll {i + 1}/{scrolls}")

        # Try several selectors that FB uses for post containers.
        selectors = [
            'div[role="article"]',
            'article',
            'div[data-ft]',
            'div[data-tracking-duration-id]',
        ]
        articles = []
        used = None
        for sel in selectors:
            articles = await page.query_selector_all(sel)
            if articles:
                used = sel
                break
        print(f"Found {len(articles)} elements via selector {used!r}")

        # Title of the page/group, if any.
        try:
            title = await page.title()
        except Exception:
            title = None
        print(f"Page title: {title}")

        # Save artefacts for inspection.
        html = await page.content()
        (OUT / f"pw_{label}.html").write_text(html, encoding="utf-8")
        await page.screenshot(path=str(OUT / f"pw_{label}.png"), full_page=True)

        rows = []
        for i, art in enumerate(articles[:8]):
            try:
                txt = (await art.inner_text()).strip()
            except Exception:
                txt = ""
            rows.append({"i": i, "len": len(txt), "preview": txt[:200]})
            print(f"\n--- post {i + 1} ({len(txt)} chars) ---")
            print(txt[:240])

        (OUT / f"pw_{label}.json").write_text(
            json.dumps({"url": url, "final": page.url, "title": title,
                        "selector": used, "count": len(articles), "rows": rows},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        await browser.close()
        return len(articles)


async def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    headless = "--head" not in sys.argv  # default headless; pass --head to watch
    for label, url in TARGETS.items():
        if only and only != label:
            continue
        await scrape(label, url, headless=headless)


asyncio.run(main())
