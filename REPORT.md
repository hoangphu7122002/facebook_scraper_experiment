# Facebook scraping — experiment report

Report on three approaches to scraping a **Facebook Page** and a **Facebook Group**, with comparison and recommendations.

**Targets used throughout:**

| Type | Description | URL |
|---|---|---|
| Page | "Nguyễn Đắc Hoàng Phú international fanclub" — personal fan page, 290 followers, mostly inactive (last post 02/2024) | `https://www.facebook.com/p/Nguy%E1%BB%85n-%C4%90%E1%BA%AFc-Ho%C3%A0ng-Ph%C3%BA-international-fanclub-100063916755649/` |
| Group | "Build in Public VN" — public group, 74K members, daily activity | `https://www.facebook.com/groups/1569314343856132/` |

---

## Folder structure

```
experiment/
├── REPORT.md                    ← this file
├── fb_cookies.example.json      ← cookie template for Playwright login
├── fb_cookies.json              ← real cookies (gitignored, chmod 600)
├── .gitignore
│
├── exp1_public_scraping/        ← Experiment 1: facebook-scraper PyPI
│   └── exp1_basic.py
│
├── exp2_apify/                  ← Experiment 2: Apify managed actors
│   ├── exp2a_page.py            ← page (apify/facebook-pages-scraper + facebook-posts-scraper)
│   ├── exp2b_group.py           ← group (apify/facebook-groups-scraper)
│   └── outputs/
│       ├── page_info.json       ← 1 item: title/likes/followers/category
│       ├── posts.json           ← 20 page posts
│       └── group_posts.json     ← 20 group posts
│
└── exp3_playwright/             ← Experiment 3: Playwright DIY (4 variants)
    ├── exp3a_anon_basic.py      ← anonymous, dumps raw text per article
    ├── exp3b_anon_structured.py ← anonymous, structured JSON matching Apify schema
    ├── exp3c_login_basic.py     ← cookie session, counts articles
    ├── exp3d_login_structured.py← cookie session + locale-aware parser (vi/en)
    └── outputs/
        ├── pw_*.{html,json,png}             ← exp3a artefacts
        ├── structured_*.json                ← exp3b
        ├── login_*.{html,json,png}          ← exp3c
        └── login_structured_*.json          ← exp3d
```

---

## Experiment 1 — `facebook-scraper` (public scraping)

**Goal:** verify whether a public Page can be scraped without an account.

**Result:** ❌ **Not feasible at all.**

### What happened

1. First run: `ImportError: lxml.html.clean module is now a separate project lxml_html_clean` → fixed with `pip install lxml_html_clean`.
2. Re-run: returned `Total: 0 posts` (no error, but no data).
3. Enabled DEBUG logging → saw the library request `https://m.facebook.com/{page}/`. Facebook returned 200 OK but the body was just a block page:
   > "This browser is not supported. Use the Facebook app, tap to use a supported browser: Safari, Chrome"
4. Tried swapping the User-Agent to iPhone Safari → bypassed the block page; Facebook returned real mobile HTML (47 KB), but the HTML contained **zero `<article>`, `data-ft`, or `data-sigil` tags** — Facebook has migrated all mobile pages to a JS-rendered SPA.

### Conclusion
- The `facebook-scraper` PyPI library has been effectively dead since ~2023 and is unmaintained.
- Any HTTP-only scraper (requests + BeautifulSoup) will fail for the same reason: m.facebook.com no longer serves static content for unauthenticated users.
- **Skip this approach, move to Experiment 2.**

---

## Experiment 2 — Apify managed actors

**Goal:** compare data quality and decide whether the paid managed service is worth it.

**Result:** ✅ **Works for both Page and Group, returns clean and complete data.**

### 2a — Page (`apify/facebook-pages-scraper` + `apify/facebook-posts-scraper`)

Two actors: one returns page-info (1 record), the other returns posts (20 records).

| Field | Value |
|---|---|
| Title | Nguyễn Đắc Hoàng Phú international fanclub |
| Likes | 290 |
| Followers | 290 |
| Category | `["Page", "Health/beauty"]` |

Per-post: `time` (ISO 8601), `text`, `likes`, `comments`, `shares`, `url`, `attachments`, `legacyId`, etc.

### 2b — Group (`apify/facebook-groups-scraper`)

"Build in Public VN" → 20 posts. Schema fields differ slightly from the page actor:

