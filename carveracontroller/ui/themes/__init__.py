"""Theme package. Bundled palettes live in ``bundled/``; ``dark`` is the full token schema."""

from __future__ import annotations

import json
import logging
import re
from functools import cache
from pathlib import Path

from carveracontroller.ui.fonts import FontSpecError, normalize_font_spec

logger = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parents[2]
THEMES_DIR = Path(__file__).resolve().parent / "bundled"
BASE_THEME = "dark"
DEFAULT_THEME = BASE_THEME
# The one user-saved palette. It lives under the app data directory, not in this package.
CUSTOM_THEME = "custom"
CUSTOM_TITLE = "Custom"
_user_themes_dir: Path | None = None

# Each name is the g-code highlight token gcode_<name>.
GCODE_SYNTAX_CATEGORIES = (
    "comment",
    "g_command",
    "m_command",
    "coordinate",
    "feedrate",
    "spindle",
    "tool",
    "line_number",
    "parameter",
    "o_label",
    "o_keyword",
    "param_ref",
    "math_keyword",
    "shell_command",
)

# Font roles a theme may set under ``"fonts"``. A role left out falls back to
# ``default``, and ``default`` falls back to the bundled ARIALUNI.
FONT_ROLES = ("default", "top_bar", "jog_pad", "code_list")
_FONT_EXTENSIONS = (".ttf", ".otf", ".ttc")

# Boolean options under ``"behaviors"``. A key left out stays at the parent's
# value, and a key nobody sets stays off.
BEHAVIOR_KEYS = (
    "jog_pad_axis_colors",
    "jog_pad_sign_colors",
    "jog_pad_axis_background",
    "group_main_menu",
)
_AXIS_LETTERS = "XYZA"

_RESERVED_KEYS = {"name", "title", "extends", "fonts", "behaviors"}
# A theme JSON object whose inner keys rebuild a flat token. The value is the
# prefix added to each inner key. ``layout`` keys are already the token names.
_GROUP_PREFIXES = {
    "machine": "machine_",
    "axis": "axis_",
    "map": "map_",
    "gcode": "gcode_",
    "sketch": "sketch_",
    "cmm": "cmm_",
    "facing": "facing_",
    "viewer": "viewer_",
    "graph": "graph_",
    "speed_colormap": "speed_colormap_",
    "tooltip": "tooltip_",
    "scroll": "scroll_",
    "layout": "",
}
# Longest prefix first, so ``speed_colormap_`` is not read as some shorter group.
_PREFIX_GROUPS = sorted(
    ((prefix, group) for group, prefix in _GROUP_PREFIXES.items() if prefix),
    key=lambda item: len(item[0]),
    reverse=True,
)
_LAYOUT_KEYS = frozenset(
    {
        "radius_s",
        "radius_m",
        "radius_l",
        "pad_radius",
        "top_bar_radius",
        "top_bar_height",
        "bottom_bar_height",
        "bar_padding",
        "spacing",
        "control_page_min",
        "pad_row_height",
    }
)
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


class ThemeError(ValueError):
    """A theme file is missing, malformed or inconsistent with the base theme."""


def parse_hex_color(value: str) -> list:
    """Convert ``#rrggbb`` / ``#rrggbbaa`` to 0-1 RGBA channels."""
    if not isinstance(value, str) or not _HEX_RE.match(value):
        raise ThemeError(f"Theme color must be '#rrggbb' or '#rrggbbaa', got {value!r}")
    digits = value[1:]
    channels = [int(digits[i : i + 2], 16) / 255.0 for i in range(0, len(digits), 2)]
    if len(channels) == 3:
        channels.append(1.0)
    return channels


def gcode_syntax_colors(source) -> dict:
    """``{category: '#rrggbb'}`` from a palette dict or a live theme object."""
    colors = {}
    for category in GCODE_SYNTAX_CATEGORIES:
        key = f"gcode_{category}"
        value = source[key] if isinstance(source, dict) else getattr(source, key)
        colors[category] = value if isinstance(value, str) else format_hex_color(value)
    return colors


def format_hex_color(rgba) -> str:
    """Inverse of :func:`parse_hex_color` for 0-1 channels (alpha omitted when opaque)."""
    channels = [int(round(float(channel) * 255)) for channel in rgba]
    if len(channels) == 3:
        channels.append(255)
    text = "#" + "".join(f"{channel:02x}" for channel in channels[:3])
    if channels[3] != 255:
        text += f"{channels[3]:02x}"
    return text


