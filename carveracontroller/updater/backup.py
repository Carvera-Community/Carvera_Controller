"""Select config files to copy during a machine backup."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

DEFAULT_BACKUP_PATHS = (
    "/sd/cartesian_nm.grid",
    "/sd/config.default",
    "/sd/config.txt",
    "/sd/custom_tool_slots.txt",
    "/sd/flex_compensation.dat",
)


def matching_backup_paths(
    listing: Sequence[dict] | None,
    allowlist: Iterable[str] = DEFAULT_BACKUP_PATHS,
) -> list[str]:
    """Return allowlisted file paths present in a machine directory listing."""
    allowed = {str(path).replace("\\", "/").rstrip("/") for path in allowlist}
    found: list[str] = []
    seen: set[str] = set()
    for entry in listing or []:
        if entry.get("is_dir"):
            continue
        path = str(entry.get("path") or "").replace("\\", "/").rstrip("/")
        if path in allowed and path not in seen:
            found.append(path)
            seen.add(path)
    return found
