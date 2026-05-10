# Demo — Facebook scraping (Playwright + cookie session)

A small, well-structured demo that pulls the **5 latest posts** from one Page
and one Group using a logged-in mobile session. Built on top of the lessons in
the parent project's [knowledge.md](../knowledge.md):

- TLS / fingerprint via Playwright Chromium + `playwright-stealth`
- Persistent cookies via `fb_cookies.json` (loaded *and* saved back)
- Mobile UA + matching viewport / locale / timezone
- Human-ish scroll with randomized delays and stall detection
- Per-post structured schema (matches Apify output where possible)

## Targets

Configured in [config.py](config.py):

| Kind  | Name                  | URL |
|-------|-----------------------|-----|
| group | machinelearningcoban  | https://www.facebook.com/groups/machinelearningcoban |
| page  | cung.AI.VN            | https://www.facebook.com/cung.AI.VN/ |

## File layout

```
demo/
├── config.py        constants: targets, paths, UA/viewport, delays
├── fb_session.py    cookie loader, browser/context setup, modal dismiss
├── fb_behavior.py   human-like scroll, randomized sleep
├── fb_time.py       relative time ("2 giờ", "Apr 29") -> ISO
├── fb_parser.py     post-block → Post record (locale-aware, glyph-aware)
├── crawl.py         pipeline: navigate → scroll → harvest → parse → save
└── outputs/
    ├── machinelearningcoban.json
    ├── cung.AI.VN.json
    ├── *.png         debug screenshot per target
    └── summary.json
```

## Output schema (per post)

```json
{
  "source":      "https://m.facebook.com/groups/machinelearningcoban",
  "source_kind": "group",
  "author":      "...",
  "time_text":   "2 giờ",
  "time_iso":    "2026-05-07T14:23:00",
  "text":        "...",
  "likes":       42,
  "comments":    7,
  "shares":      3,
  "top_reactor": "Người A và 41 người khác"
}
```

## How to run

```bash
# from repo root
source venv/bin/activate
playwright install chromium       # only first time

# 1. Make sure cookies are exported to ../fb_cookies.json
#    (Cookie-Editor extension on facebook.com → Export as JSON)
chmod 600 ../fb_cookies.json

# 2. Run
cd demo
python crawl.py
```

## Security notes

- `fb_cookies.json` is your **logged-in session token**. Anyone with that file
  can impersonate your account — keep it `chmod 600`, gitignored, never paste.
- After demo runs, log out other sessions in
  Facebook → Settings → Security → "Where you're logged in" to invalidate the
  exported `xs` cookie.
- This demo is **low volume on purpose** (5 posts × 2 targets). Scaling it up
  triggers the behavioral signals knowledge.md describes — at higher volume
  you'd want a residential proxy + warm-up account, not your personal session.
