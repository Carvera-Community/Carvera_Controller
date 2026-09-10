"""Typed GitHub release models used by the Update Center."""

from __future__ import annotations

from dataclasses import dataclass, field

from .version import Version, parse_version


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    size: int
    browser_download_url: str
    digest: str = ""
    content_type: str = ""

    @property
    def sha256(self) -> str | None:
        digest = (self.digest or "").strip()
        if digest.lower().startswith("sha256:"):
            hex_digest = digest.split(":", 1)[1].strip().lower()
            if len(hex_digest) == 64 and all(c in "0123456789abcdef" for c in hex_digest):
                return hex_digest
        return None


@dataclass(frozen=True)
class Release:
    tag_name: str
    name: str
    html_url: str
    body: str
    published_at: str
    prerelease: bool
    draft: bool = False
    assets: tuple[ReleaseAsset, ...] = field(default_factory=tuple)

    @property
    def version(self) -> Version | None:
        return parse_version(self.tag_name) or parse_version(self.name)

    @property
    def display_name(self) -> str:
        parsed = self.version
        if parsed is not None:
            return parsed.display()
        text = (self.tag_name or self.name or "").strip()
        if text.lower().startswith("v") and len(text) > 1 and text[1:2].isdigit():
            return text[1:]
        return text
