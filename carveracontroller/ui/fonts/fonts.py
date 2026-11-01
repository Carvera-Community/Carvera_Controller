"""Fonts for the interface: the bundled ARIALUNI plus a theme's family or file.

Kivy's SDL2 provider resolves ``font_name`` to a registered alias or a font
file. It does not look up a family name. This module does that lookup and
returns an alias whose four slots (regular, italic, bold, bold italic) are
files of the chosen face: fontconfig on Linux, the font registry on Windows,
Core Text on macOS and iOS, and the system font configuration on Android. A
collection face other than 0 is left out, because Kivy opens face 0.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
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
    only italic or oblique is regular italic. A style that is only a width, or
    an unknown word, is skipped. A lower penalty wins when two files share a
    weight: the plain Regular file beats Book and Bold Condensed.
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
        if italic:
            return (WEIGHT_REGULAR, True, skipped)
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


def _is_font_path(value: str) -> bool:
    """A theme value that names a file, not a family."""
    return "/" in value or "\\" in value or value.lower().endswith(FONT_EXTENSIONS)


def _is_font_file(path: str) -> bool:
    return os.path.isfile(path) and path.lower().endswith(FONT_EXTENSIONS)


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


# Linux. A timeout is not cached, so the next lookup tries ``fc-list`` again.
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


# Windows. Entries are read from the machine hive, then the user hive, so a
# per-user font overrides the same family.
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


# macOS, and iOS when Core Text can list the file behind each face.
_CF_STRING_UTF8 = 0x08000100


def _load_apple_framework(name: str):
    """Core Text or Core Foundation.

    macOS has the binary on disk. iOS serves the same framework from the dyld
    shared cache, which opens by framework name when the absolute path does not.
    """
    absolute = f"/System/Library/Frameworks/{name}.framework/{name}"
    try:
        return ctypes.cdll.LoadLibrary(absolute)
    except OSError:
        logger.debug("Could not open %s; trying the framework name", absolute, exc_info=True)
        return ctypes.cdll.LoadLibrary(name)


def _declare(function, argtypes, restype) -> None:
    function.argtypes = argtypes
    function.restype = restype


def _declare_core_foundation(core_foundation) -> None:
    """Pointer-sized Core Foundation signatures.

    ctypes otherwise passes a CFTypeRef as a 32-bit int. On arm64 macOS that
    truncated word is a tagged object such as an NSDate or NSNumber, and the
    ``length`` message aborts the process. The NSException is not a Python
    exception, so the signatures have to be right before the first call.
    """
    pointer = ctypes.c_void_p
    index = ctypes.c_long
    type_id = ctypes.c_ulong
    boolean = ctypes.c_uint8
    _declare(core_foundation.CFGetTypeID, [pointer], type_id)
    _declare(core_foundation.CFStringGetTypeID, [], type_id)
    _declare(core_foundation.CFURLGetTypeID, [], type_id)
    _declare(core_foundation.CFStringCreateWithCString, [pointer, ctypes.c_char_p, ctypes.c_uint32], pointer)
    _declare(core_foundation.CFStringGetLength, [pointer], index)
    _declare(core_foundation.CFStringGetCString, [pointer, ctypes.c_char_p, index, ctypes.c_uint32], boolean)
    _declare(core_foundation.CFRelease, [pointer], None)
    _declare(core_foundation.CFArrayGetCount, [pointer], index)
    _declare(core_foundation.CFArrayGetValueAtIndex, [pointer, index], pointer)
    _declare(
        core_foundation.CFURLGetFileSystemRepresentation,
        [pointer, boolean, ctypes.c_char_p, index],
        boolean,
    )


def _cf_type_is(core_foundation, ref, get_type_id) -> bool:
    return bool(ref) and core_foundation.CFGetTypeID(ref) == get_type_id()


def _cf_string(core_foundation, text: str):
    _declare_core_foundation(core_foundation)
    return core_foundation.CFStringCreateWithCString(None, text.encode("utf-8"), _CF_STRING_UTF8)


def _py_string(core_foundation, ref) -> str:
    """A CFString as a Python str. A date, URL, or other CF type yields ``""``."""
    _declare_core_foundation(core_foundation)
    if not _cf_type_is(core_foundation, ref, core_foundation.CFStringGetTypeID):
        return ""
    length = core_foundation.CFStringGetLength(ref)
    size = int(length) * 4 + 1
    buffer = ctypes.create_string_buffer(size)
    if not core_foundation.CFStringGetCString(ref, buffer, size, _CF_STRING_UTF8):
        return ""
    return buffer.value.decode("utf-8")


def _cf_path(core_foundation, ref) -> str:
    """Filesystem path of a CFURL. Anything that is not a URL yields ``""``."""
    _declare_core_foundation(core_foundation)
    if not _cf_type_is(core_foundation, ref, core_foundation.CFURLGetTypeID):
        return ""
    path_buffer = ctypes.create_string_buffer(4096)
    if not core_foundation.CFURLGetFileSystemRepresentation(ref, 1, path_buffer, len(path_buffer)):
        return ""
    return path_buffer.value.decode("utf-8")


def _macos_descriptor_records() -> list[tuple[str, str, str, int]] | None:
    """Every file-backed face Core Text publishes, or ``None`` when the call fails."""
    try:
        core_text = _load_apple_framework("CoreText")
        core_foundation = _load_apple_framework("CoreFoundation")
    except OSError:
        return None
    pointer = ctypes.c_void_p
    try:
        _declare_core_foundation(core_foundation)
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
                path = _cf_path(core_foundation, url)
                if not family or not path:
                    continue
                records.append((family, style, path, 0))
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
    core_text = _load_apple_framework("CoreText")
    core_foundation = _load_apple_framework("CoreFoundation")
    pointer = ctypes.c_void_p

    _declare_core_foundation(core_foundation)
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
                path = _cf_path(core_foundation, url)
                if not path:
                    continue
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


# Family and weight read from the font file itself. Android uses this when
# its font configuration cannot be read, and iOS uses it when Core Text
# returns nothing.

# A filename may glue a style on in camel case (Roboto-BoldItalic, RobotoSemiBold).
# Longest first, so BoldItalic is not read as Italic.
_CAMEL_STYLE_SUFFIXES = (
    "SemiBoldItalic",
    "ExtraLightItalic",
    "BoldItalic",
    "BoldOblique",
    "ExtraLight",
    "UltraLight",
    "SemiBold",
    "DemiBold",
    "ExtraBold",
    "UltraBold",
    "SemiLight",
    "Hairline",
    "Regular",
    "Oblique",
    "Medium",
    "Normal",
    "Italic",
    "Roman",
    "Light",
    "Black",
    "Heavy",
    "Bold",
    "Thin",
    "Book",
)


def _style_compacts() -> set[str]:
    """Style words that are a whole filename chunk, not part of a family name."""
    compacts = set(_ITALIC_WORDS)
    for alias in _WEIGHT_LOOKUP:
        compact = _normalize(alias)
        compacts.add(compact)
        for slant in _ITALIC_WORDS:
            compacts.add(compact + slant)
    return compacts


_STYLE_CHUNK_COMPACT = _style_compacts()


def _camel_words(text: str) -> list[str]:
    return re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", text)


def _chunk_is_only_style(chunk: str) -> bool:
    return _normalize(chunk) in _STYLE_CHUNK_COMPACT


def _strip_glued_style(chunk: str) -> str:
    changed = True
    while changed and chunk:
        changed = False
        for suffix in _CAMEL_STYLE_SUFFIXES:
            if len(chunk) <= len(suffix) or not chunk.endswith(suffix):
                continue
            boundary = chunk[-len(suffix) - 1]
            if boundary.islower() or boundary.isdigit():
                chunk = chunk[: -len(suffix)]
                changed = True
                break
    return chunk


def _font_filename_parts(path: str) -> tuple[list[str], list[str]]:
    """Family chunks, and the style chunks peeled off a font file name.

    A trailing chunk that is only a weight or slant is a style, and so is a
    style glued on in camel case. A file whose whole name is a style keeps
    that chunk as the family too.
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    chunks = [chunk for chunk in re.split(r"[-_\s]+", stem) if chunk]
    styles: list[str] = []
    while len(chunks) > 1 and _chunk_is_only_style(chunks[-1]):
        styles.append(chunks.pop())
    if len(chunks) == 1 and _chunk_is_only_style(chunks[0]):
        styles.append(chunks[0])
    elif chunks:
        stripped = _strip_glued_style(chunks[-1])
        if stripped != chunks[-1]:
            styles.append(chunks[-1][len(stripped) :])
    if chunks:
        chunks[-1] = _strip_glued_style(chunks[-1]) or chunks[-1]
    return chunks, styles


