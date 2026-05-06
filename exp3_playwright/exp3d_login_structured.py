"""Locale-aware structured Facebook scrape via Playwright + cookie session.

- Works for Page (logged-in only) and Group (logged-in or anonymous)
- Returns the same schema regardless of FB locale (vi or en)
- Output schema (per post):
    {author, time_text, text, likes, comments, shares,
     top_reactor, post_url, raw}
"""
import asyncio
import json
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
USE_LOGIN = "--anon" not in sys.argv

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

# Glyph codepoints observed across anon-EN and logged-VI renders.
LIKE_GLYPHS    = ("\U000f0378",)                       # heart/like
COMMENT_GLYPHS = ("\U000f0379", "\U000f0926")          # comment bubble (vi, en)
SHARE_GLYPHS   = ("\U000f037a", "\U000f0927")          # share arrow  (vi, en)
HEADER_GLYPHS  = ("\U000f212d", "\U000f3197", "\U000f312b")  # author/time markers
ALL_REACTION_GLYPHS = LIKE_GLYPHS + COMMENT_GLYPHS + SHARE_GLYPHS

# Locale-specific phrases.
SEE_MORE_RE   = re.compile(r"\.{2,3}\s*(?:Xem thêm|See more)\s*$")
COMMENT_AS_RE = re.compile(r"^(?:Bình luận dưới tên|Comment as)\b.*$", re.M)

# "X others" / "X người khác" reactor summary.
REACTOR_RE = re.compile(
    r"^(?P<who>.+?)\s+(?:and|và)\s+(?P<n>[\d.,]+\s*[KMB]?)\s+(?:others?|người khác)\b",
    re.M,
)

# Human-readable count "11 bình luận" / "30 shares".
COMMENT_TEXT_RE = re.compile(r"([\d.,]+\s*[KMB]?)\s+(?:bình luận|comments?)", re.I)
SHARE_TEXT_RE   = re.compile(r"([\d.,]+\s*[KMB]?)\s+(?:lượt chia sẻ|shares?)", re.I)

# Time tokens — accept either VI or EN forms.
TIME_RE = re.compile(
    r"‎?(\d+\s*(?:s|m|h|d|w|y|giây|phút|giờ|ngày|tuần|năm)\b"
    r"|\d{1,2}\s+tháng\s+\d{1,2}(?:,\s*\d{4})?"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{2,4}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:,\s*\d{4})?"
    r"|Yesterday|Hôm qua|Just now|Vừa xong)"
)


