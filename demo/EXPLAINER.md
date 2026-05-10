# Demo Facebook scraper — full explainer

This document explains (a) what each file does, (b) the end-to-end flow, and
(c) **why this approach is safe at demo scale** (won't get cookies invalidated
or the account banned).

> Read alongside [knowledge.md](../knowledge.md) in the parent folder — that's
> the theoretical reference for Facebook's 6-layer detection stack. This doc
> is the practical application.

---

## Part 1 — Architecture & files

```
demo/
├── config.py        ← target list + runtime params (UA, viewport, delays)
├── fb_session.py    ← cookie loader, browser context, save cookies back
├── fb_behavior.py   ← human-like scroll (random delay, smooth, mouse jitter)
├── fb_time.py       ← parse "2 giờ" / "Apr 29" / "3 tháng 1, 2019" → ISO
├── fb_parser.py     ← parse a post container's text → struct Post
├── crawl.py         ← main entry: glues everything together
├── outputs/         ← JSON results + screenshots
├── README.md        ← short quick-start
└── EXPLAINER.md     ← (this file)
```

### `config.py` — *centralized constants*

All parameters that might change between runs live here, so other modules
don't need to know about file layout or magic numbers. Highlights:

- **`TARGETS`**: list of URLs to crawl. Adding a new Page later = one dict
  here, no code changes elsewhere.
- **`POSTS_PER_TARGET = 5`**: cap per target. Kept low so FB doesn't classify
  this run as "heavy bot scraping".
- **`UA_MOBILE` + `VIEWPORT_MOBILE` + `LOCALE` + `TIMEZONE`**: **these four
  must be consistent.** If UA claims "iPhone" but viewport is 1920×1080,
  Facebook flags the mismatch immediately (knowledge.md Layer 4).
- **Random delay ranges** (`DELAY_AFTER_LOAD`, `DELAY_BETWEEN_SCROLLS`...):
  `(min, max)` tuples so each sleep picks a different value. FB's behavioral
  model dislikes uniform timing.

### `fb_session.py` — *session management*

Three responsibilities:

1. **Load cookies from `fb_cookies.json`** (lives in the parent folder,
   gitignored, chmod 600). Cookies are exported manually via the Cookie-Editor
   browser extension on a real browser session.
2. **Normalize cookies**: Cookie-Editor exports use lowercase
   `sameSite: "no_restriction"` / `"lax"`, but Playwright only accepts
   `"None"` / `"Lax"` / `"Strict"` (Pascal case). `_normalize_cookie` does
   the translation.
3. **Build the browser context** with stealth + a mobile profile, inject
   cookies into it.
4. **`save_cookies()`**: at the end of the run, write current cookies back to
   disk. This matters because FB rotates `xs` / `fr` / `presence` every few
   hours — without saving, the next run uses stale cookies that may already
   be invalidated.
5. **`detect_checkpoint(url)`**: detect redirect to `/checkpoint` or `/login`.
   If hit, **stop immediately** instead of continuing — pushing further only
   adds more flag signal.

### `fb_behavior.py` — *human-like browsing*

Knowledge.md Layer 5: FB has ML models that catch bots by uniform scrolling /
zero-jitter clicks / 24-7 activity. This module dampens those signals:

- **`human_scroll(page, scrolls, delay_range)`**:
  - Each iteration scrolls a **random** 700-1500 px (not the same each time)
  - Uses `behavior: 'smooth'` (CSS smooth scroll) instead of jumping — looks
    like a finger swipe rather than a programmatic anchor jump
  - **Random sleep** 1.8-3.6 s after the scroll to "read"
  - **30% chance** per iteration the mouse moves to a random spot (with a
    `steps` param so the path is curved, not linear)
  - **Stall detection**: if 3 consecutive iterations don't grow `scrollHeight`,
    break early. Avoids spinning on a feed that has stopped loading.

### `fb_time.py` — *time parser*

Facebook renders time strings **differently per locale + post age**:
- "2 giờ" / "1 ngày" / "Vừa xong" (vi-VN)
- "2h" / "1d" / "Just now" (en-US)
- "3 tháng 1, 2019" (vi date — note Vietnamese is day-month-year)
- "Apr 29" / "Apr 29, 2024" (en date)