def _family_from_filename(path: str) -> str:
    """``Roboto-BoldItalic.ttf`` and ``NotoSansCJK-Regular.ttc`` become family names.

    Used when the name table cannot be read. A hyphen chunk that is only a
    weight or slant is dropped. Condensed and Mono stay, because they are
    different families.
    """
    chunks, _styles = _font_filename_parts(path)
    words = [word for chunk in chunks for word in (_camel_words(chunk) or [chunk])]
    return " ".join(words)


def _pretty_family(name: str) -> str:
    parts = [part for part in re.split(r"[-_\s]+", name.strip()) if part]
    return " ".join(part.capitalize() for part in parts)


def _weight_and_italic_from_filename(path: str) -> tuple[int, bool]:
    _chunks, styles = _font_filename_parts(path)
    if not styles:
        return _WEIGHT_ORDER[WEIGHT_REGULAR], False
    words = [word for chunk in reversed(styles) for word in (_camel_words(chunk) or [chunk])]
    classified = _classify_style(" ".join(words))
    if classified is None:
        return _WEIGHT_ORDER[WEIGHT_REGULAR], False
    weight, italic, _penalty = classified
    return _WEIGHT_ORDER[weight], italic


def _decode_font_name(raw: bytes, platform: int, encoding: int) -> str:
    if platform in (0, 3):
        text = raw.decode("utf-16-be")
    elif platform == 1 and encoding == 0:
        text = raw.decode("mac_roman")
    else:
        text = raw.decode("utf-8")
    return text.replace("\x00", "").strip()