def parse_count(s: str) -> int | None:
    if not s:
        return None
    s = s.strip().replace(",", "").replace(" ", "")
    m = re.match(r"^([\d.]+)([KkMmBb]?)$", s)
    if not m:
        return None
    return int(float(m.group(1)) * {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(m.group(2).lower(), 1))


def has_any(text: str, glyphs: tuple[str, ...]) -> bool:
    return any(g in text for g in glyphs)


def find_count_after(text: str, glyphs: tuple[str, ...]) -> int | None:
    # K/M/B must touch the digits — no whitespace allowed — otherwise we'd
    # eat the 'B' from "Bình" and read "30 B" as 30 billion.
    for g in glyphs:
        m = re.search(re.escape(g) + r"\s*(\d+(?:[.,]\d+)?[KMBkmb]?)\b", text)
        if m:
            n = parse_count(m.group(1))
            if n is not None:
                return n
    return None


def is_header_block(text: str) -> bool:
    return has_any(text, HEADER_GLYPHS) and TIME_RE.search(text) is not None


def is_footer_block(text: str) -> bool:
    return (has_any(text, ALL_REACTION_GLYPHS)
            or REACTOR_RE.search(text) is not None
            or COMMENT_TEXT_RE.search(text) is not None)


def parse_header(text: str) -> dict:
    text = re.sub("|".join(re.escape(g) for g in HEADER_GLYPHS), "", text)
    text = text.replace("‎", "")
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    out = {"author": None, "time_text": None}
    if not lines:
        return out

    # Time may be on its own line or appended to author. Split if appended.
    time_match = TIME_RE.search(text)
    if time_match:
        out["time_text"] = time_match.group(1).strip()
        # Author = everything before the time match.
        before = text[:time_match.start()].strip()
        out["author"] = " ".join(part.strip() for part in before.split("\n") if part.strip())
    else:
        out["author"] = lines[0]
    return out


def parse_body(text: str) -> str:
    text = SEE_MORE_RE.sub("", text).strip()
    text = COMMENT_AS_RE.sub("", text).strip()
    return text


def parse_footer(text: str) -> dict:
    out = {"likes": None, "comments": None, "shares": None, "top_reactor": None}
    out["likes"]    = find_count_after(text, LIKE_GLYPHS)
    out["comments"] = find_count_after(text, COMMENT_GLYPHS)
    out["shares"]   = find_count_after(text, SHARE_GLYPHS)

    # Fallback: text-form counts ("11 bình luận", "30 lượt chia sẻ").
    if out["comments"] is None:
        m = COMMENT_TEXT_RE.search(text)
        if m:
            out["comments"] = parse_count(m.group(1))
    if out["shares"] is None:
        m = SHARE_TEXT_RE.search(text)
        if m:
            out["shares"] = parse_count(m.group(1))

    m = REACTOR_RE.search(text)
    if m:
        connector = "và" if "và" in m.group(0) else "and"
        out["top_reactor"] = f"{m.group('who').strip()} {connector} {m.group('n').strip()} người khác"
    return out


def merge_blocks(blocks: list[tuple[str, str | None]]) -> list[dict]:
    """Walk (text, post_url) pairs and emit grouped posts.

    Logged-in m.facebook.com splits a post into (header, body, footer) divs.
    Anonymous m.facebook.com puts the whole post in one <article>; treat
    that as a single block by detecting it has both header AND footer signals.
    """
    posts: list[dict] = []
    pending: dict | None = None

    def flush():
        nonlocal pending
        if pending and (pending.get("author") or pending.get("text")):
            posts.append(pending)
        pending = None

    for text, url in blocks:
        is_full = is_header_block(text) and is_footer_block(text)
        if is_full:
            # Single self-contained post.
            flush()
            post = {**parse_header(text), "text": "", **parse_footer(text),
                    "post_url": url, "raw": text}
            # Body sits between author/time and the reactor/glyph section.
            body_text = text
            for g in HEADER_GLYPHS:
                body_text = body_text.replace(g, "")
            body_text = body_text.replace("‎", "")
            tm = TIME_RE.search(body_text)
            if tm:
                body_text = body_text[tm.end():]
            # Cut at first reactor / reaction glyph.
            cut = len(body_text)
            for g in ALL_REACTION_GLYPHS:
                idx = body_text.find(g)
                if idx >= 0 and idx < cut:
                    cut = idx
            rm = REACTOR_RE.search(body_text)
            if rm and rm.start() < cut:
                cut = rm.start()
            cm = COMMENT_TEXT_RE.search(body_text)
            if cm and cm.start() < cut:
                cut = cm.start()
            body_text = body_text[:cut]
            post["text"] = parse_body(body_text)
            posts.append(post)
            continue

        if is_header_block(text):
            flush()
            pending = {**parse_header(text), "text": "",
                       "likes": None, "comments": None, "shares": None,
                       "top_reactor": None, "post_url": url, "raw": text}
            continue

        if is_footer_block(text):
            if pending is None:
                pending = {"author": None, "time_text": None, "text": "",
                           "likes": None, "comments": None, "shares": None,
                           "top_reactor": None, "post_url": url, "raw": ""}
            pending.update(parse_footer(text))
            pending["raw"] += "\n" + text
            flush()
            continue

        # Body block.
        if pending is None:
            continue
        body = parse_body(text)
        if body:
            pending["text"] = (pending["text"] + "\n" + body).strip() if pending["text"] else body
        if not pending.get("post_url") and url:
            pending["post_url"] = url
        pending["raw"] += "\n" + text

    flush()
    return posts


# ---- Cookie loader (mirrors exp6) ----
def load_cookies() -> list[dict]:
    if not COOKIE_FILE.exists():
        return []
    cookies = json.loads(COOKIE_FILE.read_text())
    out = []
    for c in cookies:
        same_site_raw = (c.get("sameSite") or "").lower()
        same_site = {"lax": "Lax", "strict": "Strict",
                     "no_restriction": "None", "unspecified": "None",
                     "": "None", "none": "None"}.get(same_site_raw, "None")
        clean = {
            "name": c["name"], "value": c["value"],
            "domain": c.get("domain", ".facebook.com"),
            "path": c.get("path", "/"),
            "secure": c.get("secure", True),
            "httpOnly": c.get("httpOnly", False),
            "sameSite": same_site,
        }
        if "expirationDate" in c:
            clean["expires"] = int(c["expirationDate"])
        elif isinstance(c.get("expires"), (int, float)):
            clean["expires"] = int(c["expires"])
        out.append(clean)
    return out


async def harvest(page) -> list[tuple[str, str | None]]:
    """Return [(inner_text, post_url)] for each candidate block.

    NOTE: logged-in m.facebook.com renders posts without anchor href — clicks go
    through data-action-id router. So post_url is usually None when using
    cookie session. Anonymous m.facebook.com group view DOES expose hrefs.
    """
    pairs: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for sel in ('article', 'div[role="article"]', 'div[data-tracking-duration-id]'):
        elements = await page.query_selector_all(sel)
        if not elements:
            continue
        for el in elements:
            try:
                text = (await el.inner_text()).strip()
            except Exception:
                continue
            if not text or text in seen:
                continue
            seen.add(text)
            href = await el.evaluate(
                """(node) => {
                    const a = node.querySelector(
                        'a[href*=\"/posts/\"], a[href*=\"/permalink\"], a[href*=\"story_fbid=\"], a[href*=\"pfbid0\"], a[href*=\"/videos/\"]'
                    );
                    return a ? a.href : null;
                }"""
            )
            pairs.append((text, href))
        if pairs:
            return pairs
    return pairs


async def auto_scroll(page, n: int = 8):
    last_height = 0
    stalled = 0
    for _ in range(n):
        await page.evaluate("window.scrollBy(0, 1800)")
        await asyncio.sleep(1.8)
        h = await page.evaluate("() => document.body.scrollHeight")
        if h == last_height:
            stalled += 1
            if stalled >= 3:
                break
        else:
            stalled = 0
            last_height = h


async def dismiss_modal(page):
    for sel in ('div[aria-label="Close"]', 'div[aria-label="Đóng"]'):
        try:
            await page.click(sel, timeout=1200)
            return
        except Exception:
            pass


async def scrape(ctx, label: str, url: str) -> dict:
    print(f"\n========== {label} : {url} ==========")
    page = await ctx.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(2.5)
    await dismiss_modal(page)
    body_top = await page.evaluate(
        "() => (document.body && document.body.innerText || '').slice(0, 400)"
    )
    locale = "vi" if re.search(r"\b(Đăng nhập|Xem thêm|bình luận)\b", body_top) else "en"
    print(f"  locale: {locale}, final url: {page.url}")

    await auto_scroll(page, n=20)
    blocks = await harvest(page)
    print(f"  harvested {len(blocks)} blocks")
    posts = merge_blocks(blocks)
    posts = [p for p in posts if p.get("author") or p.get("text")]
    print(f"  parsed {len(posts)} posts")
    (OUT / f"login_structured_{label}.json").write_text(
        json.dumps({"url": url, "final": page.url, "locale": locale,
                    "posts": posts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for i, p in enumerate(posts[:5], 1):
        print(f"\n  [{i}] {p['author']} ({p['time_text']})")
        print(f"      {(p['text'] or '')[:140]}")
        print(f"      likes={p['likes']} comments={p['comments']} shares={p['shares']}")
        print(f"      url={p['post_url']}")
    return {"label": label, "n_blocks": len(blocks), "n_posts": len(posts),
            "locale": locale}


async def main():
    cookies = load_cookies() if USE_LOGIN else []
    print(f"Cookies: {len(cookies)} ({'LOGGED IN' if cookies else 'ANON'})")

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=MOBILE_UA, is_mobile=True, has_touch=True, locale="en-US",
        )
        if cookies:
            await ctx.add_cookies(cookies)

        results = []
        for label, url in [("page", PAGE_URL), ("group", GROUP_URL)]:
            results.append(await scrape(ctx, label, url))
        await browser.close()

    print("\n=== Summary ===")
    for r in results:
        print(f"  {r['label']:6s}  locale={r['locale']}  blocks={r['n_blocks']}  posts={r['n_posts']}")


asyncio.run(main())