| Field name | Apify Page | Apify Group |
|---|---|---|
| likes | `likes` (int) | `likesCount` (int) |
| comments | `comments` (int) | `commentsCount` (int) |
| shares | `shares` (int) | `sharesCount` (int) |
| author | (the page itself) | `user.{id, name}` |
| group meta | — | `groupTitle` only (no member count) |

### Observations
- 1–2 retries due to upstream proxy 502 errors and one transient `BLOCKED 100063916755649` from Facebook — the actor retries automatically and still returned the full 20/20 posts.
- Per-post "views" (impression count) is **not available** publicly — only Page admins can see this in Meta Business Suite.
- Full group meta (member count, privacy) requires a logged-in actor; the default returns only `groupTitle`.

### Cost
Free tier: $5 credit + monthly free credits. Each 20-post run costs roughly $0.01–0.05. More than enough for small research/testing.

---

## Experiment 3 — Playwright DIY

**Goal:** full control, zero per-request cost. Tested four variants of increasing complexity.

### 3a — Anonymous basic (raw text dump)

Launch Chromium headless with mobile UA + `playwright-stealth`, scroll a few times, dump the inner_text of each `<article>` / fallback selector.

| Target | Matching selector | Blocks captured |
|---|---|---|
| Page | `div[data-tracking-duration-id]` (fallback) | 7 (only comments/widgets, **not real posts**) |
| Group | `article` | 9 ✅ |

**Finding:** anonymous m.facebook.com in Profile/Page mode **does not show real posts** — it only shows recent activity and comments. Group view works normally.

### 3b — Anonymous structured (parser matching Apify schema)

Added a parser that converts inner_text into structured records:
```
PageInfo:  {title, category, description, url}
GroupInfo: {title, privacy, members, description, url}
Post:      {author, time_relative, text, likes, comments, shares, top_reactor}
```

Quirks handled:
- Reaction counts are rendered with **PUA Unicode glyphs** (`U+F0378` = like, `U+F0926` = comment, `U+F0927` = share in anon-EN). Must regex by glyph.
- The mobile title carries a " | Facebook" suffix → strip it.
- `/about/` for groups exposes more info than the main URL.
- "X others" / "X người khác" patterns mark the top reactor.

| Target | Output |
|---|---|
| Page | title + category ✅, posts = 0 (same reason as 3a) |
| Group | title=Build in Public VN, privacy=Public, members=74000, description ✅, 9 posts with full likes/comments/shares ✅ |

### 3c — Login basic (cookie proof-of-concept)

Export cookies from the browser (Cookie-Editor extension → JSON) → load into the Playwright context via `add_cookies()`.

⚠️ **Security:** the `xs` cookie is a full session token that can fully impersonate the account. The `fb_cookies.json` file is `chmod 600` and `.gitignore`d. After finishing, log out other sessions to invalidate it.

