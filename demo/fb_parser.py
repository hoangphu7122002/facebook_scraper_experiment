"""Parse m.facebook.com post blocks into a structured Post record.

m.facebook.com (logged-in mobile) renders one post as 3 sibling DIVs:
    [header]  author + relative time + post-marker glyphs
    [body]    text / "... See more" / media markers
    [footer]  reactor summary + reaction counts (like/comment/share glyphs)

Anonymous m.facebook.com group view sometimes wraps a whole post in one
<article>, so the merger handles both layouts.

Reaction counts are rendered as PUA Unicode icon glyphs followed by a number.
The glyph codepoints differ between anon-EN and logged-VI renders — see
LIKE_GLYPHS / COMMENT_GLYPHS / SHARE_GLYPHS below.
"""
import re
from dataclasses import dataclass, field, asdict

from fb_time import parse_relative

# Glyph codepoints observed across anon-EN and logged-VI:
LIKE_GLYPHS    = ("\U000f0378",)
COMMENT_GLYPHS = ("\U000f0379", "\U000f0926")
SHARE_GLYPHS   = ("\U000f037a", "\U000f0927")
HEADER_GLYPHS  = ("\U000f212d", "\U000f3197", "\U000f312b")
ALL_REACTION   = LIKE_GLYPHS + COMMENT_GLYPHS + SHARE_GLYPHS

SEE_MORE_RE = re.compile(r"\.{2,3}\s*(?:Xem thêm|See more)\s*$")
COMMENT_AS_RE = re.compile(r"^(?:Bình luận dưới tên|Comment as)\b.*$", re.M)
REACTOR_RE = re.compile(
    r"^(?P<who>.+?)\s+(?:and|và)\s+(?P<n>[\d.,]+\s*[KMB]?)\s+(?:others?|người khác)\b",
    re.M,
)
COMMENTS_TEXT_RE = re.compile(r"([\d.,]+\s*[KMB]?)\s+(?:bình luận|comments?)", re.I)
SHARES_TEXT_RE   = re.compile(r"([\d.,]+\s*[KMB]?)\s+(?:lượt chia sẻ|shares?)", re.I)
# Time strings come in two flavors:
#   relative — "2 giờ", "1 ngày", "5h", "Yesterday"
#   absolute — "3 tháng 1, 2019", "Apr 29, 2024"
# We only ever look for these in the *first ~100 chars* of a block (the header
# region) to avoid false positives like "10 năm kinh nghiệm" deep in body text.
TIME_RE = re.compile(
    r"‎?(\d+\s*(?:giây|phút|giờ|ngày|tuần|năm|s|m|h|d|w|y)(?![a-zA-Zà-ỹÀ-Ỹ])"
    r"|\d{1,2}\s+tháng\s+\d{1,2}(?:\s*,?\s*\d{4})?"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{2,4}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:\s*,\s*\d{4})?"
    r"|Yesterday|Hôm qua|Just now|Vừa xong)"
)
HEADER_PREFIX_LEN = 120

# Author badges that follow the actual name on m.facebook.com.
AUTHOR_BADGE_RE = re.compile(
    r"\s*(?:•\s*Theo dõi|•\s*Follow|Người đóng góp đang lên|Top contributor|Theo dõi|Follow)\s*$"
)


@dataclass
class Post:
    source: str = ""           # the URL we were scraping
    source_kind: str = ""      # "page" or "group" as declared in config
    author: str | None = None
    time_text: str | None = None      # raw FB string, e.g. "2 giờ"
    time_iso: str | None = None       # parsed ISO date, may be None
    text: str = ""
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    top_reactor: str | None = None
    raw: str = field(default="", repr=False)


# ---- low-level helpers ----

def _parse_count(s: str) -> int | None:
    if not s:
        return None
    s = s.strip().replace(",", "").replace(" ", "")
    m = re.match(r"^([\d.]+)([KkMmBb]?)$", s)
    if not m:
        return None
    return int(float(m.group(1)) * {"k": 1_000, "m": 1_000_000,
                                    "b": 1_000_000_000}.get(m.group(2).lower(), 1))


def _count_after(text: str, glyphs: tuple[str, ...]) -> int | None:
    # No whitespace allowed between digits and K/M/B — otherwise we'd eat the
    # "B" of "Bình luận" and read 30 as 30B.
    for g in glyphs:
        m = re.search(re.escape(g) + r"\s*(\d+(?:[.,]\d+)?[KMBkmb]?)\b", text)
        if m:
            n = _parse_count(m.group(1))
            if n is not None:
                return n
    return None


def _has_any(text: str, glyphs: tuple[str, ...]) -> bool:
    return any(g in text for g in glyphs)


def _time_in_header(text: str) -> re.Match | None:
    """Look for a TIME_RE match only in the header region (first chars)."""
    return TIME_RE.search(text[:HEADER_PREFIX_LEN])


