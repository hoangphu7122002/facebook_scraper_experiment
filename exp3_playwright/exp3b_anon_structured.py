"""Playwright scraper that returns structured data matching Apify schema.

Outputs:
  page_info  -> {title, category, description, url}
  group_info -> {title, privacy, members, description, url}
  post       -> {author, time_relative, text, likes, comments, shares,
                 top_reactor, post_url}
"""
import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

OUT = Path(__file__).parent / "outputs"
OUT.mkdir(exist_ok=True)

PAGE_URL  = "https://m.facebook.com/100063916755649/"
GROUP_URL = "https://m.facebook.com/groups/1569314343856132/"

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

LIKE_GLYPH    = "\U000f0378"
COMMENT_GLYPH = "\U000f0926"
SHARE_GLYPH   = "\U000f0927"
CONTENT_LEAD_GLYPHS = ("\U000f312b", "\U000f3197", "\U000f212d")  # body/time markers
REACTION_GLYPHS = (LIKE_GLYPH, COMMENT_GLYPH, SHARE_GLYPH)


def parse_count(s: str) -> int | None:
    """'74K' -> 74000, '1.2M' -> 1200000, '57' -> 57."""
    if not s:
        return None
    s = s.strip().replace(",", "")
    m = re.match(r"^([\d.]+)\s*([KkMmBb]?)$", s)
    if not m:
        return None
    n = float(m.group(1))
    mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(m.group(2).lower(), 1)
    return int(n * mult)


def parse_post_text(inner: str) -> dict:
    """Extract structured fields from an article's inner_text."""
    lines = [l for l in (line.strip() for line in inner.split("\n")) if l]

    out = {"author": None, "time_relative": None, "text": "",
           "likes": None, "comments": None, "shares": None,
           "top_reactor": None}
    if not lines:
        return out

    out["author"] = lines[0]

    # Line 2 typically: "2h" or "Apr 29" with trailing icon glyphs.
    if len(lines) >= 2:
        time_match = re.match(r"^([A-Za-z]{3}\s*\d{1,2}|\d+[smhdwy]|\d{1,2}\s*[A-Za-z]+\s*\d{2,4}|Yesterday)",
                              lines[1])
        if time_match:
            out["time_relative"] = time_match.group(1).strip()

    # Reactions via glyph patterns. Like icon is followed by NEWLINE then count;
    # comment/share icons are followed by space then count.
    for glyph, key in [(LIKE_GLYPH, "likes"),
                       (COMMENT_GLYPH, "comments"),
                       (SHARE_GLYPH, "shares")]:
        m = re.search(re.escape(glyph) + r"\s*([\d.,]+\s*[KMB]?)", inner)
        if m:
            out[key] = parse_count(m.group(1))

    # Top reactor line: "Quốc Sinh and 100 others"
    m = re.search(r"^([^\n]+?)\s+and\s+([\d.,KMB]+)\s+others?\s*$", inner, re.M)
    if m:
        out["top_reactor"] = f"{m.group(1)} and {m.group(2)} others"

    # Body text = everything between author/time line and the first reactor/glyph hit.
    body_lines = []
    skip_first = 2  # author + time
    for line in lines[skip_first:]:
        if re.match(r".*\s+and\s+[\d.,KMB]+\s+others?\s*$", line):
            break
        if any(g in line for g in REACTION_GLYPHS):
            break
        if re.fullmatch(r"[+]\d+", line):
            continue
        # Drop pure-glyph marker lines.
        stripped = line
        for g in CONTENT_LEAD_GLYPHS:
            stripped = stripped.replace(g, "")
        if not stripped.strip():
            continue
        body_lines.append(stripped.strip())
    text = "\n".join(body_lines)
    text = re.sub(r"\.\.\.\s*See more\s*$", "", text).strip()
    out["text"] = text
    return out


def has_engagement(post: dict) -> bool:
    return (post.get("likes") is not None
            or post.get("comments") is not None
            or post.get("shares") is not None
            or post.get("top_reactor") is not None)


async def auto_scroll(page, scrolls: int):
    for i in range(scrolls):
        await page.evaluate("window.scrollBy(0, 1800)")
        await asyncio.sleep(2.0)


async def open_browser(p):
    browser = await p.chromium.launch(headless=True)
    ctx = await browser.new_context(
        viewport={"width": 390, "height": 844},
        user_agent=MOBILE_UA, is_mobile=True, has_touch=True, locale="en-US",
    )
    return browser, ctx


async def dismiss_modal(page):
    for sel in ['div[aria-label="Close"]',
                'div[role="button"][aria-label="Close"]']:
        try:
            await page.click(sel, timeout=1200)
            return
        except Exception:
            pass