def set_user_themes_dir(path) -> None:
    """Directory of ``custom.json``. ``None`` leaves only the built-in themes.

    The palette cache is cleared, so a Custom theme saved or removed since the
    last load is picked up on the next read.
    """
    global _user_themes_dir
    _user_themes_dir = None if path is None else Path(path)
    _load_cached.cache_clear()


def user_themes_dir() -> Path | None:
    """Directory set by :func:`set_user_themes_dir`, or ``None`` when Custom is unavailable."""
    return _user_themes_dir


def clear_theme_cache() -> None:
    """Drop cached palettes so the next load reads the theme files again."""
    _load_cached.cache_clear()


def _check_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ThemeError(f"Invalid theme name {name!r}")
    return name


def _theme_path(name: str) -> Path:
    """File for ``name``. Custom is read from the user directory when one is set."""
    checked = _check_name(name)
    if checked == CUSTOM_THEME and _user_themes_dir is not None:
        return Path(_user_themes_dir) / f"{CUSTOM_THEME}.json"
    return THEMES_DIR / f"{checked}.json"


def _read_raw(name: str) -> dict:
    path = _theme_path(name)
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        known = ", ".join(sorted(item.stem for item in THEMES_DIR.glob("*.json") if item.stem != CUSTOM_THEME))
        raise ThemeError(f"Unknown theme {name!r}. Known: {known}") from None
    except json.JSONDecodeError as error:
        raise ThemeError(f"Theme {name!r} is not valid JSON: {error}") from None
    if not isinstance(data, dict):
        raise ThemeError(f"Theme {name!r} must be a JSON object")
    return data


def _group_for_flat_token(key: str) -> str | None:
    """The group a flat token belongs in, or ``None`` when it stays at the top level."""
    if key in _LAYOUT_KEYS:
        return "layout"
    for prefix, group in _PREFIX_GROUPS:
        if key.startswith(prefix) and len(key) > len(prefix):
            return group
    return None


def _merge_grouped(name: str, chain: tuple = ()) -> dict:
    """Tokens of ``name`` over its parent, with group objects merged key by key."""
    if name in chain:
        raise ThemeError(f"Theme inheritance loop: {' -> '.join((*chain, name))}")
    raw = _read_raw(name)
    parent = raw.get("extends")
    merged = dict(_merge_grouped(parent, (*chain, name))) if parent else {}
    for key, value in raw.items():
        if key in _RESERVED_KEYS:
            continue
        if key in _GROUP_PREFIXES:
            if not isinstance(value, dict):
                raise ThemeError(f"Theme {name!r}: {key!r} must be an object")
            group = dict(merged.get(key) or {})
            for inner, inner_value in value.items():
                if not isinstance(inner, str) or not inner:
                    raise ThemeError(f"Theme {name!r}: {key!r} has an empty key")
                group[inner] = inner_value
            merged[key] = group
            continue
        owner = _group_for_flat_token(key)
        if owner is not None:
            raise ThemeError(f"Theme {name!r}: token {key!r} belongs in {owner!r}")
        merged[key] = value
    return merged


def _flatten_groups(name: str, grouped: dict) -> dict:
    """Expand group objects to the flat token names the rest of the app uses."""
    tokens = {key: value for key, value in grouped.items() if key not in _GROUP_PREFIXES}
    for group, prefix in _GROUP_PREFIXES.items():
        entries = grouped.get(group)
        if not entries:
            continue
        for inner, value in entries.items():
            token = f"{prefix}{inner}"
            if token in tokens:
                raise ThemeError(f"Theme {name!r}: token {token!r} is set twice")
            tokens[token] = value
    return tokens


def _resolve(name: str, chain: tuple = ()) -> dict:
    """Flat tokens of ``name`` merged over the palette it extends."""
    return _flatten_groups(name, _merge_grouped(name, chain))


def _looks_like_path(value: str) -> bool:
    return "/" in value or "\\" in value or value.lower().endswith(_FONT_EXTENSIONS)


def _locate_font_file(value: str) -> str:
    """Absolute path of a font file named by ``value``, or ``value`` unchanged.

    A relative path is tried in the bundled themes folder, then in the
    ``carveracontroller`` package. A family name has no path form and passes through.
    """
    if not _looks_like_path(value):
        return value
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return str(candidate) if candidate.is_file() else value
    for base in (THEMES_DIR, _PACKAGE_DIR):
        located = (base / candidate).resolve()
        if located.is_file():
            return str(located)
    return value


def jog_axis_color(theme, caption: str):
    """Axis color for a jog caption such as ``X+``, or ``None`` when it is not one.

    The first character selects ``axis_x`` through ``axis_a``.
    """
    if not isinstance(caption, str) or not caption:
        return None
    letter = caption[0]
    if letter.upper() not in _AXIS_LETTERS:
        return None
    color = getattr(theme, f"axis_{letter.lower()}", None)
    if not isinstance(color, (list, tuple)):
        return None
    return color


