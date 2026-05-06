"""Scrape a Facebook group via Apify: group info + posts."""
import json
import os
from pathlib import Path
from apify_client import ApifyClient

OUT = Path(__file__).parent / "outputs"
OUT.mkdir(exist_ok=True)

TOKEN = os.environ.get("APIFY_TOKEN")
if not TOKEN:
    raise SystemExit("Set APIFY_TOKEN env var. e.g. `export APIFY_TOKEN=apify_api_...`")
GROUP_URL = "https://www.facebook.com/groups/1569314343856132/"
POSTS_LIMIT = 20

client = ApifyClient(TOKEN)


def run(actor_id: str, run_input: dict) -> list:
    print(f"\n=== Running {actor_id} ===")
    run = client.actor(actor_id).call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    print(f"  got {len(items)} items (run id={run['id']}, status={run['status']})")
    return items


# Posts from the group (this actor also embeds group metadata in each post)
post_items = run(
    "apify/facebook-groups-scraper",
    {"startUrls": [{"url": GROUP_URL}], "resultsLimit": POSTS_LIMIT},
)

(OUT / "group_posts.json").write_text(json.dumps(post_items, ensure_ascii=False, indent=2), encoding="utf-8")

# Surface group-level info from the first post (actor embeds it per-row)
if post_items:
    first = post_items[0]
    print("\n--- Group info (from first post) ---")
    for key in ("groupTitle", "groupName", "groupId", "groupUrl", "groupMembersCount", "groupPrivacy"):
        if key in first:
            print(f"  {key}: {first[key]}")

print(f"\n--- First {min(5, len(post_items))} posts ---")
for i, post in enumerate(post_items[:5], 1):
    author = post.get("user", {}).get("name") if isinstance(post.get("user"), dict) else post.get("authorName")
    text = (post.get("text") or post.get("message") or "")[:160]
    print(f"\n[{i}] {post.get('time')} — {author}")
    print(f"    {text}")
    print(f"    likes={post.get('likesCount')} comments={post.get('commentsCount')} shares={post.get('sharesCount')}")
    print(f"    url={post.get('url')}")

print(f"\nSaved: outputs/group_posts.json ({len(post_items)} items)")
