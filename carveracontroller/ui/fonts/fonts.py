"""Fonts for the interface: the bundled ARIALUNI plus a theme's family or file.

Kivy's SDL2 provider resolves ``font_name`` to a registered alias or a font
file. It does not look up a family name. This module does that lookup and
returns an alias whose four slots (regular, italic, bold, bold italic) are
files of the chosen face: fontconfig on Linux, the font registry on Windows,
and Core Text on macOS. A collection face other than 0 is left out, because
Kivy opens face 0.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import NamedTuple

from kivy.core.text import LabelBase

logger = logging.getLogger("carveracontroller.ui.fonts")

ARIALUNI = "ARIALUNI"
FONT_EXTENSIONS = (".ttf", ".otf", ".ttc")
WEIGHT_REGULAR = "Regular"
STYLE_ROMAN = "Roman"
STYLE_ITALIC = "Italic"

# Canonical weight, its order, and the style words that mean it. The first
# alias of each row is the canonical name. "Book" is a regular face, not a
# separate weight. These words are never stripped off a family name.
_WEIGHTS = (
    ("Thin", 100, ("thin", "hairline")),
    ("Extra Light", 200, ("extra light", "extralight", "ultra light", "ultralight")),
    ("Light", 300, ("light",)),
    ("Semi Light", 350, ("semi light", "semilight")),
    ("Regular", 400, ("regular", "normal", "roman", "book")),
    ("Medium", 500, ("medium",)),
    ("Semibold", 600, ("semibold", "semi bold", "demibold", "demi bold")),
    ("Bold", 700, ("bold",)),
    ("Extra Bold", 800, ("extra bold", "extrabold", "ultra bold", "ultrabold")),
    ("Black", 900, ("black", "heavy")),
)
WEIGHT_NAMES = tuple(name for name, _order, _aliases in _WEIGHTS)
_WEIGHT_ORDER = {name: order for name, order, _aliases in _WEIGHTS}
_WEIGHT_LOOKUP = {}
for _name, _order, _aliases in _WEIGHTS:
    for _alias in (_name.casefold(), *_aliases):
        _WEIGHT_LOOKUP[_alias] = (_name, _order, 0 if _alias in {_name.casefold(), "regular", ""} else 1)

_ITALIC_WORDS = {"italic", "oblique"}
_SKIP_WORDS = {"condensed", "narrow", "expanded", "extended", "compressed", "semicondensed"}

# Suffixes Windows appends to a family in the font registry. Longest first.
# "Roman" and "Book" are omitted: they belong to family names.
_REGISTRY_STYLES = (
    "bold italic",
    "bold oblique",
    "semi bold",
    "extra bold",
    "extra light",
    "ultra light",
    "demi bold",
    "semibold",
    "semilight",
    "demibold",
    "extrabold",
    "extralight",
    "ultralight",
    "italic",
    "oblique",
    "regular",
    "normal",
    "medium",
    "light",
    "black",
    "bold",
    "thin",
    "heavy",
)

_FC_LIST_TIMEOUT = 15

# None until a scan finishes. A timed-out scan stays None so the next call can retry.
_index_cache: dict[str, str] | None = None


def arialuni_path() -> str:
    """Location of the bundled ARIALUNI file, in a checkout, a pip install, or a frozen app.

    The file lives at ``assets/fonts/ARIALUNI.ttf``. The wheel ships that path, so an
    install resolves it under ``site-packages``. A PyInstaller build extracts the
    folder under ``sys._MEIPASS`` (see ``scripts/build.py``).
    """
    relative = os.path.join("assets", "fonts", "ARIALUNI.ttf")
    if getattr(sys, "frozen", False):
        root = getattr(sys, "_MEIPASS", "") or os.path.dirname(sys.executable)
        return os.path.abspath(os.path.join(root, relative))
    # fonts.py is carveracontroller/ui/fonts/fonts.py. Three levels up is the checkout
    # root, or site-packages when the wheel has installed assets/fonts beside the package.
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir))
    return os.path.join(root, relative)


def register_arialuni() -> None:
    """Register the ``ARIALUNI`` alias. It stays available whatever the theme picks."""
    path = arialuni_path()
    if not os.path.isfile(path):
        logger.error("Bundled font %s is missing at %s", ARIALUNI, path)
        raise FileNotFoundError(f"Bundled font {ARIALUNI} is missing at {path}")
    LabelBase.register(name=ARIALUNI, fn_regular=path)


class FontSpecError(ValueError):
    """A theme font value is not a family, a path, or a weight and style."""


class FontFace(NamedTuple):
    """One installed face of a family."""

    family: str
    weight: str
    italic: bool
    path: str
    order: int


def _normalize(text: str) -> str:
    return re.sub(r"[\s_\-]+", "", text).casefold()


def _canonical_weight(name: str) -> str:
    token = name.strip().casefold()
    found = _WEIGHT_LOOKUP.get(token) or _WEIGHT_LOOKUP.get(token.replace(" ", ""))
    if found is not None:
        return found[0]
    return name.strip() or WEIGHT_REGULAR


def _canonical_style(name: str) -> str:
    token = name.strip().casefold()
    if token in _ITALIC_WORDS:
        return STYLE_ITALIC
    return STYLE_ROMAN


def _classify_style(style: str) -> tuple[str, bool, int] | None:
    """``(weight, italic, penalty)`` for a fontconfig or registry style string.

    Width words such as Condensed are not their own weight. A style that is
    only a width, or an unknown word, is skipped. A lower penalty wins when
    two files share a weight: the plain Regular file beats Book and Bold
    Condensed.
    """
    words = [word for word in re.split(r"[\s_\-]+", style.strip()) if word]
    if not words:
        return (WEIGHT_REGULAR, False, 0)
    italic = False
    kept = []
    skipped = 0
    for word in words:
        if word.isdigit():
            skipped += 1
            continue
        token = word.casefold()
        if token in _ITALIC_WORDS:
            italic = True
            continue
        if token in _SKIP_WORDS:
            skipped += 1
            continue
        kept.append(token)
    if not kept:
        return None
    joined = " ".join(kept)
    found = _WEIGHT_LOOKUP.get(joined) or _WEIGHT_LOOKUP.get("".join(kept))
    if found is None:
        return None
    canonical, _order, alias_penalty = found
    return (canonical, italic, skipped + alias_penalty)


def normalize_font_spec(value):
    """Family string, or ``{family, weight, style}``.

    Regular roman collapses to the family string. A path stays a string.
    Raises :class:`FontSpecError` when the value cannot be stored.
    """
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise FontSpecError("empty font")
        return text
    if not isinstance(value, dict):
        raise FontSpecError("font must be a name or an object")
    unknown = sorted(set(value) - {"family", "weight", "style"})
    if unknown:
        raise FontSpecError(f"unknown font keys: {', '.join(unknown)}")
    family = value.get("family")
    if not isinstance(family, str) or not family.strip():
        raise FontSpecError("font family must be a name")
    weight_raw = value.get("weight", WEIGHT_REGULAR)
    style_raw = value.get("style", STYLE_ROMAN)
    if not isinstance(weight_raw, str) or not weight_raw.strip():
        raise FontSpecError("font weight must be a name")
    if not isinstance(style_raw, str) or not style_raw.strip():
        raise FontSpecError("font style must be a name")
    if _canonical_weight(weight_raw) == weight_raw.strip() and weight_raw.strip() not in WEIGHT_NAMES:
        raise FontSpecError(f"unknown font weight {weight_raw!r}")
    style_token = style_raw.strip().casefold()
    if style_token not in {"roman", "italic", "oblique"}:
        raise FontSpecError(f"unknown font style {style_raw!r}")
    weight = _canonical_weight(weight_raw)
    style = STYLE_ITALIC if style_token in _ITALIC_WORDS else STYLE_ROMAN
    family = family.strip()
    if weight == WEIGHT_REGULAR and style == STYLE_ROMAN:
        return family
    return {"family": family, "weight": weight, "style": style}


def split_font_spec(spec) -> tuple[str, str, str]:
    """``(family or path, weight, style)``. An empty spec is regular ARIALUNI."""
    if spec is None or spec == "" or (isinstance(spec, str) and not spec.strip()):
        return ARIALUNI, WEIGHT_REGULAR, STYLE_ROMAN
    if isinstance(spec, str):
        return spec.strip(), WEIGHT_REGULAR, STYLE_ROMAN
    normalized = normalize_font_spec(spec)
    if isinstance(normalized, str):
        return normalized, WEIGHT_REGULAR, STYLE_ROMAN
    return normalized["family"], normalized["weight"], normalized["style"]


def font_choice(family: str, weight: str, style: str):
    """Theme value for a family at ``weight`` and ``style``.

    A path, ARIALUNI, and regular roman stay a string.
    """
    family = family.strip()
    if not family or family.casefold() == ARIALUNI.casefold() or _is_font_path(family):
        return family or ARIALUNI
    weight = _canonical_weight(weight)
    style = _canonical_style(style)
    if weight == WEIGHT_REGULAR and style == STYLE_ROMAN:
        return family
    if weight not in WEIGHT_NAMES:
        weight = WEIGHT_REGULAR
    return {"family": family, "weight": weight, "style": style}


def _collection_family(path: str) -> str | None:
    """Family of face 0 in a font collection, or ``None`` when it cannot be read."""
    try:
        from PIL import ImageFont

        family, _style = ImageFont.truetype(path, size=12, index=0).getname()
    except (OSError, ValueError):
        logger.debug("Could not read font collection %s", path, exc_info=True)
        return None
    if not isinstance(family, str) or not family.strip():
        return None
    return family


def _index_from_records(
    records: list[tuple[str, str, str, int]], *, trust_face: bool = False
) -> dict[str, tuple[FontFace, ...]]:
    """Installed faces of each family, keyed by the display family name.

    Later records win for the same weight and style, so a per-user font overrides
    the machine font. ``trust_face`` skips the collection check for a source that
    already names the family of face 0.
    """
    chosen: dict[tuple[str, str, bool], tuple[int, int, FontFace]] = {}
    display: dict[str, str] = {}
    for order, (family, style, path, face) in enumerate(records):
        if face != 0 or not family or not path:
            continue
        classified = _classify_style(style)
        if classified is None or not path.lower().endswith(FONT_EXTENSIONS) or not os.path.isfile(path):
            continue
        if not trust_face and path.lower().endswith(".ttc"):
            actual = _collection_family(path)
            if actual is None or _normalize(actual) != _normalize(family):
                continue
        key_name = _normalize(family)
        if not key_name:
            continue
        weight, italic, penalty = classified
        current = chosen.get((key_name, weight, italic))
        if current is None or penalty < current[0] or (penalty == current[0] and order > current[1]):
            chosen[(key_name, weight, italic)] = (
                penalty,
                order,
                FontFace(family.strip(), weight, italic, path, _WEIGHT_ORDER[weight]),
            )
            display[key_name] = family.strip()
    grouped: dict[str, list[FontFace]] = {}
    for (key_name, _weight, _italic), (_penalty, _order, chosen_face) in chosen.items():
        grouped.setdefault(key_name, []).append(chosen_face)
    return {
        display[key_name]: tuple(sorted(faces, key=lambda item: (item.order, item.italic, item.path)))
        for key_name, faces in grouped.items()
    }


def _parse_fc_list(stdout: str) -> list[tuple[str, str, str, int]]:
    """Rows from ``fc-list -f '%{family[0]}|%{style[0]}|%{file}|%{index}'``."""
    records = []
    for raw in stdout.splitlines():
        parts = raw.split("|")
        if len(parts) != 4:
            continue
        family, style, path, index_text = (part.strip() for part in parts)
        if not family or not path:
            continue
        try:
            face = int(index_text or "0")
        except ValueError:
            continue
        records.append((family, style, path, face))
    return records


def _decode_fc_list(raw) -> str:
    """Fontconfig writes UTF-8. A non-UTF-8 locale must not fail the scan."""
    if isinstance(raw, str):
        return raw
    if not raw:
        return ""
    return bytes(raw).decode("utf-8", errors="replace")


def _fontconfig_index() -> dict[str, tuple[FontFace, ...]] | None:
    """Installed faces via fontconfig, or ``None`` when the scan times out."""
    fc_list = shutil.which("fc-list")
    if not fc_list:
        return {}
    try:
        result = subprocess.run(
            [fc_list, "-f", "%{family[0]}|%{style[0]}|%{file}|%{index}\n"],
            capture_output=True,
            timeout=_FC_LIST_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("fc-list timed out after %ss; font families will be tried again later", _FC_LIST_TIMEOUT)
        return None
    except (OSError, UnicodeError):
        logger.warning("Could not run fc-list", exc_info=True)
        return {}
    if result.returncode != 0:
        logger.warning("fc-list failed with exit code %s", result.returncode)
        return {}
    return _index_from_records(_parse_fc_list(_decode_fc_list(result.stdout)), trust_face=True)


def _split_registry_name(value_name: str) -> tuple[str, str] | None:
    """``(family, style)`` from a Windows font-registry value name."""
    name = re.sub(r"\s*\([^)]*\)\s*$", "", value_name).strip()
    if not name:
        return None
    lowered = name.casefold()
    for suffix in _REGISTRY_STYLES:
        if lowered == suffix:
            continue
        tail = " " + suffix
        if lowered.endswith(tail):
            family = name[: -len(tail)].rstrip()
            if family:
                return family, suffix
    return name, ""


def _registry_file(data: str, fonts_dir: str) -> str | None:
    """Absolute path for a registry font value. A bare filename lives in ``fonts_dir``."""
    data = data.strip().strip("\x00")
    if not data:
        return None
    return data if os.path.isabs(data) else os.path.join(fonts_dir, data)


def _records_from_registry(entries: list[tuple[str, str]], fonts_dir: str) -> list[tuple[str, str, str, int]]:
    """Registry ``(value name, file)`` pairs in the order they should override."""
    records = []
    for value_name, data in entries:
        if not isinstance(data, str):
            continue
        split = _split_registry_name(value_name)
        path = None if split is None else _registry_file(data, fonts_dir)
        if split is None or path is None:
            continue
        family, style = split
        records.append((family, style, path, 0))
    return records


def _windows_font_index() -> dict[str, tuple[FontFace, ...]]:
    """Installed faces from the machine font registry, then the user one."""
    if sys.platform != "win32":
        return {}
    import winreg

    fonts_dir = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "Fonts")
    access = winreg.KEY_READ
    if hasattr(winreg, "KEY_WOW64_64KEY"):
        access |= winreg.KEY_WOW64_64KEY
    locations = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    )
    entries: list[tuple[str, str]] = []
    for hive, subkey in locations:
        try:
            with winreg.OpenKey(hive, subkey, 0, access) as key:
                count = winreg.QueryInfoKey(key)[1]
                for index in range(count):
                    name, data, _kind = winreg.EnumValue(key, index)
                    if isinstance(data, str):
                        entries.append((name, data))
        except OSError:
            logger.debug("Font registry key unavailable: %s", subkey, exc_info=True)
    return _index_from_records(_records_from_registry(entries, fonts_dir))


_CF_STRING_UTF8 = 0x08000100


def _cf_string(core_foundation, text: str):
    return core_foundation.CFStringCreateWithCString(None, text.encode("utf-8"), _CF_STRING_UTF8)


def _py_string(core_foundation, ref) -> str:
    if not ref:
        return ""
    length = core_foundation.CFStringGetLength(ref)
    size = int(length) * 4 + 1
    buffer = ctypes.create_string_buffer(size)
    if not core_foundation.CFStringGetCString(ref, buffer, size, _CF_STRING_UTF8):
        return ""
    return buffer.value.decode("utf-8")


def _macos_descriptor_records() -> list[tuple[str, str, str, int]] | None:
    """Every file-backed face Core Text publishes, or ``None`` when the call fails."""
    try:
        core_text = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreText.framework/CoreText")
        core_foundation = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    except OSError:
        return None
    pointer = ctypes.c_void_p
    index_type = ctypes.c_long
    boolean = ctypes.c_uint8
    try:
        core_foundation.CFRelease.argtypes = [pointer]
        core_foundation.CFRelease.restype = None
        core_foundation.CFArrayGetCount.argtypes = [pointer]
        core_foundation.CFArrayGetCount.restype = index_type
        core_foundation.CFArrayGetValueAtIndex.argtypes = [pointer, index_type]
        core_foundation.CFArrayGetValueAtIndex.restype = pointer
        core_foundation.CFURLGetFileSystemRepresentation.argtypes = [pointer, boolean, ctypes.c_char_p, index_type]
        core_foundation.CFURLGetFileSystemRepresentation.restype = boolean
        core_text.CTFontCollectionCreateFromAvailableFonts.argtypes = [pointer]
        core_text.CTFontCollectionCreateFromAvailableFonts.restype = pointer
        core_text.CTFontCollectionCreateMatchingFontDescriptors.argtypes = [pointer]
        core_text.CTFontCollectionCreateMatchingFontDescriptors.restype = pointer
        core_text.CTFontDescriptorCopyAttribute.argtypes = [pointer, pointer]
        core_text.CTFontDescriptorCopyAttribute.restype = pointer
        family_attribute = ctypes.c_void_p.in_dll(core_text, "kCTFontFamilyNameAttribute").value
        style_attribute = ctypes.c_void_p.in_dll(core_text, "kCTFontStyleNameAttribute").value
        url_attribute = ctypes.c_void_p.in_dll(core_text, "kCTFontURLAttribute").value
    except (AttributeError, ValueError):
        return None

    def release(ref) -> None:
        if ref:
            core_foundation.CFRelease(ref)

    collection = core_text.CTFontCollectionCreateFromAvailableFonts(None)
    if not collection:
        return None
    descriptors = None
    records = []
    try:
        descriptors = core_text.CTFontCollectionCreateMatchingFontDescriptors(collection)
        if not descriptors:
            return None
        count = int(core_foundation.CFArrayGetCount(descriptors))
        for index in range(count):
            descriptor = core_foundation.CFArrayGetValueAtIndex(descriptors, index)
            family_ref = core_text.CTFontDescriptorCopyAttribute(descriptor, family_attribute)
            style_ref = core_text.CTFontDescriptorCopyAttribute(descriptor, style_attribute)
            url = core_text.CTFontDescriptorCopyAttribute(descriptor, url_attribute)
            try:
                family = _py_string(core_foundation, family_ref)
                style = _py_string(core_foundation, style_ref) or "Regular"
                if not family or not url:
                    continue
                path_buffer = ctypes.create_string_buffer(4096)
                if not core_foundation.CFURLGetFileSystemRepresentation(url, 1, path_buffer, len(path_buffer)):
                    continue
                records.append((family, style, path_buffer.value.decode("utf-8"), 0))
            finally:
                release(family_ref)
                release(style_ref)
                release(url)
    except (OSError, AttributeError, ValueError, ctypes.ArgumentError):
        return None
    finally:
        release(descriptors)
        release(collection)
    return records


def _macos_font_records() -> list[tuple[str, str, str, int]]:
    """File-backed faces Core Text can expose. A failed full list falls back to regular faces."""
    described = _macos_descriptor_records()
    if described is not None:
        return described
    core_text = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreText.framework/CoreText")
    core_foundation = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    pointer = ctypes.c_void_p
    index_type = ctypes.c_long
    boolean = ctypes.c_uint8

    core_foundation.CFStringCreateWithCString.argtypes = [pointer, ctypes.c_char_p, ctypes.c_uint32]
    core_foundation.CFStringCreateWithCString.restype = pointer
    core_foundation.CFStringGetLength.argtypes = [pointer]
    core_foundation.CFStringGetLength.restype = index_type
    core_foundation.CFStringGetCString.argtypes = [pointer, ctypes.c_char_p, index_type, ctypes.c_uint32]
    core_foundation.CFStringGetCString.restype = boolean
    core_foundation.CFRelease.argtypes = [pointer]
    core_foundation.CFRelease.restype = None
    core_foundation.CFArrayGetCount.argtypes = [pointer]
    core_foundation.CFArrayGetCount.restype = index_type
    core_foundation.CFArrayGetValueAtIndex.argtypes = [pointer, index_type]
    core_foundation.CFArrayGetValueAtIndex.restype = pointer
    core_foundation.CFURLGetFileSystemRepresentation.argtypes = [pointer, boolean, ctypes.c_char_p, index_type]
    core_foundation.CFURLGetFileSystemRepresentation.restype = boolean
    core_text.CTFontManagerCopyAvailableFontFamilyNames.argtypes = []
    core_text.CTFontManagerCopyAvailableFontFamilyNames.restype = pointer
    core_text.CTFontCreateWithName.argtypes = [pointer, ctypes.c_double, pointer]
    core_text.CTFontCreateWithName.restype = pointer
    core_text.CTFontCopyFamilyName.argtypes = [pointer]
    core_text.CTFontCopyFamilyName.restype = pointer
    core_text.CTFontCopyAttribute.argtypes = [pointer, pointer]
    core_text.CTFontCopyAttribute.restype = pointer
    url_attribute = ctypes.c_void_p.in_dll(core_text, "kCTFontURLAttribute").value

    def release(ref) -> None:
        if ref:
            core_foundation.CFRelease(ref)

    families = core_text.CTFontManagerCopyAvailableFontFamilyNames()
    records = []
    try:
        count = int(core_foundation.CFArrayGetCount(families)) if families else 0
        for index in range(count):
            family = _py_string(core_foundation, core_foundation.CFArrayGetValueAtIndex(families, index))
            if not family:
                continue
            name_ref = _cf_string(core_foundation, family)
            font = core_text.CTFontCreateWithName(name_ref, 0.0, None) if name_ref else None
            release(name_ref)
            if not font:
                continue
            url = None
            try:
                actual_ref = core_text.CTFontCopyFamilyName(font)
                actual = _py_string(core_foundation, actual_ref)
                release(actual_ref)
                if _normalize(actual) != _normalize(family):
                    continue
                url = core_text.CTFontCopyAttribute(font, url_attribute)
                if not url:
                    continue
                path_buffer = ctypes.create_string_buffer(4096)
                if not core_foundation.CFURLGetFileSystemRepresentation(url, 1, path_buffer, len(path_buffer)):
                    continue
                path = path_buffer.value.decode("utf-8")
            finally:
                release(url)
                release(font)
            records.append((family, "Regular", path, 0))
    finally:
        release(families)
    return records


def _macos_font_index() -> dict[str, tuple[FontFace, ...]]:
    try:
        records = _macos_font_records()
    except (OSError, AttributeError, ValueError, ctypes.ArgumentError):
        logger.warning("Core Text font list failed", exc_info=True)
        return {}
    return _index_from_records(records)


def _load_font_index() -> dict | None:
    """Installed faces, or ``None`` when the scan should be retried."""
    if sys.platform == "win32":
        return _windows_font_index()
    if sys.platform == "darwin":
        return _macos_font_index()
    return _fontconfig_index()


def font_index() -> dict:
    """Installed family name to its faces.

    A timed-out scan is not stored, so a later call tries again. A finished
    scan, including an empty one, is kept for the process. A family stored as
    a single file path is treated as the regular roman face.
    """
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    loaded = _load_font_index()
    if loaded is None:
        return {}
    _index_cache = loaded
    return _index_cache


def available_families() -> list[str]:
    """Family names a theme can use, with the bundled alias first."""
    names = {name for name in font_index() if _normalize(name) != _normalize(ARIALUNI)}
    return [ARIALUNI, *sorted(names, key=str.casefold)]


def _is_font_path(value: str) -> bool:
    return "/" in value or "\\" in value or value.lower().endswith(FONT_EXTENSIONS)


def _coerce_faces(value) -> tuple[FontFace, ...]:
    if isinstance(value, str):
        return (FontFace("", WEIGHT_REGULAR, False, value, _WEIGHT_ORDER[WEIGHT_REGULAR]),)
    return tuple(value)


def _family_faces(family: str, index) -> tuple[FontFace, ...]:
    source = font_index() if index is None else index
    wanted = _normalize(family)
    if not wanted:
        return ()
    for name, value in source.items():
        if _normalize(name) == wanted:
            return _coerce_faces(value)
    return ()


def _face_named(faces: tuple[FontFace, ...], weight: str, italic: bool) -> FontFace | None:
    canonical = _canonical_weight(weight)
    for face in faces:
        if face.weight == canonical and face.italic == italic:
            return face
    return None


def _next_heavier(faces: tuple[FontFace, ...], order: int, italic: bool) -> FontFace | None:
    heavier = [face for face in faces if face.italic == italic and face.order > order]
    if not heavier:
        return None
    return min(heavier, key=lambda face: (face.order, face.path))


def available_weights(family: str, index=None) -> list[str]:
    """Weights ``family`` actually ships, lightest first. A path has Regular only."""
    if not family or family.casefold() == ARIALUNI.casefold() or _is_font_path(family):
        return [WEIGHT_REGULAR]
    names = []
    for face in _family_faces(family, index):
        if face.weight not in names:
            names.append(face.weight)
    return names or [WEIGHT_REGULAR]


def available_styles(family: str, weight: str, index=None) -> list[str]:
    """Roman, plus Italic when ``family`` has that style at ``weight``."""
    if not family or family.casefold() == ARIALUNI.casefold() or _is_font_path(family):
        return [STYLE_ROMAN]
    faces = [face for face in _family_faces(family, index) if face.weight == _canonical_weight(weight)]
    if not faces:
        return [STYLE_ROMAN]
    styles = []
    if any(not face.italic for face in faces):
        styles.append(STYLE_ROMAN)
    if any(face.italic for face in faces):
        styles.append(STYLE_ITALIC)
    return styles or [STYLE_ROMAN]


def _is_registered(name: str) -> bool:
    return name in getattr(LabelBase, "_fonts", {})


def _is_font_file(path: str) -> bool:
    return os.path.isfile(path) and path.lower().endswith(FONT_EXTENSIONS)


def _alias_name(family: str, weight: str, style: str) -> str:
    return f"{family} [{weight} {style}]"


def _register_family(family: str, weight: str, style: str, index) -> str | None:
    """Register the chosen face and the bold and italic slots Kivy already switches."""
    faces = _family_faces(family, index)
    if not faces:
        return None
    italic = style == STYLE_ITALIC
    chosen = _face_named(faces, weight, italic)
    if chosen is None and italic:
        chosen = _face_named(faces, weight, False)
    if chosen is None:
        chosen = _face_named(faces, WEIGHT_REGULAR, False) or faces[0]
    if chosen.italic:
        italic_face = chosen
        bold = _next_heavier(faces, chosen.order, True) or _next_heavier(faces, chosen.order, False) or chosen
        bold_italic = _next_heavier(faces, chosen.order, True) or bold
    else:
        italic_face = _face_named(faces, chosen.weight, True) or chosen
        bold = _next_heavier(faces, chosen.order, False) or chosen
        bold_italic = _next_heavier(faces, chosen.order, True) or italic_face
    paths = (chosen.path, italic_face.path, bold.path, bold_italic.path)
    if not all(_is_font_file(path) for path in paths):
        return None
    style_name = STYLE_ITALIC if chosen.italic else STYLE_ROMAN
    name = _alias_name(chosen.family or family, chosen.weight, style_name)
    try:
        LabelBase.register(name, *paths)
    except OSError:
        logger.warning("Could not register font %s", name, exc_info=True)
        return None
    return name


def resolve_font(spec, index=None) -> str:
    """Kivy ``font_name`` for a theme font: a registered alias or an absolute file path.

    ``spec`` is a family name, a ``{family, weight, style}`` object, a font file
    path, or the ARIALUNI alias. A family is registered so a bold label can use
    the next heavier face. An empty or unusable value gives ARIALUNI. ``index``
    reuses one family scan when several roles are resolved together.
    """
    if not isinstance(spec, (str, dict)) and spec is not None:
        return ARIALUNI
    try:
        family, weight, style = split_font_spec(spec)
    except FontSpecError:
        logger.warning("Theme font %r is invalid, using %s", spec, ARIALUNI)
        return ARIALUNI
    if family.casefold() == ARIALUNI.casefold():
        return ARIALUNI
    if isinstance(spec, str) and _is_registered(spec):
        return spec
    expanded = os.path.expanduser(family)
    if _is_font_path(family):
        if os.path.isabs(expanded) and _is_font_file(expanded):
            return expanded
        logger.warning("Theme font file %r not found, using %s", family, ARIALUNI)
        return ARIALUNI
    registered = _register_family(family, weight, style, index)
    if registered:
        return registered
    logger.warning("Theme font %r not found, using %s", spec, ARIALUNI)
    return ARIALUNI


def resolve_theme_fonts(roles) -> dict:
    """Kivy ``font_name`` values for each theme font role.

    A role the theme leaves out takes the resolved default, which is ARIALUNI when
    the theme sets none.
    """
    from carveracontroller.ui.themes import FONT_ROLES

    roles = roles or {}
    index = font_index()
    default = resolve_font(roles.get("default"), index)
    resolved = {"default": default}
    for role in FONT_ROLES:
        if role == "default":
            continue
        spec = roles.get(role)
        resolved[role] = resolve_font(spec, index) if spec else default
    return resolved
