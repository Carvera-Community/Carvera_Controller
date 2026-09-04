"""Pure helpers for the file browser: listing, grouping, types, and action state."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from carveracontroller import Utils

MACHINE_BASE_DIR = "/sd/gcodes"
MACHINE_BASE_DIR_WIN = "\\sd\\gcodes"
LOCATION_DEVICE = "device"
LOCATION_MACHINE = "machine"
CONFIG_LAST_LOCATION = "file_browser_location"
COMPACT_WIDTH_DP = 720

KIND_FOLDER = "folder"
KIND_FILE = "file"

SORT_NAME = "name"
SORT_DATE = "date"
SORT_SIZE = "size"

DEFAULT_SORT_REVERSE = {
    SORT_NAME: False,
    SORT_DATE: True,
    SORT_SIZE: False,
}

GCODE_EXTENSIONS = {".nc", ".gcode", ".ngc", ".cnc", ".tap", ".gc"}
FIRMWARE_EXTENSIONS = {".bin"}
COMPRESSED_EXTENSIONS = {".lz"}

TYPE_GCODE = "gcode"
TYPE_FIRMWARE = "firmware"
TYPE_COMPRESSED = "compressed"
TYPE_OTHER = "other"

ICON_FOLDER = "data/folder-32.png"
ICON_FILE = "data/file-outline.png"
ICON_GCODE = "data/file-code-outline.png"
ICON_FIRMWARE = "data/memory.png"

Translate = Callable[[str], str]


def is_ios_platform() -> bool:
    return os.environ.get("KIVY_BUILD") == "ios" or sys.platform == "ios"


def is_compact_width(window_width: float, *, threshold: float = COMPACT_WIDTH_DP) -> bool:
    return float(window_width) < float(threshold)


def default_device_dir() -> str:
    """Default local gcodes folder, matching the historical LocalRV roots."""
    try:
        from kivy.utils import platform as kivy_platform
    except Exception:
        kivy_platform = sys.platform

    pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if kivy_platform == "android":
        android_dir = os.path.abspath(".carveracontroller/gcodes")
        if os.path.isdir(android_dir):
            return android_dir
        alt = os.path.join(pkg_root, "gcodes")
        if os.path.isdir(alt):
            return alt
        return android_dir

    cwd_dir = os.path.abspath("./gcodes")
    if os.path.isdir(cwd_dir):
        return cwd_dir
    pkg_dir = os.path.join(pkg_root, "gcodes")
    if os.path.isdir(pkg_dir):
        return pkg_dir
    return os.path.abspath(".")


def is_machine_root(path: str) -> bool:
    norm = os.path.normpath(path or "")
    return norm in (MACHINE_BASE_DIR, MACHINE_BASE_DIR_WIN, os.path.normpath(MACHINE_BASE_DIR))


def is_under_machine_root(path: str) -> bool:
    """True for /sd/gcodes and folders beneath it."""
    if is_machine_root(path):
        return True
    raw = (path or "").replace("\\", "/")
    parts = [part for part in raw.split("/") if part and part != "."]
    return len(parts) >= 2 and parts[0].lower() == "sd" and parts[1].lower() == "gcodes"


def trim_breadcrumb_pairs(
    paths: list[str],
    labels: list[str],
    *,
    machine: bool,
) -> tuple[list[str], list[str]]:
    """Drop empty crumbs and, on the machine, everything above /sd/gcodes."""
    pairs = [(path, label) for path, label in zip(paths, labels) if str(label).strip()]
    if machine:
        start = 0
        for index, (path, _label) in enumerate(pairs):
            if is_machine_root(path):
                start = index
                break
        pairs = pairs[start:]
    return [path for path, _label in pairs], [label for _path, label in pairs]


def device_tab_path_display(device_dir: str) -> str:
    """Local folder shown under the This device tab, in this OS's path format."""
    if not device_dir:
        return ""
    return os.path.normpath(device_dir)