def _is_header_block(text: str) -> bool:
    """Has time in header region, no reaction signals."""
    if _time_in_header(text) is None:
        return False
    return not _is_footer_block(text)


def _is_footer_block(text: str) -> bool:
    return (_has_any(text, ALL_REACTION)
            or REACTOR_RE.search(text) is not None
            or COMMENTS_TEXT_RE.search(text) is not None)


def _is_full_block(text: str) -> bool:
    """Single block with both a header-region time AND reaction signals."""
    return _time_in_header(text) is not None and _is_footer_block(text)


def _clean_author(name: str | None) -> str | None:
    if not name:
        return name
    # Some authors come with trailing badges that aren't part of the name.
    return AUTHOR_BADGE_RE.sub("", name).strip() or None


def _parse_header(text: str) -> dict:
    cleaned = text
    for g in HEADER_GLYPHS:
        cleaned = cleaned.replace(g, "")
    cleaned = cleaned.replace("‎", "")
    out = {"author": None, "time_text": None}
    tm = _time_in_header(cleaned)
    if tm:
        out["time_text"] = tm.group(1).strip()
        before = cleaned[:tm.start()].strip()
        out["author"] = " ".join(p.strip() for p in before.split("\n") if p.strip())
    else:
        first = next((l.strip() for l in cleaned.split("\n") if l.strip()), None)
        out["author"] = first
    return out


def _parse_body(text: str) -> str:
    text = SEE_MORE_RE.sub("", text).strip()
    text = COMMENT_AS_RE.sub("", text).strip()
    return text


def _parse_footer(text: str) -> dict:
    out = {
        "likes":    _count_after(text, LIKE_GLYPHS),
        "comments": _count_after(text, COMMENT_GLYPHS),
        "shares":   _count_after(text, SHARE_GLYPHS),
        "top_reactor": None,
    }
    if out["comments"] is None:
        m = COMMENTS_TEXT_RE.search(text)
        if m:
            out["comments"] = _parse_count(m.group(1))
    if out["shares"] is None:
        m = SHARES_TEXT_RE.search(text)
        if m:
            out["shares"] = _parse_count(m.group(1))
    m = REACTOR_RE.search(text)
    if m:
        connector = "và" if "và" in m.group(0) else "and"
        out["top_reactor"] = f"{m.group('who').strip()} {connector} {m.group('n').strip()} người khác"
    return out


# ---- public API ----

def merge_blocks(blocks: list[str], *, source: str, source_kind: str,
                 limit: int) -> list[Post]:
    """Walk inner_text blocks and emit at most `limit` Post records.

    Two layouts coexist:
      - Single block contains BOTH header and footer signals (anon group view).
      - Three consecutive blocks: header, body, footer (logged-in mobile).
    """
    posts: list[Post] = []
    pending: Post | None = None

    def flush():
        nonlocal pending
        if pending and (pending.author or pending.text):
            posts.append(pending)
        pending = None

    for text in blocks:
        if len(posts) >= limit:
            break

        if _is_full_block(text):
            flush()
            head = _parse_header(text)
            head["author"] = _clean_author(head.get("author"))
            foot = _parse_footer(text)
            # Body sits between time and the first reactor / reaction glyph.
            body_text = text
            for g in HEADER_GLYPHS:
                body_text = body_text.replace(g, "")
            body_text = body_text.replace("‎", "")
            tm = TIME_RE.search(body_text)
            if tm:
                body_text = body_text[tm.end():]
            cut = len(body_text)
            for g in ALL_REACTION:
                idx = body_text.find(g)
                if idx >= 0 and idx < cut:
                    cut = idx
            for rx in (REACTOR_RE, COMMENTS_TEXT_RE):
                rm = rx.search(body_text)
                if rm and rm.start() < cut:
                    cut = rm.start()
            posts.append(Post(
                source=source, source_kind=source_kind,
                author=head["author"],
                time_text=head["time_text"],
                time_iso=parse_relative(head["time_text"] or ""),
                text=_parse_body(body_text[:cut]),
                **foot,
                raw=text,
            ))
            continue

        if _is_header_block(text):
            flush()
            head = _parse_header(text)
            head["author"] = _clean_author(head.get("author"))
            pending = Post(
                source=source, source_kind=source_kind,
                author=head["author"],
                time_text=head["time_text"],
                time_iso=parse_relative(head["time_text"] or ""),
                raw=text,
            )
            continue

        if _is_footer_block(text):
            if pending is None:
                # Footer with no preceding header — orphaned, skip.
                continue
            for k, v in _parse_footer(text).items():
                setattr(pending, k, v)
            pending.raw += "\n" + text
            flush()
            continue

        # Body block.
        if pending is None:
            continue
        body = _parse_body(text)
        if body:
            pending.text = (pending.text + "\n" + body).strip() if pending.text else body
        pending.raw += "\n" + text

    flush()
    return posts


def post_to_dict(post: Post) -> dict:
    d = asdict(post)
    d.pop("raw", None)  # keep JSON output small; raw is for debugging only
    return d
