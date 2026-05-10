"""Demo config — targets, paths, and runtime constants.

Centralizes everything that might change between runs so other modules don't
need to know about file layout or magic numbers.
"""
from pathlib import Path

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "outputs"
OUT_DIR.mkdir(exist_ok=True)

# Cookies live ONE level above /demo (shared with exp3_playwright). Treated as
# a secret — the file is gitignored and chmod 600.
COOKIE_FILE = ROOT.parent / "fb_cookies.json"

# We deliberately hit m.facebook.com — per knowledge.md it has cleaner DOM,
# fewer login walls, and matches the mobile UA we send.
TARGETS = [
    {
        "name": "machinelearningcoban",
        "kind": "group",
        "url":  "https://m.facebook.com/groups/machinelearningcoban",
    },
    {
        "name": "cung.AI.VN",
        "kind": "page",
        "url":  "https://m.facebook.com/cung.AI.VN",
    },
]

# Limit per target — knowledge.md "<500 page views/day" budget; we want only
# the latest few posts so this stays well under the radar.
POSTS_PER_TARGET = 5
SCROLLS_MAX = 12  # cap so we don't scroll forever on a stalled feed

# Random ranges for human-like delays — see fb_behavior.py.
DELAY_BETWEEN_SCROLLS = (1.8, 3.6)
DELAY_AFTER_LOAD      = (3.0, 6.0)
DELAY_BETWEEN_TARGETS = (12.0, 25.0)

# Mobile Safari UA — must stay consistent with viewport+locale+timezone or FB
# detects the mismatch (knowledge.md Layer 4).
UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 "
    "Mobile/15E148 Safari/604.1"
)
VIEWPORT_MOBILE = {"width": 390, "height": 844}
LOCALE   = "vi-VN"
TIMEZONE = "Asia/Ho_Chi_Minh"
