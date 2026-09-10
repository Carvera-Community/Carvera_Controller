"""Semantic version parsing for Controller and Community Firmware tags."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_VERSION_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?P<community>c)?"
    r"(?:-(?P<pre>RC|BETA|ALPHA|DEV)(?P<pre_n>\d*))?$",
    re.IGNORECASE,
)

_PRE_RANK = {
    "rc": 1,
    "beta": 2,
    "alpha": 3,
    "dev": 4,
}


@dataclass(frozen=True, order=False)
class Version:
    major: int
    minor: int
    patch: int
    community: bool = False
    prerelease: str | None = None
    prerelease_n: int = 0
    raw: str = field(default="", compare=False)

    @property
    def is_prerelease(self) -> bool:
        return self.prerelease is not None

    def display(self) -> str:
        if self.raw:
            text = self.raw[1:] if self.raw.lower().startswith("v") and self.raw[1:2].isdigit() else self.raw
            return text
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.community:
            base += "c"
        if self.prerelease:
            suffix = self.prerelease.upper()
            if self.prerelease_n:
                suffix += str(self.prerelease_n)
            return f"{base}-{suffix}"
        return base

    def _sort_key(self) -> tuple[int, int, int, int, int, int]:
        # Stable releases sort after prereleases of the same X.Y.Z.
        pre_kind = 0 if self.prerelease is None else _PRE_RANK.get(self.prerelease, 9)
        # Invert prerelease_n so higher RC numbers are newer, but still < stable.
        pre_n = 0 if self.prerelease is None else self.prerelease_n
        stable_rank = 1 if self.prerelease is None else 0
        return (self.major, self.minor, self.patch, stable_rank, -pre_kind, pre_n)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._sort_key() < other._sort_key()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._sort_key() <= other._sort_key()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._sort_key() > other._sort_key()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._sort_key() >= other._sort_key()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._sort_key() == other._sort_key()

    def __hash__(self) -> int:
        return hash(self._sort_key())


def parse_version(value: str | None) -> Version | None:
    """Parse a GitHub tag or machine/controller version string."""
    text = (value or "").strip()
    if not text:
        return None
    match = _VERSION_RE.match(text)
    if match is None:
        return None
    pre = match.group("pre")
    pre_n_raw = match.group("pre_n") or ""
    pre_n = int(pre_n_raw) if pre_n_raw else (1 if pre else 0)
    return Version(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        community=bool(match.group("community")),
        prerelease=pre.lower() if pre else None,
        prerelease_n=pre_n if pre else 0,
        raw=text,
    )


def is_prerelease_tag(tag_name: str, *, github_prerelease: bool = False) -> bool:
    if github_prerelease:
        return True
    parsed = parse_version(tag_name)
    return bool(parsed and parsed.is_prerelease)
