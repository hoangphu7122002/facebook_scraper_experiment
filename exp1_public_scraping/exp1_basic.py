from facebook_scraper import get_posts, _scraper

_scraper.set_user_agent(
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)
_scraper.session.headers.update({"Accept-Language": "en-US,en;q=0.9"})

PAGE = "100063916755649"   # numeric profile id from profile.php?id=...

print(f"Scraping {PAGE}...")
count = 0
for post in get_posts(PAGE, pages=10):
    count += 1
    print(f"\n--- Post {count} ---")
    print(f"Time:     {post.get('time')}")
    print(f"Text:     {(post.get('text') or '')[:150]}")
    print(f"Likes:    {post.get('likes')}")
    print(f"Comments: {post.get('comments')}")
    print(f"URL:      {post.get('post_url')}")

print(f"\nTotal: {count} posts")