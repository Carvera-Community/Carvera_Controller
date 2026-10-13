"""JSON palettes in this directory. ``dark`` is the full token schema (no Kivy)."""

from __future__ import annotations

import json
import logging
import re
from functools import cache
from pathlib import Path

logger = logging.getLogger(__name__)

THEMES_DIR = Path(__file__).resolve().parent
BASE_THEME = "dark"
DEFAULT_THEME = BASE_THEME

# Syntax-highlight categories for the g-code list, MDI history and IntelliSense.
# Each one is the theme token ``gcode_<category>``.
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

_RESERVED_KEYS = {"name", "title", "extends"}
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


def _check_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ThemeError(f"Invalid theme name {name!r}")
    return name


def _read_raw(name: str) -> dict:
    path = THEMES_DIR / f"{_check_name(name)}.json"
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        known = ", ".join(sorted(path.stem for path in THEMES_DIR.glob("*.json")))
        raise ThemeError(f"Unknown theme {name!r}. Known: {known}") from None
    except json.JSONDecodeError as error:
        raise ThemeError(f"Theme {name!r} is not valid JSON: {error}") from None
    if not isinstance(data, dict):
        raise ThemeError(f"Theme {name!r} must be a JSON object")
    return data


def _resolve(name: str, chain: tuple = ()) -> dict:
    """Raw tokens of ``name`` merged over the palette it extends."""
    if name in chain:
        raise ThemeError(f"Theme inheritance loop: {' -> '.join((*chain, name))}")
    raw = _read_raw(name)
    parent = raw.get("extends")
    tokens = _resolve(parent, (*chain, name)) if parent else {}
    tokens.update({key: value for key, value in raw.items() if key not in _RESERVED_KEYS})
    return tokens


def _convert(name: str, tokens: dict) -> dict:
    palette: dict[str, list | int | float] = {}
    for key, value in tokens.items():
        if isinstance(value, bool):
            raise ThemeError(f"Theme {name!r}: token {key!r} must be a color or a number")
        if isinstance(value, str):
            try:
                palette[key] = parse_hex_color(value)
            except ThemeError as error:
                raise ThemeError(f"Theme {name!r}: token {key!r}: {error}") from None
        elif isinstance(value, (int, float)):
            palette[key] = value
        else:
            raise ThemeError(f"Theme {name!r}: token {key!r} must be a color or a number")
    return palette


@cache
def _load_cached(name: str) -> dict:
    palette = _convert(name, _resolve(name))
    if name != BASE_THEME:
        base = load_palette(BASE_THEME)
        unknown = sorted(set(palette) - set(base))
        missing = sorted(set(base) - set(palette))
        if unknown:
            raise ThemeError(f"Theme {name!r} has unknown tokens: {', '.join(unknown)}")
        if missing:
            raise ThemeError(f"Theme {name!r} is missing tokens: {', '.join(missing)}")
        for key, value in base.items():
            if isinstance(value, list) != isinstance(palette[key], list):
                raise ThemeError(f"Theme {name!r}: token {key!r} changes kind (color vs number)")
    return palette


def load_palette(name: str) -> dict:
    """Return the resolved palette: colors as 0-1 RGBA lists, metrics as numbers.

    Raises :class:`ThemeError` when the theme is unknown or inconsistent. A
    fresh copy is returned, so callers may modify it.
    """
    return {key: list(value) if isinstance(value, list) else value for key, value in _load_cached(name).items()}


def list_themes() -> list:
    """``[(name, title), ...]`` for every valid theme file, base theme first."""
    themes = []
    for path in sorted(THEMES_DIR.glob("*.json")):
        name = path.stem
        try:
            load_palette(name)
            title = _read_raw(name).get("title") or name.replace("_", " ").title()
        except ThemeError as error:
            logger.warning("Ignoring theme %s: %s", name, error)
            continue
        themes.append((name, str(title)))
    themes.sort(key=lambda item: (item[0] != BASE_THEME, item[0]))
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