def jog_axis_markup(caption: str, theme) -> tuple[str, bool]:
    """``(text, markup)`` for a jog key such as ``X+`` or ``X-``.

    ``jog_pad_axis_colors`` wraps the axis letter. ``jog_pad_sign_colors`` wraps
    the following ``+`` or ``-``. With both on, the letter and the sign share
    one color tag. ``jog_pad_axis_background`` leaves the caption plain: the
    key face already carries the axis color, and a matching glyph would vanish.
    """
    if not isinstance(caption, str):
        return "", False
    color = jog_axis_color(theme, caption)
    if color is None:
        return caption, False
    if getattr(theme, "jog_pad_axis_background", False):
        return caption, False
    color_letter = bool(getattr(theme, "jog_pad_axis_colors", False))
    color_sign = bool(getattr(theme, "jog_pad_sign_colors", False))
    if not color_letter and not color_sign:
        return caption, False
    letter = caption[0]
    rest = caption[1:]
    sign = rest[:1]
    tail = rest[1:]
    has_sign = sign in ("+", "-")
    painted = format_hex_color(color)
    if color_letter and color_sign and has_sign:
        return f"[color={painted}]{letter}{sign}[/color]{tail}", True
    if color_letter:
        return f"[color={painted}]{letter}[/color]{rest}", True
    if has_sign:
        return f"{letter}[color={painted}]{sign}[/color]{tail}", True
    return caption, False


def _merge_behaviors(name: str, chain: tuple = ()) -> dict:
    """Behavior flags of ``name`` merged over the theme it extends."""
    if name in chain:
        raise ThemeError(f"Theme inheritance loop: {' -> '.join((*chain, name))}")
    raw = _read_raw(name)
    parent = raw.get("extends")
    flags = _merge_behaviors(parent, (*chain, name)) if parent else {}
    behaviors = raw.get("behaviors")
    if behaviors is None:
        return flags
    if not isinstance(behaviors, dict):
        raise ThemeError(f"Theme {name!r}: 'behaviors' must be an object")
    unknown = sorted(set(behaviors) - set(BEHAVIOR_KEYS))
    if unknown:
        raise ThemeError(f"Theme {name!r} has unknown behaviors: {', '.join(unknown)}")
    for key, value in behaviors.items():
        if not isinstance(value, bool):
            raise ThemeError(f"Theme {name!r}: behavior {key!r} must be true or false")
        flags[key] = value
    return flags


def load_behaviors(name: str) -> dict:
    """``{behavior: bool}`` for every known behavior, inherited values included.

    A behavior the theme never sets is false. Raises :class:`ThemeError` when
    the theme is unknown or its ``behaviors`` are malformed.
    """
    _check_name(name)
    flags = dict.fromkeys(BEHAVIOR_KEYS, False)
    flags.update(_merge_behaviors(name))
    return flags


def _accept_font(name: str, role: str, value):
    """Stored font value, or a :class:`ThemeError` when it cannot be kept."""
    try:
        return normalize_font_spec(value)
    except FontSpecError:
        raise ThemeError(f"Theme {name!r}: font role {role!r} must be a font name, a path or null") from None


def _locate_font_value(value):
    """Resolve a path inside a font value. A family name passes through."""
    if isinstance(value, str):
        return _locate_font_file(value)
    located = _locate_font_file(value["family"])
    if located == value["family"]:
        return value
    return {**value, "family": located}


def _merge_font_specs(name: str, chain: tuple = ()) -> dict:
    """Font roles of ``name`` merged over the theme it extends.

    JSON ``null`` drops a role. A regular roman face is stored as a family name.
    Any other weight or style is ``{family, weight, style}``. Paths stay as written.
    """
    if name in chain:
        raise ThemeError(f"Theme inheritance loop: {' -> '.join((*chain, name))}")
    raw = _read_raw(name)
    parent = raw.get("extends")
    roles = _merge_font_specs(parent, (*chain, name)) if parent else {}
    fonts = raw.get("fonts")
    if fonts is None:
        return roles
    if not isinstance(fonts, dict):
        raise ThemeError(f"Theme {name!r}: 'fonts' must be an object")
    unknown = sorted(set(fonts) - set(FONT_ROLES))
    if unknown:
        raise ThemeError(f"Theme {name!r} has unknown font roles: {', '.join(unknown)}")
    for role, value in fonts.items():
        if value is None:
            roles.pop(role, None)
        else:
            roles[role] = _accept_font(name, role, value)
    return roles


