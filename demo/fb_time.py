"""Convert FB's localized relative-time strings into ISO timestamps.

Examples handled:
    "2 giờ"            -> now - 2h
    "1 ngày"           -> now - 1d
    "3 tuần"           -> now - 21d
    "Apr 29"           -> Apr 29 of this year (or last year if future)
    "Apr 29, 2024"     -> Apr 29 2024
    "3 tháng 1, 2019"  -> 2019-01-03
    "Hôm qua" / "Yesterday" -> yesterday
"""
import re
from datetime import datetime, timedelta

EN_MONTHS = {m.lower(): i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1
)}

UNIT_TO_DELTA = {
    "s": ("seconds", 1), "giây": ("seconds", 1),
    "m": ("minutes", 1), "phút": ("minutes", 1),
    "h": ("hours", 1),   "giờ":  ("hours", 1),
    "d": ("days", 1),    "ngày": ("days", 1),
    "w": ("weeks", 1),   "tuần": ("weeks", 1),
    "y": ("days", 365),  "năm":  ("days", 365),
}


def parse_relative(text: str, now: datetime | None = None) -> str | None:
    """Return an ISO 8601 string (no timezone) or None if unparsable."""
    if not text:
        return None
    now = now or datetime.now()
    s = text.strip()

    if re.match(r"^(just now|vừa xong)$", s, re.I):
        return now.isoformat(timespec="seconds")

    if re.match(r"^(yesterday|hôm qua)$", s, re.I):
        return (now - timedelta(days=1)).date().isoformat()

    # "2 giờ", "3 d", "5 tuần"
    m = re.match(r"^(\d+)\s*(s|m|h|d|w|y|giây|phút|giờ|ngày|tuần|năm)\b", s, re.I)
    if m:
        n = int(m.group(1))
        unit_key, mult = UNIT_TO_DELTA.get(m.group(2).lower(), (None, 1))
        if unit_key:
            return (now - timedelta(**{unit_key: n * mult})).isoformat(
                timespec="seconds"
            )

    # Vietnamese day-month-year: "3 tháng 1, 2019" or "3 tháng 1"
    m = re.match(r"^(\d{1,2})\s+tháng\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?", s, re.I)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        try:
            dt = datetime(year, month, day)
            if not m.group(3) and dt > now:
                dt = dt.replace(year=year - 1)
            return dt.date().isoformat()
        except ValueError:
            return None

    # English month-day: "Apr 29" / "Apr 29, 2024"
    m = re.match(r"^([A-Za-z]{3})\s+(\d{1,2})(?:\s*,\s*(\d{4}))?", s)
    if m and m.group(1).lower() in EN_MONTHS:
        month = EN_MONTHS[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        try:
            dt = datetime(year, month, day)
            if not m.group(3) and dt > now:
                dt = dt.replace(year=year - 1)
            return dt.date().isoformat()
        except ValueError:
            return None

    return None