def machine_path_display(machine_dir: str) -> str:
    """Machine folder as a POSIX /sd/... path (tab caption and upload tooltip)."""
    raw = (machine_dir or MACHINE_BASE_DIR).replace("\\", "/")
    parts = [part for part in raw.split("/") if part and part != "."]
    if not parts:
        parts = ["sd", "gcodes"]
    return "/" + "/".join(parts)


def machine_tab_path_display(machine_dir: str, *, connected: bool, translate: Translate) -> str:
    """Machine folder (or disconnected status) shown under the Your machine tab."""
    if not connected:
        return translate("Not connected")
    return machine_path_display(machine_dir)


def upload_dest_tooltip(machine_dir: str, *, translate: Translate) -> str:
    return translate("Upload to: %s") % machine_path_display(machine_dir)


def download_dest_tooltip(device_dir: str, *, translate: Translate) -> str:
    return translate("Download to: %s") % device_tab_path_display(device_dir)


def local_dir_has_file(directory: str, filename: str) -> bool:
    """True if a file (not a folder) with this basename already exists locally."""
    if not directory or not filename:
        return False
    return os.path.isfile(os.path.join(directory, os.path.basename(filename)))


def local_child_path(directory: str, name: str) -> str:
    """Join *directory* with a single path component. Empty if *name* is unsafe."""
    child = (name or "").strip()
    if not directory or not child:
        return ""
    if os.path.sep in child or "/" in child or "\\" in child:
        return ""
    if child in (".", ".."):
        return ""
    return os.path.join(directory, child)


def local_sibling_path(path: str, new_name: str) -> str:
    if not path:
        return ""
    return local_child_path(os.path.dirname(path), new_name)


def rename_local_path(src: str, dest: str) -> None:
    os.replace(src, dest)