`parse_relative(text)` tries each pattern in turn and returns an **ISO 8601
string** so downstream code can sort/compare cleanly. If no pattern matches,
returns `None` (better to admit ignorance than guess wrong).

Important detail: if "Apr 29" is parsed but it would land in the future,
fall back to the previous year — FB doesn't post in the future.

### `fb_parser.py` — *post content parser*

This is the **trickiest** part. Mobile FB renders each post as
**3 sibling `div` containers**:

```
[1] Header  ← author + relative time + post-marker glyphs (3 PUA Unicode chars)
[2] Body    ← text + "... See more" + media markers
[3] Footer  ← reactor summary + reaction counts (like/comment/share glyphs)
```

Sometimes (anonymous group view, or short posts) all three live in a single
block.

#### Block classification

```
_is_header_block  → time present in first 120 chars, no reaction signals
_is_footer_block  → reaction glyph or "X others" / "X bình luận" present
_is_full_block    → has both → one whole post in one block
```

The reason **time is only searched in the first 120 chars**
(`HEADER_PREFIX_LEN`): if we searched the whole block, phrases like
"10 năm kinh nghiệm" ("10 years of experience") deep in body text would be
mistaken for a timestamp.

#### Reaction counts — **PUA Unicode glyphs**

FB doesn't render reactions as plain text like "❤" or "👍" — they use an
**icon font with codepoints in the Private Use Area** (U+F0378, U+F0379…).
Each locale + each mode (anon vs login) uses a different codepoint:

| Icon | EN anonymous | VI logged-in |
|---|---|---|
| Like | `U+F0378` | `U+F0378` (same) |
| Comment | `U+F0926` | `U+F0379` (different) |
| Share | `U+F0927` | `U+F037A` (different) |

The parser declares both glyph sets in tuples and uses
`re.escape(g) + r"\s*(\d+...)"` to extract the count.

#### Bugs already fixed

1. **K/M/B regex eating the 'B' of "Bình"**: `"30\nB"` → parse_count read it
   as "30B" = 30 billion. Fix: K/M/B must touch the digits with no whitespace
   in between.
2. **Word boundary `\b` doesn't work in Vietnamese**: in "15 giờDạ", both "ờ"
   and "D" are `\w` in Unicode, so `\b` doesn't fire. Fix: use a negative
   lookahead `(?![a-zA-Zà-ỹÀ-Ỹ])`.
3. **Author has trailing badge**: FB mobile shows badges like
   "Người đóng góp đang lên" / "• Theo dõi" after the name. `_clean_author()`
   strips them.

#### `merge_blocks` state machine

```
walk through blocks:
    is_full_block?      → emit Post directly
    is_header_block?    → flush pending, open new pending with author/time
    is_footer_block?    → merge likes/comments/shares into pending → flush
    else (body)?        → append body text to pending.text
```

This is a **state machine parser**: rather than trying to find a single "post
container" (FB doesn't expose one), we walk the blocks sequentially and
classify each by content signals.

### `crawl.py` — *orchestration*

The main file, no logic of its own — it just composes the modules:

```
1. open_session()          → browser + ctx + save_cookies fn
2. for each target in TARGETS:
     2a. page.goto(url)
     2b. random sleep 3-6s     (read the top of the page)
     2c. dismiss_modals()
     2d. detect_checkpoint()   → if hit, skip this target
     2e. human_scroll()
     2f. harvest_blocks()      → list[str]
     2g. merge_blocks()        → list[Post]
     2h. screenshot + JSON
     2i. random sleep 12-25s   (between targets)
3. save_cookies()            ← write rotated cookies back to file
4. browser.close()
```

---

## Part 2 — End-to-end flow