def _font_name_rank(platform: int, encoding: int, language: int, name_id: int) -> tuple[int, int]:
    """Lower is better. The typographic family outranks the legacy family name."""
    identity = 0 if name_id == 16 else 1
    windows_unicode = platform == 3 and encoding in (0, 1, 10)
    if windows_unicode and language == 0x409:
        source = 0
    elif windows_unicode:
        source = 1
    elif platform == 0:
        source = 2
    elif platform == 1 and encoding == 0:
        source = 3
    else:
        source = 4
    return (identity, source)


def _clean_family_name(name: str) -> str | None:
    split = _split_registry_name(name)
    if split is None:
        return None
    family = split[0].strip()
    if not family:
        return None
    return family


def _family_from_name_table(table: bytes) -> str | None:
    if len(table) < 6:
        return None
    count = int.from_bytes(table[2:4], "big")
    string_offset = int.from_bytes(table[4:6], "big")
    best: tuple[tuple[int, int], str] | None = None
    for index in range(count):
        rec = 6 + index * 12
        if rec + 12 > len(table):
            break
        fields = [int.from_bytes(table[rec + part : rec + part + 2], "big") for part in range(0, 12, 2)]
        platform, encoding, language, name_id, length, offset = fields
        if name_id not in (1, 16):
            continue
        start = string_offset + offset
        end = start + length
        if start < 0 or end > len(table):
            continue
        try:
            text = _decode_font_name(table[start:end], platform, encoding)
        except UnicodeDecodeError:
            continue
        if not text:
            continue
        rank = _font_name_rank(platform, encoding, language, name_id)
        if best is None or rank < best[0]:
            best = (rank, text)
    if best is None:
        return None
    return _clean_family_name(best[1])


