"""Demo entry point — crawl the latest N posts from each target.

Pipeline per target:
    1. Open page → wait, dismiss any modal → check for checkpoint redirect.
    2. Human-like scroll until enough blocks appear or feed stalls.
    3. Harvest inner_text from candidate selectors.
    4. Parse blocks → structured Post records via fb_parser.merge_blocks.
    5. Save JSON + a screenshot for verification.

Run:
    cd demo
    python crawl.py
"""
import asyncio
import json
import re

from config import (
    TARGETS, POSTS_PER_TARGET, SCROLLS_MAX, OUT_DIR,
    DELAY_BETWEEN_SCROLLS, DELAY_AFTER_LOAD, DELAY_BETWEEN_TARGETS,
)
from fb_session import open_session, dismiss_modals, detect_checkpoint
from fb_behavior import human_scroll, sleep_random
from fb_parser import merge_blocks, post_to_dict


async def harvest_blocks(page) -> list[str]:
    """Return inner_text of each post-candidate element, deduped."""
    seen: set[str] = set()
    blocks: list[str] = []
    for sel in ("article", 'div[data-tracking-duration-id]',
                'div[role="article"]'):
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
            blocks.append(text)
        if blocks:
            return blocks
    return blocks


async def crawl_one(ctx, target: dict) -> dict:
    name, kind, url = target["name"], target["kind"], target["url"]
    print(f"\n=== {kind.upper()}: {name}  ({url}) ===")
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await sleep_random(*DELAY_AFTER_LOAD)
        await dismiss_modals(page)

        cp = detect_checkpoint(page.url)
        if cp:
            print(f"  ⚠️ stopped: {cp} (final url={page.url})")
            return {"name": name, "url": url, "error": cp,
                    "final_url": page.url, "posts": []}

        title = await page.title()
        body_top = await page.evaluate(
            "() => (document.body && document.body.innerText || '').slice(0, 200)"
        )
        locale = "vi" if re.search(r"\b(Đăng nhập|Xem thêm|bình luận)\b", body_top) else "en"
        print(f"  final url: {page.url}")
        print(f"  title:     {title}")
        print(f"  locale:    {locale}")

        await human_scroll(page, scrolls=SCROLLS_MAX,
                           delay_range=DELAY_BETWEEN_SCROLLS)

        blocks = await harvest_blocks(page)
        print(f"  harvested {len(blocks)} blocks")
        posts = merge_blocks(blocks, source=url, source_kind=kind,
                             limit=POSTS_PER_TARGET)
        print(f"  parsed {len(posts)} posts (capped at {POSTS_PER_TARGET})")

        # Save artefacts.
        await page.screenshot(path=str(OUT_DIR / f"{name}.png"), full_page=False)
        return {
            "name": name, "url": url, "kind": kind,
            "final_url": page.url, "title": title, "locale": locale,
            "posts": [post_to_dict(p) for p in posts],
        }
    finally:
        await page.close()


async def main():
    browser, ctx, save_cookies = await open_session()
    try:
        results = []
        for i, target in enumerate(TARGETS):
            results.append(await crawl_one(ctx, target))
            if i < len(TARGETS) - 1:
                # Small inter-target pause — don't burst between two pages.
                await sleep_random(*DELAY_BETWEEN_TARGETS)

        # Save per-target JSON + a combined report.
        for r in results:
            (OUT_DIR / f"{r['name']}.json").write_text(
                json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        (OUT_DIR / "summary.json").write_text(
            json.dumps(
                [{"name": r["name"], "kind": r.get("kind"),
                  "posts": len(r.get("posts", [])),
                  "error": r.get("error"),
                  "final_url": r.get("final_url")} for r in results],
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

        # Reflect any rotated session cookies back to disk.
        await save_cookies()

        print("\n=== Summary ===")
        for r in results:
            err = f" error={r['error']}" if r.get("error") else ""
            print(f"  {r['name']:30s} posts={len(r.get('posts', []))}{err}")
            for p in r.get("posts", [])[:3]:
                print(f"    - {p['author']} ({p['time_iso'] or p['time_text']}): "
                      f"likes={p['likes']} comments={p['comments']} shares={p['shares']}")
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
