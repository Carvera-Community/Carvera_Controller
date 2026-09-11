"""Turn GitHub release markdown into structured note rows."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

_HTML_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_A_RE = re.compile(
    r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
_AUTOLINK_RE = re.compile(r"<(https?://[^>\s]+)>", re.IGNORECASE)
_BARE_URL_RE = re.compile(r"https?://[^\s<>\[\]\"']+", re.IGNORECASE)
# Strong markers and backticks are unambiguous. Single _ or * must sit on a
# word boundary so identifiers like Carvera_Community_Firmware stay intact.
_EMPHASIS_RE = re.compile(
    r"(\*\*|__)(.+?)\1"
    r"|(?<!\w)(\*|_)(?!\s)(.+?)(?<!\s)\3(?!\w)"
    r"|`([^`]+)`"
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*\d+\.\s+(.*)$")
_CATEGORY_RE = re.compile(
    r"^(Enhancement|Fixed|Fix|Change|Changed|Breaking)[:\s]+(.*)$",
    re.IGNORECASE,
)
# Private-use delimiters so placeholders survive str.strip(); ASCII RS (\x1e) is whitespace.
_TOKEN_MARK = "\ue000"
_TOKEN_RE = re.compile(_TOKEN_MARK + r"(\d+)" + _TOKEN_MARK)
_CATEGORY_KIND = {
    "enhancement": "enhancement",
    "fixed": "fixed",
    "fix": "fixed",
    "change": "change",
    "changed": "change",
    "breaking": "breaking",
}
_CATEGORY_BADGE = {
    "enhancement": "Enhancement",
    "fixed": "Fixed",
    "change": "Changed",
    "breaking": "Breaking",
}
_LINK_COLOR = "32a4ce"

_Stored = list[tuple[str, str | None]]


@dataclass(frozen=True)
class NoteRow:
    kind: str
    text: str
    badge: str = ""
    markup: str = ""
    links: tuple[str, ...] = ()


def format_release_notes(body: str | None, *, limit: int | None = None) -> list[NoteRow]:
    """Parse a GitHub release body into heading/paragraph/bullet/category rows."""
    if not body or not body.strip():
        return []

    rows: list[NoteRow] = []
    paragraph: list[str] = []
    stored: _Stored = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if not paragraph:
            return
        text = "\n".join(paragraph).strip()
        paragraph = []
        row = _note_row("paragraph", text, stored)
        if row is not None:
            rows.append(row)

    def at_limit() -> bool:
        return limit is not None and len(rows) >= limit

    for raw_line in body.replace("\r\n", "\n").split("\n"):
        cleaned = _parse_inline(raw_line, stored)
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
                    row = _note_row("heading", title, stored)
                    if row is not None:
                        rows.append(row)
                continue
            bullet = _BULLET_RE.match(line) or _NUMBERED_RE.match(line)
            if bullet:
                flush_paragraph()
                text = bullet.group(1).strip()
                if text:
                    row = _categorize(text, stored)
                    if row is not None:
                        rows.append(row)
                continue
            categorized = _try_category(line.strip(), stored)
            if categorized is not None:
                flush_paragraph()
                rows.append(categorized)
                continue
            paragraph.append(line.strip())

    flush_paragraph()
    return rows if limit is None else rows[:limit]


def _categorize(text: str, stored: _Stored) -> NoteRow | None:
    categorized = _try_category(text, stored)
    if categorized is not None:
        return categorized
    return _note_row("bullet", text, stored)


def _try_category(text: str, stored: _Stored) -> NoteRow | None:
    if not text:
        return None
    match = _CATEGORY_RE.match(text)
    if match is None:
        return None
    kind = _CATEGORY_KIND.get(match.group(1).lower(), "bullet")
    badge = _CATEGORY_BADGE.get(kind, "")
    rest = (match.group(2) or "").strip()
    return _note_row(kind, rest or text, stored, badge=badge)


def _note_row(kind: str, tokenized: str, stored: _Stored, badge: str = "") -> NoteRow | None:
    tokenized = tokenized.strip()
    if not tokenized:
        return None
    text, markup, links = _expand_tokens(tokenized, stored)
    if not text:
        return None
    return NoteRow(kind, text, badge=badge, markup=markup, links=links)


def _parse_inline(text: str, stored: _Stored) -> str:
    text = html.unescape(text or "")

    def stash(display: str, url: str | None, *, strip: bool = True) -> str:
        stored.append((_strip_emphasis(display) if strip else display, url))
        return f"{_TOKEN_MARK}{len(stored) - 1}{_TOKEN_MARK}"

    text = _MD_IMAGE_RE.sub(lambda match: match.group(1) or "", text)

    def md_link(match: re.Match[str]) -> str:
        label = match.group(1)
        url = _http_url(_md_destination(match.group(2)))
        if url:
            return stash(label, url)
        return label

    text = _MD_LINK_RE.sub(md_link, text)

    def html_a(match: re.Match[str]) -> str:
        inner = _strip_emphasis(_HTML_RE.sub("", html.unescape(match.group(2))))
        url = _http_url(match.group(1))
        if url:
            return stash(inner, url)
        return inner

    text = _HTML_A_RE.sub(html_a, text)

    def autolink(match: re.Match[str]) -> str:
        url = _http_url(match.group(1))
        if url:
            return stash(url, url, strip=False)
        return match.group(1)

    def bare_url(match: re.Match[str]) -> str:
        url, trailing = _split_trailing_punct(match.group(0))
        http = _http_url(url)
        if http:
            return stash(http, http, strip=False) + trailing
        return match.group(0)

    text = _AUTOLINK_RE.sub(autolink, text)
    text = _BR_RE.sub("\n", text)
    text = _HTML_RE.sub("", text)
    text = _BARE_URL_RE.sub(bare_url, text)
    text = _strip_emphasis(text)
    return text.replace("\u0000", "").strip()


def _expand_tokens(tokenized: str, stored: _Stored) -> tuple[str, str, tuple[str, ...]]:
    plain: list[str] = []
    markup: list[str] = []
    links: list[str] = []
    pos = 0
    for match in _TOKEN_RE.finditer(tokenized):
        if match.start() > pos:
            chunk = tokenized[pos : match.start()]
            plain.append(chunk)
            markup.append(_escape_markup(chunk))
        index = int(match.group(1))
        if 0 <= index < len(stored):
            display, url = stored[index]
            if display:
                plain.append(display)
                escaped = _escape_markup(display)
                if url:
                    markup.append(f"[ref={len(links)}][color=#{_LINK_COLOR}][u]{escaped}[/u][/color][/ref]")
                    links.append(url)
                else:
                    markup.append(escaped)
        pos = match.end()
    if pos < len(tokenized):
        chunk = tokenized[pos:]
        plain.append(chunk)
        markup.append(_escape_markup(chunk))
    return "".join(plain), "".join(markup), tuple(links)


def _escape_markup(text: str) -> str:
    return text.replace("&", "&amp;").replace("[", "&bl;").replace("]", "&br;")


def _strip_emphasis(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return match.group(2) or match.group(4) or match.group(5) or ""

    return _EMPHASIS_RE.sub(repl, text)


def _md_destination(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("<") and ">" in text:
        return text[1 : text.index(">")].strip()
    if not text:
        return ""
    return text.split()[0]


def _split_trailing_punct(text: str) -> tuple[str, str]:
    url = text
    trailing = ""
    while url and url[-1] in ".,;:)]}>\"'":
        trailing = url[-1] + trailing
        url = url[:-1]
    return url, trailing


def _http_url(value: str | None) -> str | None:
    url = (value or "").strip()
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1].strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return None
    if any(ord(char) < 32 for char in url):
        return None
    return url