def _sfnt_family(path: str) -> str | None:
    """Family of face 0 from the font's name table, without loading the whole file."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(12)
            if len(header) < 12:
                return None
            if header[:4] == b"ttcf":
                count = int.from_bytes(header[8:12], "big")
                offset_bytes = handle.read(4)
                if count < 1 or len(offset_bytes) < 4:
                    return None
                start = int.from_bytes(offset_bytes, "big")
                handle.seek(start)
                header = handle.read(12)
                if len(header) < 12:
                    return None
            if header[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"):
                return None
            num_tables = int.from_bytes(header[4:6], "big")
            if num_tables < 1 or num_tables > 128:
                return None
            directory = handle.read(num_tables * 16)
            if len(directory) < num_tables * 16:
                return None
            name_offset = name_length = None
            for index in range(num_tables):
                entry = index * 16
                if directory[entry : entry + 4] != b"name":
                    continue
                name_offset = int.from_bytes(directory[entry + 8 : entry + 12], "big")
                name_length = int.from_bytes(directory[entry + 12 : entry + 16], "big")
                break
            if name_offset is None or name_length is None or name_length < 6 or name_length > 1_000_000:
                return None
            handle.seek(name_offset)
            table = handle.read(name_length)
    except OSError:
        logger.debug("Could not read font name from %s", path, exc_info=True)
        return None
    if len(table) < name_length:
        return None
    return _family_from_name_table(table)


def _nearest_weight_name(weight: int) -> str:
    return min(_WEIGHT_ORDER, key=lambda name: (abs(_WEIGHT_ORDER[name] - weight), _WEIGHT_ORDER[name]))


def _style_label(weight: int, italic: bool) -> str:
    name = _nearest_weight_name(weight)
    if not italic:
        return name
    if name == WEIGHT_REGULAR:
        return "Italic"
    return f"{name} Italic"


def _is_emoji_family(name: str) -> bool:
    return "emoji" in name.casefold()


def _family_label(path: str, hint: str, cache: dict[str, str | None]) -> str:
    if path not in cache:
        cache[path] = _sfnt_family(path)
    found = cache[path]
    if found:
        return found
    return _family_from_filename(path) or _pretty_family(hint)


def _directory_faces(font_dirs: tuple[str, ...]) -> list[tuple[str, int, bool, str]]:
    """Every font file under ``font_dirs``. Weight and slant come from the file name."""
    faces = []
    seen = set()
    for directory in font_dirs:
        if not os.path.isdir(directory):
            continue
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            logger.debug("Font directory unavailable: %s", directory, exc_info=True)
            continue
        for name in names:
            path = os.path.join(directory, name)
            if path in seen or not _is_font_file(path) or "emoji" in name.casefold():
                continue
            seen.add(path)
            weight, italic = _weight_and_italic_from_filename(path)
            faces.append(("", weight, italic, path))
    return faces


def _collapse_faces(
    faces: list[tuple[str, int, bool, str]],
) -> list[tuple[str, int, bool, str]]:
    """One file is one face. A variable font listed at several weights keeps the one nearest Regular."""
    labels: dict[str, str | None] = {}
    best: dict[tuple[str, bool, str], tuple[int, int, tuple[str, int, bool, str]]] = {}
    for order, (hint, weight, italic, path) in enumerate(faces):
        family = _family_label(path, hint, labels)
        if not family or _is_emoji_family(family):
            continue
        key = (_normalize(family), italic, path)
        chosen = (family, weight, italic, path)
        distance = abs(weight - _WEIGHT_ORDER[WEIGHT_REGULAR])
        current = best.get(key)
        if current is None or distance < current[0]:
            best[key] = (distance, order, chosen)
    return [item for _distance, _order, item in sorted(best.values(), key=lambda row: row[1])]


def _index_from_faces(faces: list[tuple[str, int, bool, str]]) -> dict[str, tuple[FontFace, ...]]:
    """Family index for face 0. The same file listed at several weights is kept once."""
    records = [
        (family, _style_label(weight, italic), path, 0) for family, weight, italic, path in _collapse_faces(faces)
    ]
    return _index_from_records(records, trust_face=True)


# Base config, then product and OEM overlays. Later files add families.
_ANDROID_FONT_CONFIGS = (
    "/system/etc/fonts.xml",
    "/product/etc/fonts_customization.xml",
    "/system_ext/etc/fonts_customization.xml",
    "/oem/etc/fonts_customization.xml",
)
_ANDROID_FONT_DIRS = (
    "/system/fonts",
    "/product/fonts",
    "/system_ext/fonts",
    "/oem/fonts",
)


def _xml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _resolve_android_font(name: str, font_dirs: tuple[str, ...]) -> str | None:
    """A config's font filename, under one of the system font directories."""
    name = name.strip().strip("\x00")
    if not name or "emoji" in os.path.basename(name).casefold():
        return None
    if os.path.isabs(name):
        return name if _is_font_file(name) else None
    if os.path.basename(name) != name:
        return None
    for directory in font_dirs:
        path = os.path.join(directory, name)
        if _is_font_file(path):
            return path
    return None


def _elements_named(family: ET.Element, tag: str) -> list[ET.Element]:
    """``tag`` elements inside one family. Legacy files sit under ``<fileset>``."""
    return [child for child in family.iter() if child is not family and _xml_local(child.tag) == tag]