def remove_local_path(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def mkdir_local(parent: str, name: str) -> str:
    dest = local_child_path(parent, name)
    if not dest:
        raise OSError("invalid folder name")
    os.mkdir(dest)
    return dest


def machine_parent_dir(path: str) -> str | None:
    norm = os.path.normpath(path or "")
    if not norm or is_machine_root(norm):
        return None
    parent = os.path.dirname(norm)
    if not parent or parent == norm:
        return None
    return parent


def file_type_key(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in GCODE_EXTENSIONS:
        return TYPE_GCODE
    if suffix in FIRMWARE_EXTENSIONS:
        return TYPE_FIRMWARE
    if suffix in COMPRESSED_EXTENSIONS:
        return TYPE_COMPRESSED
    return TYPE_OTHER


def _translate(translate: Translate | None, text: str) -> str:
    if translate is not None:
        return translate(text)
    try:
        from carveracontroller.translation import tr

        return tr._(text)
    except Exception:
        return text


def file_type_label(name: str, *, translate: Translate | None = None) -> str:
    key = file_type_key(name)
    labels = {
        TYPE_GCODE: "G-code",
        TYPE_FIRMWARE: "Firmware",
        TYPE_COMPRESSED: "Compressed",
        TYPE_OTHER: "File",
    }
    return _translate(translate, labels[key])


def row_icon(kind: str, name: str) -> str:
    """MDI asset for a folder or file row."""
    if kind == KIND_FOLDER:
        return ICON_FOLDER
    key = file_type_key(name)
    if key == TYPE_GCODE:
        return ICON_GCODE
    if key == TYPE_FIRMWARE:
        return ICON_FIRMWARE
    return ICON_FILE


def list_device_directory(directory: str) -> list[dict]:
    """One-level listing of a local folder. Skips names starting with '.'."""
    entries: list[dict] = []
    if not directory:
        return entries
    new_dir = directory if directory.endswith(os.path.sep) else directory + os.path.sep
    try:
        walker = os.walk(new_dir)
        dirpath, dirnames, filenames = next(walker)
    except (OSError, StopIteration):
        return entries

    for dirname in dirnames:
        if dirname.startswith("."):
            continue
        file_path = os.path.join(new_dir, dirname)
        try:
            file_time = os.stat(file_path).st_mtime
        except OSError:
            continue
        entries.append(
            {
                "name": dirname,
                "path": os.path.normpath(file_path),
                "is_dir": True,
                "size": 0,
                "date": file_time,
            }
        )
    for filename in filenames:
        if filename.startswith("."):
            continue
        file_path = os.path.join(new_dir, filename)
        try:
            stat = os.stat(file_path)
        except OSError:
            continue
        entries.append(
            {
                "name": filename,
                "path": os.path.normpath(file_path),
                "is_dir": False,
                "size": stat.st_size,
                "date": stat.st_mtime,
            }
        )
    return entries


def machine_listing_has(entries: Iterable[dict], filename: str) -> bool:
    target = os.path.basename(filename)
    for entry in entries:
        if entry.get("is_dir"):
            continue
        if entry.get("name") == target:
            return True
    return False


def _sort_entries(entries: list[dict], sort_key: str, reverse: bool) -> list[dict]:
    key = sort_key if sort_key in DEFAULT_SORT_REVERSE else SORT_DATE
    return sorted(entries, key=lambda item: item.get(key, 0), reverse=reverse)


def group_and_sort_entries(
    entries: list[dict],
    *,
    sort_key: str = SORT_DATE,
    reverse: bool = True,
    keyword: str = "",
    firmware_mode: bool = False,
    current_job_path: str = "",
    current_is_preview: bool = False,
    multi_select: bool = False,
    selected_paths: Iterable[str] | None = None,
    highlight_path: str = "",
    translate: Translate | None = None,
) -> list[dict]:
    """Turn raw directory entries into RecycleView rows (folders first, then files)."""
    selected = {os.path.normpath(p) for p in (selected_paths or []) if p}
    highlight = os.path.normpath(highlight_path) if highlight_path else ""
    current_job = os.path.normpath(current_job_path) if current_job_path else ""
    needle = (keyword or "").strip().lower()

    filtered: list[dict] = []
    for entry in entries:
        name = entry.get("name") or ""
        if firmware_mode and not entry.get("is_dir") and Path(name).suffix.lower() != ".bin":
            continue
        if needle and needle not in name.lower():
            continue
        filtered.append(entry)

    folders = _sort_entries([e for e in filtered if e.get("is_dir")], sort_key, reverse)
    files = _sort_entries([e for e in filtered if not e.get("is_dir")], sort_key, reverse)

    rows: list[dict] = []
    for entry in folders:
        rows.append(
            _item_row(
                entry,
                kind=KIND_FOLDER,
                current_job=current_job,
                current_is_preview=current_is_preview,
                selected=selected,
                highlight=highlight,
                multi_select=multi_select,
                translate=translate,
            )
        )
    for entry in files:
        rows.append(
            _item_row(
                entry,
                kind=KIND_FILE,
                current_job=current_job,
                current_is_preview=current_is_preview,
                selected=selected,
                highlight=highlight,
                multi_select=multi_select,
                translate=translate,
            )
        )
    return rows


def _item_row(
    entry: dict,
    *,
    kind: str,
    current_job: str,
    current_is_preview: bool,
    selected: set[str],
    highlight: str,
    multi_select: bool,
    translate: Translate | None,
) -> dict:
    path = os.path.normpath(entry.get("path") or "")
    name = entry.get("name") or ""
    is_dir = bool(entry.get("is_dir"))
    size = int(entry.get("size") or 0)
    date = entry.get("date") or 0
    type_label = "" if is_dir else file_type_label(name, translate=translate)
    size_label = "" if is_dir else Utils.humansize(size)
    date_label = Utils.humandate(date) if date else ""
    if is_dir:
        subtitle = ""
    else:
        parts = [part for part in (type_label, size_label, date_label) if part]
        subtitle = " · ".join(parts)
    is_current = bool(current_job) and path == current_job
    return {
        "kind": kind,
        "filename": name,
        "path": path,
        "is_dir": is_dir,
        "intsize": size,
        "filesize": size_label,
        "filedate": date_label,
        "file_type": type_label,
        "icon": row_icon(kind, name),
        "subtitle": subtitle,
        "selected": (not multi_select) and bool(highlight) and path == highlight,
        "is_current_job": is_current,
        "current_badge": current_row_badge(is_current=is_current, is_preview=current_is_preview, translate=translate),
        "show_checkbox": multi_select,
        "checked": path in selected,
        "selectable": True,
        "thumbnail": "" if kind != KIND_FILE else str(entry.get("thumbnail") or ""),
    }


@dataclass(frozen=True)
class ActionState:
    show_preview: bool = False
    show_upload: bool = False
    show_upload_and_use: bool = False
    show_use_as_job: bool = False
    show_download: bool = False
    show_rename: bool = False
    show_delete: bool = False
    show_new_folder: bool = False
    show_multi_toggle: bool = False
    show_cancel_multi: bool = False
    show_ios_browse: bool = False
    show_places: bool = True
    search_enabled: bool = True
    primary: str = ""


def compute_action_state(
    *,
    location: str,
    firmware_mode: bool,
    ios: bool,
    machine_connected: bool,
    machine_idle: bool,
    selected_is_file: bool,
    selected_count: int,
    multi_select_mode: bool,
) -> ActionState:
    """Which chrome/actions to show for the current browser state."""
    if firmware_mode:
        if ios:
            return ActionState(
                show_ios_browse=True,
                show_places=False,
                search_enabled=False,
            )
        return ActionState(
            show_upload=selected_is_file,
            show_places=True,
            search_enabled=False,
            primary="upload" if selected_is_file else "",
        )

    if location == LOCATION_DEVICE:
        if ios:
            return ActionState(
                show_ios_browse=True,
                show_places=False,
                search_enabled=False,
            )
        if multi_select_mode:
            return ActionState(
                show_delete=selected_count > 0,
                show_cancel_multi=True,
                show_places=True,
                search_enabled=True,
                primary="delete" if selected_count > 0 else "",
            )
        single_file = selected_is_file and selected_count == 1
        single_item = selected_count == 1
        return ActionState(
            show_preview=single_file,
            show_upload=single_file and machine_idle,
            show_upload_and_use=single_file and machine_idle,
            show_rename=single_item,
            show_delete=selected_count > 0,
            show_new_folder=True,
            show_multi_toggle=True,
            show_places=True,
            search_enabled=True,
            primary="upload_and_use" if single_file and machine_idle else "",
        )

    if not machine_connected:
        return ActionState(show_places=False, search_enabled=False)

    if multi_select_mode:
        return ActionState(
            show_delete=selected_count > 0,
            show_cancel_multi=True,
            show_places=True,
            search_enabled=machine_idle,
            primary="delete" if selected_count > 0 else "",
        )

    single_file = selected_is_file and selected_count == 1
    single_item = selected_count == 1
    return ActionState(
        show_use_as_job=single_file,
        show_download=single_file and machine_idle,
        show_rename=single_item,
        show_delete=selected_count > 0,
        show_new_folder=machine_idle,
        show_multi_toggle=True,
        show_places=True,
        search_enabled=machine_idle,
        primary="use_as_job" if single_file else "",
    )


def current_file_banner(remote_path: str, local_path: str, *, translate: Callable[[str], str]) -> tuple[str, str, bool]:
    """Return (filename, source badge, can_clear) for the current-file row."""
    remote = (remote_path or "").strip()
    local = (local_path or "").strip()
    if remote:
        return os.path.basename(remote), translate("Machine"), True
    if local:
        return os.path.basename(local), translate("Local (Preview)"), True
    return translate("None"), "", False


def is_local_preview(remote_path: str, local_path: str) -> bool:
    return bool((local_path or "").strip()) and not (remote_path or "").strip()


def current_row_badge(*, is_current: bool, is_preview: bool, translate: Translate | None = None) -> str:
    if not is_current:
        return ""
    if is_preview:
        return _translate(translate, "Current (Preview)")
    return _translate(translate, "Current")