```
                       ┌──────────────────┐
                       │ fb_cookies.json  │  (exported via Cookie-Editor)
                       │  chmod 600       │
                       └────────┬─────────┘
                                │ load
                                ▼
┌──────────────────────────────────────────────────────────┐
│  Playwright Chromium + playwright-stealth                │
│  - Mobile UA (iPhone Safari 17.4)                        │
│  - viewport 390×844, locale vi-VN, tz Asia/Ho_Chi_Minh   │
│  - cookies injected into context                         │
└────────┬─────────────────────────────────────────────────┘
         │
         │ navigate to m.facebook.com/groups/X
         │ (random delay)
         ▼
┌──────────────────────────────────────────────────────────┐
│  Mobile FB serves real HTML (because c_user + xs are     │
│  valid)                                                  │
│  - dismiss popup if any                                  │
│  - detect /checkpoint redirect (stop if hit)             │
└────────┬─────────────────────────────────────────────────┘
         │
         │ human_scroll: 12 randomized iterations
         ▼
┌──────────────────────────────────────────────────────────┐
│  Harvest: query <article> or div[data-tracking-...]      │
│  → list[str] of inner_text per block (~30-80 blocks)     │
└────────┬─────────────────────────────────────────────────┘
         │
         │ merge_blocks (state machine)
         ▼
┌──────────────────────────────────────────────────────────┐
│  list[Post]                                              │
│   {author, time_text, time_iso, text,                    │
│    likes, comments, shares, top_reactor}                 │
│  capped at 5 → save JSON                                 │
└────────┬─────────────────────────────────────────────────┘
         │
         │ write rotated cookies back to disk
         ▼
       (target done → sleep 12-25s → next target)
```

---

## Part 3 — Why this is SAFE at demo scale

Cross-referenced with the 6 layers in [knowledge.md](../knowledge.md):

### Layer 1 — TLS fingerprint (JA3/JA4)

**Risk**: if you use Python `requests`, FB recognizes the bot from the TLS
handshake alone (Python's signature ≠ Chrome's).

**How the demo handles it**: Playwright launches real Chromium → TLS
handshake **looks exactly like Chrome** → JA3 hash matches Chrome 131. ✅

### Layer 2 — HTTP headers / HTTP/2 settings

**Risk**: missing `sec-ch-ua`, `Sec-Fetch-*`, or sending headers in the wrong
order → flagged.

**How the demo handles it**: Playwright sends every Chrome header in the
right order, with the right HTTP/2 SETTINGS frames. Stealth patches a few
extra quirks. ✅

### Layer 3 — Cookies (the **most important** layer)

**Risk**: brand-new cookies (account just created) or cookies that get
cleared mid-session → FB classifies the browser as "unfamiliar" → checkpoint.

**How the demo handles it**:
- Uses cookies from a **real account that has existed for months** — the
  `datr` cookie is the highest-trust signal as a "trusted browser
  fingerprint". The account hasn't tripped suspicion before.
- **Persistent**: load cookies in, **save them back after the run**. If FB
  rotates `xs` / `fr`, the next run uses fresh cookies rather than expired
  ones.
- **Never clears or resets cookies** between targets.
- ✅ Per knowledge.md: "datr 6 months + UA stable" = familiar browser → FB
  trusts it.

### Layer 4 — Browser fingerprint

**Risk**: default Selenium leaks `navigator.webdriver = true` → instant ban.

**How the demo handles it**: `playwright-stealth` patches ~15-20 properties:
- `navigator.webdriver = false`
- Fakes `navigator.plugins`, `navigator.languages`
- Patches `chrome.runtime`, `chrome.loadTimes`
- WebGL vendor spoofing, canvas noise
- ✅ Enough to pass FB's basic fingerprint checks.

⚠️ **Limitation**: FB can still detect Playwright if they look for
inconsistencies (e.g. UA Mac + WebGL renderer Linux). The demo uses iPhone
UA + iPhone viewport + locale vi-VN + tz Asia/HCM — **all consistent** → low
suspicion surface.

### Layer 5 — Behavioral pattern

**Risk**: scrolling at uniform 1s intervals, clicking <100 ms after load,
running 24/7 → FB's ML model says "not a human".

**How the demo handles it**:
- **Random delay** after load (3-6s), between scrolls (1.8-3.6s), between
  targets (12-25s)
- **Smooth scroll** with random distance 700-1500px
- **Mouse jitter** at 30% probability
- **Only 5 posts × 2 targets = 10 posts total per run** → far below the
  "<500 page views/day" budget knowledge.md estimates
- One run a day is fine. 100 runs an hour is suicide.
- ✅ At this volume the behavioral signal sits comfortably in the
  "real user" band.

### Layer 6 — IP reputation

**Risk**: datacenter IP / consumer VPN → FB blocks immediately. Rotating
mobile IPs per request → FB sees a "user teleporting".