async def collect_posts(page, *, require_engagement: bool = False) -> list[dict]:
    """Try several selectors. If require_engagement, drop entries without
    reactions (filters out comments/widgets on profile pages)."""
    seen_text: set[str] = set()
    posts: list[dict] = []
    for sel in ['article', 'div[data-tracking-duration-id]', 'div[role="article"]']:
        elements = await page.query_selector_all(sel)
        if not elements:
            continue
        for el in elements:
            try:
                inner = (await el.inner_text()).strip()
            except Exception:
                continue
            if not inner or inner in seen_text:
                continue
            seen_text.add(inner)
            parsed = parse_post_text(inner)
            if require_engagement and not has_engagement(parsed):
                continue
            parsed["raw"] = inner
            posts.append(parsed)
        if posts:
            break
    return posts


async def scrape_page(p, url: str) -> dict:
    browser, ctx = await open_browser(p)
    page = await ctx.new_page()
    info: dict = {"url": url}

    # 1) /about for header info (category, description).
    about_url = url.rstrip("/") + "/about/"
    await page.goto(about_url, wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(2.5)
    await dismiss_modal(page)
    body = await page.evaluate("() => document.body.innerText")
    info["title"] = await page.title()
    info["title"] = info["title"].replace("Profile for ", "").strip()

    # Category appears as a line starting with the category-icon glyph.
    m = re.search(r"\U000f30d0\s*([^\n]+)", body)
    if m:
        info["category"] = m.group(1).strip()
    # Description: between title section and "Follow" or "All\nPhotos".
    desc_m = re.search(r"(Đây là page[^\n]+(?:\n[^\n]+){0,4})", body)
    if desc_m:
        info["description"] = desc_m.group(1).strip()

    # 2) main feed for posts. Filter out comment widgets that share the same
    # selector but have no engagement counts.
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(2.5)
    await dismiss_modal(page)
    await auto_scroll(page, scrolls=6)
    info["posts"] = await collect_posts(page, require_engagement=True)
    await browser.close()
    return info


async def scrape_group(p, url: str) -> dict:
    browser, ctx = await open_browser(p)
    page = await ctx.new_page()
    info: dict = {"url": url}

    # 1) /about page: deterministic source for privacy/members/description.
    about_url = url.rstrip("/") + "/about/"
    await page.goto(about_url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_selector("body", timeout=15000)
    await asyncio.sleep(3)
    await dismiss_modal(page)
    body = await page.evaluate(
        "() => (document.body && document.body.innerText) || ''"
    )
    title = (await page.title()).strip()
    info["title"] = re.sub(r"\s*\|\s*Facebook\s*$", "", title)

    if re.search(r"Public group", body, re.I):
        info["privacy"] = "Public"
    elif re.search(r"Private group", body, re.I):
        info["privacy"] = "Private"
    members_m = re.search(r"([\d.]+\s*[KMB]?)\s*\n?\s*members", body, re.I)
    if members_m:
        info["members"] = parse_count(members_m.group(1).replace(" ", ""))
    desc_m = re.search(r"About this group\s*\n(.+?)(?:\.\.\.\s*See more|\nLoading|\nSee less|\n[A-Z]\w+ \w+\n\d+[smhdwy])",
                       body, re.S)
    if desc_m:
        info["description"] = desc_m.group(1).strip()

    # 2) main feed for posts.
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(2.5)
    await dismiss_modal(page)
    await auto_scroll(page, scrolls=6)
    info["posts"] = await collect_posts(page)
    await browser.close()
    return info


async def main():
    async with Stealth().use_async(async_playwright()) as p:
        page_info = await scrape_page(p, PAGE_URL)
        group_info = await scrape_group(p, GROUP_URL)

    (OUT / "structured_page.json").write_text(
        json.dumps(page_info, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "structured_group.json").write_text(
        json.dumps(group_info, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n========== PAGE ==========")
    print(f"Title:       {page_info.get('title')}")
    print(f"Category:    {page_info.get('category')}")
    print(f"Description: {page_info.get('description')}")
    print(f"Posts:       {len(page_info.get('posts', []))}")
    for i, post in enumerate(page_info.get("posts", [])[:5], 1):
        print(f"\n  [{i}] {post['author']} ({post['time_relative']})")
        print(f"      {post['text'][:140]}")
        print(f"      likes={post['likes']} comments={post['comments']} shares={post['shares']} top={post['top_reactor']}")

    print("\n========== GROUP ==========")
    print(f"Title:       {group_info.get('title')}")
    print(f"Privacy:     {group_info.get('privacy')}")
    print(f"Members:     {group_info.get('members')}")
    print(f"Description: {group_info.get('description')}")
    print(f"Posts:       {len(group_info.get('posts', []))}")
    for i, post in enumerate(group_info.get("posts", [])[:5], 1):
        print(f"\n  [{i}] {post['author']} ({post['time_relative']})")
        print(f"      {post['text'][:140]}")
        print(f"      likes={post['likes']} comments={post['comments']} shares={post['shares']} top={post['top_reactor']}")


asyncio.run(main())
