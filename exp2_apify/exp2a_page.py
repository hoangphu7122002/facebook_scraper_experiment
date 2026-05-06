"""Scrape a Facebook page via Apify: page info, posts, followers."""
import json
import os
from pathlib import Path
from apify_client import ApifyClient

OUT = Path(__file__).parent / "outputs"
OUT.mkdir(exist_ok=True)

TOKEN = os.environ.get("APIFY_TOKEN")
if not TOKEN:
    raise SystemExit("Set APIFY_TOKEN env var. e.g. `export APIFY_TOKEN=apify_api_...`")
PAGE_URL = (
    "https://www.facebook.com/p/"
    "Nguy%E1%BB%85n-%C4%90%E1%BA%AFc-Ho%C3%A0ng-Ph%C3%BA-international-fanclub-"
    "100063916755649/"
)
POSTS_LIMIT = 20

client = ApifyClient(TOKEN)


def run(actor_id: str, run_input: dict) -> list:
    print(f"\n=== Running {actor_id} ===")
    run = client.actor(actor_id).call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    print(f"  got {len(items)} items (run id={run['id']}, status={run['status']})")
    return items


# 1) Page info + follower / like counts
page_items = run(
    "apify/facebook-pages-scraper",
    {"startUrls": [{"url": PAGE_URL}]},
)

# 2) Posts
post_items = run(
    "apify/facebook-posts-scraper",
    {"startUrls": [{"url": PAGE_URL}], "resultsLimit": POSTS_LIMIT},
)

(OUT / "page_info.json").write_text(json.dumps(page_items, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "posts.json").write_text(json.dumps(post_items, ensure_ascii=False, indent=2), encoding="utf-8")

print("\n--- Page info summary ---")
for p in page_items:
    print(f"Title:     {p.get('title') or p.get('pageName')}")
    print(f"Likes:     {p.get('likes')}")
    print(f"Followers: {p.get('followers')}")
    print(f"Category:  {p.get('categories') or p.get('category')}")
    print(f"URL:       {p.get('url') or p.get('pageUrl')}")

print(f"\n--- First {min(5, len(post_items))} posts ---")
for i, post in enumerate(post_items[:5], 1):
    print(f"\n[{i}] {post.get('time') or post.get('timestamp')}")
    text = (post.get("text") or post.get("message") or "")[:160]
    print(f"    {text}")
    print(f"    likes={post.get('likes')} comments={post.get('comments')} shares={post.get('shares')}")
    print(f"    url={post.get('url') or post.get('postUrl')}")

print(f"\nSaved: outputs/page_info.json ({len(page_items)} item), outputs/posts.json ({len(post_items)} items)")