def _resolve_fonts(name: str, chain: tuple = ()) -> dict:
    """Font roles of ``name``, with file paths resolved to an absolute path when the file exists."""
    return {role: _locate_font_value(value) for role, value in _merge_font_specs(name, chain).items()}


def load_font_specs(name: str) -> dict:
    """``{role: family name or path}`` as written in the theme files, inherited ones included.

    Relative paths stay relative. A role the theme sets to JSON ``null`` is omitted.
    """
    _check_name(name)
    return _merge_font_specs(name)


def load_fonts(name: str) -> dict:
    """``{role: family name or file path}`` for the roles ``name`` sets, inherited ones included.

    Raises :class:`ThemeError` when the theme is unknown or its ``fonts`` are malformed.
    """
    _check_name(name)
    return _resolve_fonts(name)


def _palette_value(value):
    """A color or a number, or ``None`` when ``value`` cannot be a token."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            return parse_hex_color(value)
        except ThemeError:
            return None
    if isinstance(value, (int, float)):
        return value
    return None


def _reject_token(name: str, key: str, value) -> None:
    if isinstance(value, str):
        try:
            parse_hex_color(value)
        except ThemeError as error:
            raise ThemeError(f"Theme {name!r}: token {key!r}: {error}") from None
    raise ThemeError(f"Theme {name!r}: token {key!r} must be a color or a number")


def _convert(name: str, tokens: dict) -> dict:
    """Colors and numbers. A token this build no longer has is dropped with a warning.

    A bad value for a token the base theme still defines fails the file. The
    base theme itself must be entirely valid: it is the schema.
    """
    palette: dict[str, list | int | float] = {}
    invalid: list[tuple[str, object]] = []
    for key, value in tokens.items():
        converted = _palette_value(value)
        if converted is None:
            invalid.append((key, value))
            continue
        palette[key] = converted
    if not invalid:
        return palette
    known = set() if name == BASE_THEME else set(load_palette(BASE_THEME))
    stale = sorted(key for key, _value in invalid if name != BASE_THEME and key not in known)
    if stale:
        logger.warning("Ignoring invalid tokens in theme %s: %s", name, ", ".join(stale))
    for key, value in invalid:
        if name == BASE_THEME or key in known:
            _reject_token(name, key, value)
    return palette


@cache
def _load_cached(name: str) -> dict:
    palette = _convert(name, _resolve(name))
    _resolve_fonts(name)
    _merge_behaviors(name)
    if name != BASE_THEME:
        base = load_palette(BASE_THEME)
        unknown = sorted(set(palette) - set(base))
        missing = sorted(set(base) - set(palette))
        if unknown:
            # A saved theme can name tokens this build no longer has. Drop those
            # and keep the rest, instead of discarding the theme.
            logger.warning("Ignoring unknown tokens in theme %s: %s", name, ", ".join(unknown))
            for key in unknown:
                del palette[key]
        if missing and name != CUSTOM_THEME:
            raise ThemeError(f"Theme {name!r} is missing tokens: {', '.join(missing)}")
        # A custom palette may leave a token out. Fill the gap from the base theme.
        for key in missing:
            value = base[key]
            palette[key] = list(value) if isinstance(value, list) else value
        for key, value in base.items():
            if isinstance(value, list) != isinstance(palette[key], list):
                raise ThemeError(f"Theme {name!r}: token {key!r} changes kind (color vs number)")
    return palette


def token_sections() -> list:
    """``[(group, [token, ...]), ...]`` in theme-file order. The first group is ``colors``."""
    palette = load_palette(BASE_THEME)
    grouped = {name: [] for name in _GROUP_PREFIXES}
    chrome = []
    for key in palette:
        owner = _group_for_flat_token(key)
        if owner is None:
            chrome.append(key)
        else:
            grouped[owner].append(key)
    sections = [("colors", chrome)]
    for name, keys in grouped.items():
        if keys:
            sections.append((name, keys))
    return sections


def theme_extends(name: str) -> str | None:
    """Parent named by ``extends``, or ``None`` when the file sets none.

    A blank, malformed, or self-referential parent is treated as unset.
    """
    parent = _read_raw(name).get("extends")
    if not isinstance(parent, str) or not _NAME_RE.match(parent.strip()) or parent.strip() == name:
        return None
    return parent.strip()


def custom_theme_document(
    tokens: dict,
    fonts: dict | None = None,
    behaviors: dict | None = None,
    extends: str | None = None,
) -> dict:
    """Full Custom theme snapshot in the grouped JSON shape the loader accepts.

    ``tokens`` are flat palette values (colors as 0-1 channels, sizes as numbers).
    ``extends`` records the theme this snapshot was based on. Tokens the file
    does not contain are then inherited from that theme. An empty optional font
    role is JSON null. A behavior left out of ``behaviors`` is false.
    """
    base = load_palette(BASE_THEME)
    extra = sorted(set(tokens) - set(base) - {"name"})
    missing = sorted(set(base) - set(tokens))
    if extra:
        raise ThemeError(f"Custom theme has unknown tokens: {', '.join(extra)}")
    if missing:
        raise ThemeError(f"Custom theme is missing tokens: {', '.join(missing)}")
    chrome: dict = {}
    groups: dict = {name: {} for name in _GROUP_PREFIXES}
    for key in base:
        value = tokens[key]
        if isinstance(value, bool) or not isinstance(value, (list, tuple, int, float)):
            raise ThemeError(f"Custom theme token {key!r} must be a color or a number")
        encoded = format_hex_color(value) if isinstance(value, (list, tuple)) else value
        owner = _group_for_flat_token(key)
        if owner is None:
            chrome[key] = encoded
        else:
            prefix = _GROUP_PREFIXES[owner]
            groups[owner][key[len(prefix) :]] = encoded
    document: dict = {"name": CUSTOM_THEME, "title": CUSTOM_TITLE}
    if extends is not None:
        parent = extends.strip() if isinstance(extends, str) else ""
        if not parent or not _NAME_RE.match(parent) or parent == CUSTOM_THEME:
            raise ThemeError(f"Custom theme cannot extend {extends!r}")
        document["extends"] = parent
    if fonts is not None:
        if not isinstance(fonts, dict):
            raise ThemeError("Custom theme fonts must be an object")
        written = {}
        for role in FONT_ROLES:
            value = fonts.get(role)
            if isinstance(value, str):
                value = value.strip()
            elif isinstance(value, dict):
                value = _accept_font(CUSTOM_THEME, role, value)
            else:
                value = ""
            if role == "default":
                written[role] = value or "ARIALUNI"
            else:
                written[role] = value or None
        document["fonts"] = written
    if behaviors is not None and not isinstance(behaviors, dict):
        raise ThemeError("Custom theme behaviors must be an object")
    written_behaviors = {}
    for key in BEHAVIOR_KEYS:
        value = False if behaviors is None else behaviors.get(key, False)
        if not isinstance(value, bool):
            raise ThemeError(f"Custom theme behavior {key!r} must be true or false")
        written_behaviors[key] = value
    document["behaviors"] = written_behaviors
    document.update(chrome)
    for group, entries in groups.items():
        if entries:
            document[group] = entries
    return document


def load_palette(name: str) -> dict:
    """Return the resolved palette: colors as 0-1 RGBA lists, metrics as numbers.

    Raises :class:`ThemeError` when the theme is unknown or inconsistent. A
    fresh copy is returned, so callers may modify it.
    """
    return {key: list(value) if isinstance(value, list) else value for key, value in _load_cached(name).items()}


def _append_listed_theme(themes: list, name: str) -> None:
    try:
        load_palette(name)
        raw_title = _read_raw(name).get("title")
        if isinstance(raw_title, str) and raw_title.strip():
            title = raw_title.strip()
        elif name == CUSTOM_THEME:
            title = CUSTOM_TITLE
        else:
            title = name.replace("_", " ").title()
    except ThemeError as error:
        logger.warning("Ignoring theme %s: %s", name, error)
        return
    themes.append((name, str(title)))


def list_themes() -> list:
    """``[(name, title), ...]`` for every valid theme file.

    Custom is included only when ``custom.json`` in the user themes directory loads,
    and then it is listed first. The base theme follows, then the other built-ins by name.
    A broken Custom file is skipped with a warning, same as a broken built-in.
    """
    themes = []
    for path in sorted(THEMES_DIR.glob("*.json")):
        if path.stem == CUSTOM_THEME:
            continue
        _append_listed_theme(themes, path.stem)
    if _user_themes_dir is not None and _theme_path(CUSTOM_THEME).is_file():
        _append_listed_theme(themes, CUSTOM_THEME)
    themes.sort(key=lambda item: (item[0] != CUSTOM_THEME, item[0] != BASE_THEME, item[0]))
    return themes


def theme_names() -> list:
    return [name for name, _title in list_themes()]


def theme_title(name: str) -> str:
    """Display name of a theme. An unknown or empty name is returned unchanged."""
    if not name:
        return ""
    for theme_name, title in list_themes():
        if theme_name == name:
            return title
    return name
