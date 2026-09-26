"""Online documentation URLs for stable and development controller builds."""

from __future__ import annotations

from carveracontroller.__version__ import __version__
from carveracontroller.updater.version import parse_version
from carveracontroller.Utils import digitize_v

DOCS_BASE_STABLE = "https://carvera-community.gitbook.io/docs"
DOCS_BASE_DEV = "https://carvera-community.gitbook.io/docs/dev"

# Date-based development versions use a major above this (for example 2026.x.x).
_DEV_MAJOR_ABOVE = 99


def uses_dev_documentation(version: str | None) -> bool:
    """True when this controller build should open the development docs.

    That includes pre-release tags, date-based majors above 99, and the
    unversioned ``0.0.0`` placeholder stamped before a release build.
    """
    parsed = parse_version(version)
    if parsed is not None:
        return not parsed.is_stable_release
    text = (version or "").strip()
    if not text:
        return False
    # Build tooling treats any hyphen suffix as a pre-release, including tags
    # outside the RC/BETA/ALPHA/DEV set that parse_version recognises.
    if "-" in text:
        return True
    return digitize_v(text) // 1_000_000 > _DEV_MAJOR_ABOVE


def documentation_base(version: str | None = None) -> str:
    """Documentation site root for ``version``, or the running controller version."""
    if version is None:
        version = __version__
    if uses_dev_documentation(version):
        return DOCS_BASE_DEV
    return DOCS_BASE_STABLE


def resolve_documentation_url(url: str, version: str | None = None) -> str:
    """Point a docs URL at the stable or development site for ``version``.

    Paths and anchors after the documentation base are preserved. When
    ``version`` is omitted, the running controller version is used.
    """
    base = documentation_base(version)
    for prefix in (DOCS_BASE_DEV, DOCS_BASE_STABLE):
        if url == prefix or url.startswith(prefix + "/") or url.startswith(prefix + "#"):
            return base + url[len(prefix) :]
    return url
