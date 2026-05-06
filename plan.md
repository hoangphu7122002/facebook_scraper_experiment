# Test account for facebook

[Solution facebook scraping](https://www.notion.so/Solution-facebook-scraping-3581434f8325807d8a8ec9b1e55e83ca?pvs=21)

# Facebook Crawl & Subscribe — Experiment Plan (Revised)

## Phase 0: Environment Setup (10 min, one-time)

```bash
mkdir fb-research && cd fb-research

python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

pip install facebook-scraper apify-client playwright playwright-stealth \
            feedparser requests fastapi uvicorn

playwright install chromium

docker --version   # for RSSHub later
```

Pick a target page for testing — `nintendo`, `BBCNews`, or any public page you care about.

---

## Phase 1: Setup Facebook App + Webhook Test Page ⭐

**Goal**: Prepare the FB App and a Page (owned by your real account) that you'll use in Experiment 4. Doing this first means everything is ready when you reach the webhook step.

> ✅ **Why skip Test Users**: Test User creation is currently disabled on Meta's side. Using your real account to admin a dedicated Test Page is the standard alternative — there's zero risk because you're only posting to a page you own, and webhook events only fire for that one page.
> 

### Step 1.1: Create a Facebook App (skip if already done)

1. Go to [developers.facebook.com](https://developers.facebook.com/) → **My Apps** → **Create App**
2. Use case: **"Other"** → Next
3. Type: **"Business"** → Next
4. App name: e.g., `research_test`
5. Contact email: your email
6. Click **Create App**

Note your **App ID** (visible at the top of the dashboard).

### Step 1.2: Get the App Secret (you'll need it later)

1. Dashboard → **App settings** → **Basic**
2. Field "App Secret" → click **Show** → enter password → copy
3. Save to `secrets.txt`:

```
APP_ID=952756700940510
APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> ⚠️ Never commit `secrets.txt` to git. Add it to `.gitignore`.
> 

### Step 1.3: Create a dedicated Test Page using your real account

1. Open a normal browser (where your real Facebook is logged in)
2. Go to facebook.com
3. Top-right menu → **Pages** → **Create new Page**
4. Page name: `Webhook Research Test` (or anything)
5. Category: any (e.g., "Software" or "Just for Fun")
6. Click **Create Page**

→ A new Page is created and you are the admin. Note the **Page ID** (visible in the URL like `facebook.com/profile.php?id=XXXXXXXX` or in the page's About section).

### Step 1.4: Get the Page Access Token

1. Open [Graph API Explorer](https://developers.facebook.com/tools/explorer/)
2. Top-right: select your app (`research_test`)
3. **User or Page**: select **"Get User Access Token"**
4. Click the gear icon → check these permissions:
    - `pages_show_list`
    - `pages_read_engagement`
    - `pages_manage_metadata`
    - `pages_manage_posts`
5. Click **Generate Access Token** → grant permissions in the popup
6. After getting the User Token, in the query box type:
    
    ```
    me/accounts
    ```
    
7. Click **Submit**

Response contains all your pages with their tokens:

```json
{
  "data": [
    {
      "access_token": "EAAxxxxxxxxxxxx",   ← Page Access Token (save!)
      "name": "Webhook Research Test",
      "id": "1234567890",                  ← Page ID (save!)
      "category": "Software"
    }
  ]
}
```

**Save to `secrets.txt`**:

```
APP_ID=952756700940510
APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PAGE_ID=1234567890
PAGE_ACCESS_TOKEN=EAAxxxxxxxxxxxx
```

> 💡 The Page Access Token from `me/accounts` is **long-lived** (no expiration) by default — much better than the User Token.
> 

✅ Phase 1 complete.

---

## Experiment 1: Validate Public Scraping (30 min)

**Goal**: Confirm you can extract data from a public page without any account → fastest signal whether scraping is feasible.

### Step 1.1: Basic scraper

`exp1_basic.py`:

```python
from facebook_scraper import get_posts

PAGE = "nintendo"   # change to your target page

print(f"Scraping {PAGE}...")
count = 0
for post in get_posts(PAGE, pages=2):
    count += 1
    print(f"\n--- Post {count} ---")
    print(f"Time:     {post.get('time')}")
    print(f"Text:     {(post.get('text') or '')[:150]}")
    print(f"Likes:    {post.get('likes')}")
    print(f"Comments: {post.get('comments')}")
    print(f"URL:      {post.get('post_url')}")

print(f"\nTotal: {count} posts")
```

```bash
python exp1_basic.py
```

### Step 1.2: Evaluate

- ✅ **10–30 posts with full data** → great
- ⚠️ **0–3 posts or text cut off** → library lagging behind FB updates → skip to Exp 2
- ❌ **TemporarilyBanned / 403** → IP flagged, wait 24h or change network

### Step 1.3 (optional): Test with public group

```python
from facebook_scraper import get_group_info, get_posts

GROUP_ID = "your_public_group_id"

info = get_group_info(GROUP_ID)
print(info)

for post in get_posts(group=GROUP_ID, pages=2):
    print(post.get("text", "")[:100])
```

**Decision**: Library works well → can stop here for simple cases. Otherwise → Exp 2.

---

## Experiment 2: Apify Managed Service (1 hour)

**Goal**: Compare data quality and decide if managed service is worth the cost.

### Step 2.1: Sign up

1. [apify.com](https://apify.com/) → Sign up (Google/GitHub)
2. Free plan: **$5 credit** + monthly free credits
3. Settings → Integrations → copy **Personal API token**

### Step 2.2: Test the Actor in the UI first

1. Apify Console → **Store** → search **"Facebook Pages Scraper"**
2. Click **"Try for free"**
3. Set:
    - `startUrls`: `https://www.facebook.com/nintendo`
    - `resultsLimit`: 20
4. Click **Start** → wait 1–2 min
5. Tab **Storage** → view JSON

### Step 2.3: Automate

`exp2_apify.py`:

```python
from apify_client import ApifyClient
import json

TOKEN = "YOUR_APIFY_TOKEN"
client = ApifyClient(TOKEN)

run_input = {
    "startUrls": [{"url": "https://www.facebook.com/nintendo"}],
    "resultsLimit": 20,
}

print("Starting actor...")
run = client.actor("apify/facebook-pages-scraper").call(run_input=run_input)
print(f"Run finished: {run['id']}")

items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
print(f"Got {len(items)} posts")

with open("apify_output.json", "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False, indent=2)

for post in items[:3]:
    print(post.get("text", "")[:100])
```

### Step 2.4: Check cost

Console → **Billing** → see credits per run. Estimate at scale.

**Decision**: Quality good + price OK → use Apify in production. Too expensive → continue to Exp 3.

---

## Experiment 3: Playwright DIY (2 hours, optional)

**Goal**: Full control, zero per-request cost.

### Step 3.1: Basic scraper, no login

`exp3_playwright.py`:

```python
import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

async def scrape(url):
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"),
        )
        page = await context.new_page()

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        try:
            await page.click('div[aria-label="Close"]', timeout=3000)
        except:
            pass

        for i in range(3):
            await page.evaluate("window.scrollBy(0, 1500)")
            await asyncio.sleep(2)
            print(f"Scroll {i+1}/3")

        articles = await page.query_selector_all('div[role="article"]')
        print(f"Found {len(articles)} articles")

        for i, art in enumerate(articles[:5]):
            text = await art.inner_text()
            print(f"\n--- Post {i+1} ---")
            print(text[:200])

        input("\nPress Enter to close browser...")
        await browser.close()

asyncio.run(scrape("https://www.facebook.com/nintendo"))
```

### Step 3.2: Try mobile FB

Switch URL to `https://m.facebook.com/nintendo` — cleaner DOM, fewer login walls.

### Step 3.3: (Optional) Add residential proxy

```python
context = await browser.new_context(
    proxy={
        "server": "http://gate.decodo.com:7000",
        "username": "your_username",
        "password": "your_password",
    },
)
```

---

## Experiment 4: Real-time Webhook (2 hours)

**Goal**: Receive push notifications when your Test Page (from Phase 1) gets new posts/comments.

### Step 4.1: Build webhook server

`webhook_server.py`:

```python
from fastapi import FastAPI, Request, HTTPException
import uvicorn
import json

app = FastAPI()
VERIFY_TOKEN = "my_test_token_123"   # any random string

@app.get("/webhook")
async def verify(request: Request):
    params = request.query_params
    if (params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == VERIFY_TOKEN):
        print("✅ Webhook verified!")
        return int(params.get("hub.challenge"))
    raise HTTPException(403)

@app.post("/webhook")
async def receive(request: Request):
    body = await request.json()
    print("\n🔔 EVENT RECEIVED:")
    print(json.dumps(body, indent=2, ensure_ascii=False))
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

```bash
python webhook_server.py
```

### Step 4.2: Expose via ngrok

In a separate terminal:

```bash
# Install ngrok: https://ngrok.com/download
ngrok http 8000
```

Copy the HTTPS URL like `https://xxxx-xxxx.ngrok-free.app` (keep ngrok running).

### Step 4.3: Configure webhook in App Dashboard

1. App Dashboard → left sidebar → **Webhooks** (or "Sản phẩm" → Add → Webhooks)
2. Subscribe to object: select **Page**
3. Click **"Subscribe to this object"**:
    - Callback URL: `https://xxxx-xxxx.ngrok-free.app/webhook`
    - Verify Token: `my_test_token_123` (must match code)
4. Click **"Verify and Save"** → terminal must print `✅ Webhook verified!`
5. After verification → subscribe fields → check **`feed`** (new posts + comments)

### Step 4.4: Subscribe your Test Page to the app

Use `PAGE_ID` and `PAGE_ACCESS_TOKEN` from Phase 1:

```bash
curl -X POST "https://graph.facebook.com/v25.0/{PAGE_ID}/subscribed_apps" \
  -d "subscribed_fields=feed" \
  -d "access_token={PAGE_ACCESS_TOKEN}"
```

Expected: `{"success": true}`

### Step 4.5: Trigger an event

In your normal browser (logged in as your real account):

1. Go to your "Webhook Research Test" page
2. Post a status: "Hello webhook"
3. Watch `webhook_server.py` terminal — event JSON should appear within seconds

✅ Webhook flow validated.

> 💡 You can also test by commenting on the test post — `feed` field covers comments too.
> 

---

## Experiment 5: RSSHub Monitoring (1 hour)

**Goal**: Monitor pages you don't own, no Graph API needed.

### Step 5.1: Run RSSHub

```bash
docker run -d --name rsshub -p 1200:1200 \
  --restart=always \
  diygod/rsshub:chromium-bundled
```

### Step 5.2: Test feed

```bash
curl "http://localhost:1200/facebook/page/nintendo"
```

Should return RSS XML.

### Step 5.3: Polling + notify

`exp5_monitor.py`:

```python
import feedparser
import requests
import time
import json
import os

FEEDS = [
    "http://localhost:1200/facebook/page/nintendo",
]
SEEN_FILE = "seen.json"
INTERVAL = 300

seen = set()
if os.path.exists(SEEN_FILE):
    with open(SEEN_FILE) as f:
        seen = set(json.load(f))

def notify(entry):
    print(f"\n🆕 NEW POST: {entry.title}")
    print(f"   {entry.link}")

def save_seen():
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

while True:
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if entry.id not in seen:
                    notify(entry)
                    seen.add(entry.id)
            save_seen()
        except Exception as e:
            print(f"Error {url}: {e}")
    print(f"Sleeping {INTERVAL}s...")
    time.sleep(INTERVAL)
```

Run, leave for 30+ minutes, watch new posts appear.

---

## Final Comparison Table

| Experiment | Data Quality | Setup Time | Cost / 1K posts | Stability |
| --- | --- | --- | --- | --- |
| Exp 1: facebook-scraper | ? | low | $0 | ? |
| Exp 2: Apify | ? | low | ~$1–5 | high |
| Exp 3: Playwright | ? | high | $0 + proxy | medium |
| Exp 4: Graph webhook | official | medium | $0 | high |
| Exp 5: RSSHub | medium | low | server $5/mo | medium |

---

## Recommended Order

1. **Now (~15 min)**: Phase 0 — environment setup
2. **Now (~15 min)**: Phase 1 — App secret + Test Page + Page Access Token
3. **Next (~30 min)**: Experiment 1 — public scrape validation
4. **Then (~1 hour)**: Experiment 2 — Apify
5. **Then (~2 hours)**: Experiment 4 — Webhook (uses Phase 1 setup)
6. **Then (~1 hour)**: Experiment 5 — RSSHub monitoring
7. **Optional (~2 hours)**: Experiment 3 — Playwright DIY

**Total focused time**: ~5 hours for the recommended path.

---

Start with **Phase 1 Steps 1.2 → 1.4** since you already have the App. When you have `PAGE_ID` and `PAGE_ACCESS_TOKEN` saved, you're ready for Experiment 1. Paste any errors here and I'll debug.