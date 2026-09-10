"""Turn GitHub release markdown into structured note rows."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

_HTML_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_LINK_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)|\[([^\]]+)\]\([^)]+\)")
_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_|`)(.+?)\1")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*\d+\.\s+(.*)$")
_CATEGORY_RE = re.compile(
    r"^(Enhancement|Fixed|Fix|Change|Changed|Breaking)[:\s]+(.*)$",
    re.IGNORECASE,
)
_CATEGORY_KIND = {
    "enhancement": "enhancement",
    "fixed": "fixed",
    "fix": "fixed",
    "change": "change",
    "changed": "change",
    "breaking": "breaking",
}


@dataclass(frozen=True)
class NoteRow:
    kind: str
    text: str
    badge: str = ""


def format_release_notes(body: str | None, *, limit: int | None = None) -> list[NoteRow]:
    """Parse a GitHub release body into heading/paragraph/bullet/category rows."""
    if not body or not body.strip():
        return []

    rows: list[NoteRow] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if not paragraph:
            return
        text = "\n".join(paragraph).strip()
        paragraph = []
        if text:
            rows.append(NoteRow("paragraph", text))

    def at_limit() -> bool:
        return limit is not None and len(rows) >= limit

    for raw_line in body.replace("\r\n", "\n").split("\n"):
        cleaned = _clean_inline(raw_line)
        parts = cleaned.split("\n") if cleaned else [""]
        for line in parts:
            if at_limit():
                flush_paragraph()
                return rows[:limit]
            if not line.strip():
                flush_paragraph()
                continue
            heading = _HEADING_RE.match(line.strip())
            if heading:
                flush_paragraph()
                title = heading.group(2).strip()
                if title:
                    rows.append(NoteRow("heading", title))
                continue
            bullet = _BULLET_RE.match(line) or _NUMBERED_RE.match(line)
            if bullet:
                flush_paragraph()
                text = bullet.group(1).strip()
                if text:
                    rows.append(_categorize(text))
                continue
            categorized = _try_category(line.strip())
            if categorized is not None:
                flush_paragraph()
                rows.append(categorized)
                continue
            paragraph.append(line.strip())

    flush_paragraph()
    return rows if limit is None else rows[:limit]


def _categorize(text: str) -> NoteRow:
    categorized = _try_category(text)
    if categorized is not None:
        return categorized
    return NoteRow("bullet", text)


def _try_category(text: str) -> NoteRow | None:
    if not text:
        return None
    match = _CATEGORY_RE.match(text)
    if match is None:
        return None
    label = match.group(1)
    rest = (match.group(2) or "").strip()
    kind = _CATEGORY_KIND.get(label.lower(), "bullet")
    badge = {
        "enhancement": "Enhancement",
        "fixed": "Fixed",
        "change": "Changed",
        "breaking": "Breaking",
    }.get(kind, "")
    return NoteRow(kind, rest or text, badge=badge)


def _clean_inline(text: str) -> str:
    text = html.unescape(text)
    text = _BR_RE.sub("\n", text)
    text = _HTML_RE.sub("", text)
    text = _LINK_RE.sub(lambda match: match.group(1) or match.group(2) or "", text)
    text = _EMPHASIS_RE.sub(lambda match: match.group(2), text)
    return text.replace("\u0000", "").strip()