def _android_font_children(family: ET.Element) -> list[tuple[int, bool, str, int]]:
    """``(weight, italic, filename, face)`` from ``<font>`` or legacy ``<file>`` children."""
    fonts = _elements_named(family, "font")
    if fonts:
        rows = []
        for font in fonts:
            filename = (font.text or "").strip()
            try:
                face = int(font.get("index") or "0")
            except ValueError:
                continue
            try:
                weight = int(font.get("weight") or "400")
            except ValueError:
                weight = 400
            style = (font.get("style") or "normal").strip().casefold()
            rows.append((weight, style in _ITALIC_WORDS, filename, face))
        return rows
    # Pre-Lollipop system_fonts.xml lists regular, bold, italic, bold italic.
    files = _elements_named(family, "file")
    legacy = ((400, False), (700, False), (400, True), (700, True))
    return [(weight, italic, (child.text or "").strip(), 0) for child, (weight, italic) in zip(files, legacy)]


def _android_config_faces(path: str, font_dirs: tuple[str, ...]) -> list[tuple[str, int, bool, str]]:
    """Named faces in one ``fonts.xml`` or customization file. Face 0 only."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        logger.warning("Could not read Android font config %s", path, exc_info=True)
        return []
    faces = []
    for family in root.iter():
        if _xml_local(family.tag) != "family":
            continue
        hint = (family.get("name") or "").strip()
        for weight, italic, filename, face in _android_font_children(family):
            if face != 0:
                continue
            resolved = _resolve_android_font(filename, font_dirs)
            if resolved is None:
                continue
            faces.append((hint, weight, italic, resolved))
    return faces


def _android_font_index(
    configs: tuple[str, ...] | None = None,
    font_dirs: tuple[str, ...] | None = None,
) -> dict[str, tuple[FontFace, ...]]:
    """Installed faces from Android's font configuration.
    ``fonts.xml`` names each file, its weight, and its face index.
    Product overlays add OEM families such as Google Sans.
    Kivy draws face 0 of a collection, so other faces are left out.
    A variable font is one file repeated at several weights; Kivy cannot
    select an axis, so that file is kept once, at the weight nearest Regular.
    """
    chosen_configs = _ANDROID_FONT_CONFIGS if configs is None else configs
    chosen_dirs = _ANDROID_FONT_DIRS if font_dirs is None else font_dirs
    try:
        faces: list[tuple[str, int, bool, str]] = []
        for config in chosen_configs:
            if os.path.isfile(config):
                faces.extend(_android_config_faces(config, chosen_dirs))
        if not faces:
            faces.extend(_directory_faces(chosen_dirs))
        index = _index_from_faces(faces)
    except (OSError, ValueError):
        logger.warning("Android font scan failed", exc_info=True)
        return {}
    if not index:
        logger.warning("No Android system fonts found; the font list will only offer %s", ARIALUNI)
    return index


# Loose files, then the folders current iOS releases actually use.
_IOS_FONT_DIRS = (
    "/System/Library/Fonts",
    "/System/Library/Fonts/Core",
    "/System/Library/Fonts/CoreAddition",
    "/System/Library/Fonts/LanguageSupport",
    "/System/Library/Fonts/AppFonts",
)


def _ios_font_index(font_dirs: tuple[str, ...] | None = None) -> dict[str, tuple[FontFace, ...]]:
    """Installed faces on iOS.

    Core Text names each file-backed face. When that list is empty, the system
    font directories are read by filename and name table, the same way an
    Android device with no ``fonts.xml`` is read.
    """
    index = _macos_font_index()
    if index:
        return index
    chosen_dirs = _IOS_FONT_DIRS if font_dirs is None else font_dirs
    try:
        index = _index_from_faces(_directory_faces(chosen_dirs))
    except (OSError, ValueError):
        logger.warning("iOS font directory scan failed", exc_info=True)
        return {}
    if not index:
        logger.warning("No iOS system fonts found; the font list will only offer %s", ARIALUNI)
    return index


# One scan for the process, then the Kivy name of each theme role.


def _load_font_index() -> dict | None:
    """Installed faces, or ``None`` when the scan should be retried."""
    from carveracontroller.main import is_android, is_ios

    if is_android():
        return _android_font_index()
    if is_ios() or sys.platform == "ios":
        return _ios_font_index()
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