**How the demo handles it**:
- Runs from your **home IP** — a normal residential address that **FB has
  seen this account log in from for months** → high trust score.
- **No IP rotation** between requests — same session, same IP. ✅

### Risk summary

| Factor | Verdict |
|---|---|
| Account used | ⚠️ Your main account (high stakes if flagged) |
| IP | ✅ Home residential, already trusted with this account |
| Volume | ✅ Very low (10 posts per run) |
| Frequency | ✅ One-off demo, not a cron job |
| Behavioral | ✅ Random delays, no spam |
| Cookies | ✅ Persistent, saved back |
| Fingerprint | ✅ Stealth + consistent mobile profile |

**Verdict: at demo scale (1-2 runs/day, 5 posts/target), the block risk is
very low.**

---

## Part 4 — When this stops being safe

This approach is safe **only at demo / one-off scale**. To use it in
production, plenty would have to change:

### ❌ Things that break this:

1. **Running >50 times a day** with the same cookies — FB sees the account
   behaving abnormally (1000+ post views/day with no engagement)
2. **Scraping >500 posts/day** — exceeds the budget knowledge.md estimates
   → checkpoint
3. **Running headless from cookies exported on another machine** — FB
   compares device fingerprints across sessions; mismatch → flag
4. **Crawling groups/pages the account has never visited manually** — odd
   pattern
5. **Logging in across multiple devices simultaneously** (e.g. running this
   demo while also using the FB app on a phone on a different Wi-Fi) —
   trips Layer 6
6. **Letting cookies leak** (paste in chat, commit to git, share the file)
   — anyone with the cookies = anyone with the account

### ✅ Production-ready setup looks like:

If you want to scale up later (e.g. crawl 1000 posts/day):
- **Throwaway account** (not your main one) — warmed up for 7 days before
  scraping
- **Residential proxy** with sticky session (Decodo / NodeMaven), geo-
  targeted to VN
- **Multi-account rotation** — each account < 200 posts/day
- **Anti-detect browser** (Multilogin / AdsPower) for isolated profiles
- **Time-of-day pattern** — only run during VN active hours (7am-11pm)
- **Monitor checkpoint signals** — if you hit a CAPTCHA, STOP for 1-2 weeks

Or simply: **use Apify** (like exp2/) — they handle the infrastructure;
you just pay.

---

## Part 5 — Mandatory cleanup after the demo

**Required**, not optional, because the cookie was pasted into chat in
earlier turns:

1. ✅ Go to https://www.facebook.com/settings_and_privacy/password_and_security
   → "Where you're logged in" → **log out all other sessions**. This
   invalidates the leaked `xs` cookie.
2. ✅ **Change the password** (defense in depth — in case anyone has cached
   the cookie).
3. ✅ **Delete the cookie file** when done:
   `rm /Users/phunguyen/experiment/fb_cookies.json`
4. ✅ Want to run again later? **Re-export cookies** — once the password
   changes, the old cookies are dead, you'll need a fresh export from the
   browser.

---

## Part 6 — TL;DR for a non-technical audience

> "This demo crawls the 5 latest posts from one Facebook group and one page
> using Playwright (browser automation), authenticated with cookies exported
> from my own logged-in browser. The code is split into 6 small modules:
> config, session, human-like behavior, time parser, post parser, and the
> main file. For each post we extract the author, timestamp, content, and
> like/comment/share counts. It's safe because (1) volume is tiny —
> 10 posts/run, (2) my home IP is already trusted with this account,
> (3) Playwright uses real Chrome internals so the TLS / header signature
> doesn't betray it as a bot, (4) randomized delays imitate human pacing.
> After the demo I'll log out other sessions to revoke the cookie that's
> already been exposed."

---

## References inside the codebase

- [config.py](config.py) — paths, targets, UA, viewport, delays
- [fb_session.py](fb_session.py) — cookie loader, browser context, modal
  dismiss
- [fb_behavior.py](fb_behavior.py) — human scroll
- [fb_time.py](fb_time.py) — relative time → ISO
- [fb_parser.py](fb_parser.py) — block → Post
- [crawl.py](crawl.py) — main pipeline
- [knowledge.md](../knowledge.md) — 6-layer detection theory (read the
  Layer 3 Cookies section carefully)