| Target | Anon (3a) | Login (3c) |
|---|---|---|
| Page | 0 real posts | **48 blocks** ✅ |
| Group | 9 articles | 3 blocks (logged-in mobile group view doesn't auto-load more) |

**Evidence the login took effect:** UI switched to Vietnamese, the Page's pinned 2019 post became visible, and "Bình luận dưới tên Phú" ("Comment as Phú") appeared on each block.

### 3d — Login structured + locale-aware

Combines 3b + 3c, with a parser that handles both Vietnamese and English locales:

- **Glyph codepoints differ between anon-EN and logged-VI:**
  - Like: `U+F0378` (both modes)
  - Comment: `U+F0926` (anon-EN) or `U+F0379` (logged-VI)
  - Share: `U+F0927` (anon-EN) or `U+F037A` (logged-VI)
- **Mobile logged-in splits one post into 3 divs:** header (author + date) → body (text) → footer (reactions). Required a state-machine merger.
- **Bug fixed:** the K/M/B regex was greedily capturing the 'B' from "Bình luận", reading "30 B" as 30 billion. Fix: K/M/B must be adjacent to the digits with no whitespace in between.

| Field | Page (39 posts, login) | Group (3 posts, login) |
|---|---|---|
| author | 100% | 100% |
| time_text | 100% | 100% |
| text | 90% | 100% |
| likes | 44% | 100% |
| comments | 67% | 100% |
| shares | 36% | 100% |
| top_reactor | 26% | 33% |
| post_url | 0% | 0% |

**Coverage isn't 100%** because:
- Some Page entries are "đã cập nhật ảnh đại diện" (profile-picture updates — FB activity, not real posts) → no reactions.
- A few footer blocks didn't finish rendering before scroll stopped.

**post_url = 0%** because logged-in m.facebook.com uses `data-action-id` (client-side router) instead of `<a href>`. Apify can extract URLs because it calls the GraphQL backend directly.

---

## Comparison summary

| Criterion | Exp1 — facebook-scraper | Exp2 — Apify | Exp3 — Playwright DIY |
|---|---|---|---|
| **Setup time** | 5 min (then abandoned) | 15 min | 1–2 hours |
| **Cost** | Free | $0.01–0.05/run | Free (electricity only) |
| **Page (anon)** | ❌ 0 posts | ✅ 20 posts | ❌ 0 posts |
| **Page (login)** | N/A | N/A (Apify doesn't need it) | ✅ 39 posts |
| **Group anon** | ❌ 0 posts | ✅ 20 posts | ⚠️ 9 posts (single batch) |
| **Group login** | N/A | N/A | ⚠️ 3 posts (FB doesn't load more) |
| **post_url** | N/A | ✅ | ❌ |
| **ISO timestamp** | N/A | ✅ | ❌ ("2 giờ", "Apr 29") |
| **Engagement counts** | N/A | ✅ | ⚠️ 36–100% depending on field/target |
| **Page member count / followers** | N/A | ✅ (followers, no "views") | ❌ (hidden behind login wall) |
| **Group member count** | N/A | ❌ (only groupTitle) | ✅ "74K members" |
| **Maintenance burden** | High (lib is dead) | Low (Apify handles it) | High (FB changes the DOM often) |
| **Rate-limit risk** | High | Low (proxy farm) | Medium (personal IP) |
| **ToS compliance** | Violates | Violates (but Apify absorbs the risk) | Violates + risk of account ban when using login |

---

## Practical recommendation

**By use case:**

1. **Need stability, low volume, small budget** → **Apify**. Quick setup, no DOM-change worries, has a proxy farm + GraphQL backend.

2. **Need high volume with a maintenance team** → **Playwright DIY** with a throwaway account + residential proxy.
   - Group: run anon mode (9–20 posts per scroll session)
   - Page: run with a login cookie session

3. **Need clean `post_url` or ISO timestamps** → **only Apify delivers** (because it calls GraphQL directly). Playwright DIY would have to parse relative time and click into each post to get the URL.

4. **Need legal long-term data** → **Meta's official Graph API**. Requires you to be admin of the Page/Group. Out of scope here, but it's the only sustainable path.

**Suggested hybrid strategy:**
- Apify for production data pipelines (page info + 20–50 recent posts, daily)
- Playwright DIY for deep history or specialized data needs (login session)

---

## Security checklist — do this before walking away

- [ ] **Log out all other sessions** at https://www.facebook.com/settings_and_privacy/password_and_security → "Where you're logged in" → invalidates the `xs` cookie that was copied to disk
- [ ] **Change the Facebook password** (defense in depth)
- [ ] **Rotate the Apify token** at https://console.apify.com/settings/integrations (the token was exposed in chat)
- [ ] **Verify `fb_cookies.json` is not committed to git** (already in `.gitignore`)
- [ ] **Consider using a throwaway account** for future scraping

---

## How to re-run

```bash
# Set up environment (once)
cd /Users/phunguyen/experiment
source venv/bin/activate
pip install -r requirements.txt   # if present, otherwise install packages individually

# Experiment 1 — will fail, run only to verify
python exp1_public_scraping/exp1_basic.py

# Experiment 2 — Apify
export APIFY_TOKEN=apify_api_xxx     # or hard-code in the file
python exp2_apify/exp2a_page.py      # → outputs/page_info.json + posts.json
python exp2_apify/exp2b_group.py     # → outputs/group_posts.json

# Experiment 3 — Playwright
playwright install chromium          # first time only

python exp3_playwright/exp3a_anon_basic.py        # raw dump
python exp3_playwright/exp3b_anon_structured.py   # structured (group works well)

# exp3c/3d need fb_cookies.json at the project root
cp fb_cookies.example.json fb_cookies.json
# → open the Cookie-Editor extension on facebook.com, Export as JSON, paste into the file
chmod 600 fb_cookies.json

python exp3_playwright/exp3c_login_basic.py       # verify login works
python exp3_playwright/exp3d_login_structured.py  # full structured parser
```
