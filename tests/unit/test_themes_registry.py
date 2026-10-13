"""Theme palette files in ``ui/themes``: loading, inheritance and consistency."""

import json
from pathlib import Path

import pytest

from carveracontroller.CNC import GCODE_DEFAULT_COLORS
from carveracontroller.ui import themes
from carveracontroller.ui.themes import (
    GCODE_SYNTAX_CATEGORIES,
    ThemeError,
    format_hex_color,
    gcode_syntax_colors,
    list_themes,
    load_palette,
    parse_hex_color,
    theme_title,
)

_ROOT = Path(__file__).resolve().parents[2]


def _luminance(rgba) -> float:
    def linear(channel):
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in rgba[:3])
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground, background) -> float:
    high, low = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_hex_parsing_and_formatting():
    assert parse_hex_color("#ff0000") == pytest.approx([1, 0, 0, 1])
    assert parse_hex_color("#00000080") == pytest.approx([0, 0, 0, 128 / 255])
    assert format_hex_color([1, 0, 0, 1]) == "#ff0000"
    assert format_hex_color([0, 0, 0, 128 / 255]) == "#00000080"
    for bad in ("ff0000", "#fff", "#gg0000", "#12345", 5, None):
        with pytest.raises(ThemeError):
            parse_hex_color(bad)


def test_built_in_themes_are_listed_base_first():
    names = [name for name, _title in list_themes()]
    assert names[0] == "dark"
    assert theme_title("") == ""
    assert theme_title("missing") == "missing"


def test_every_built_in_theme_has_exactly_the_base_tokens():
    base = load_palette("dark")
    for name, _title in list_themes():
        palette = load_palette(name)
        assert set(palette) == set(base), name
        for key, value in base.items():
            assert isinstance(palette[key], list) == isinstance(value, list), (name, key)


def test_colors_are_unit_range_rgba_and_metrics_are_numbers():
    for name, _title in list_themes():
        for key, value in load_palette(name).items():
            if isinstance(value, list):
                assert len(value) == 4, (name, key)
                assert all(0.0 <= channel <= 1.0 for channel in value), (name, key)
            else:
                assert isinstance(value, (int, float)), (name, key)


def test_light_inherits_metrics_and_overrides_colors():
    dark, light = load_palette("dark"), load_palette("light")
    assert light["radius_m"] == dark["radius_m"]
    assert light["top_bar_height"] == dark["top_bar_height"]
    assert light["bg"] != dark["bg"]
    assert _luminance(light["bg"]) > _luminance(dark["bg"])


def test_dark_syntax_colors_match_the_highlighter_fallback():
    assert gcode_syntax_colors(load_palette("dark")) == GCODE_DEFAULT_COLORS


def test_light_gcode_syntax_is_readable_on_the_list():
    # Keywords are drawn on the g-code rows: white normally, grey when selected.
    light = load_palette("light")
    for category in GCODE_SYNTAX_CATEGORIES:
        color = light[f"gcode_{category}"]
        for background in ("surface_raised", "control"):
            ratio = _contrast(color, light[background])
            assert ratio >= 4.5, (category, background, round(ratio, 2))
    for background in ("bg", "surface", "surface_raised"):
        ratio = _contrast(light["active_color"], light[background])
        assert ratio >= 4.5, (background, round(ratio, 2))


def test_light_panel_matches_the_dialog():
    # Tab content is filled with panel. A darker panel is a grey well inside
    # the light dialog. Dark keeps its own panel color.
    light = load_palette("light")
    assert light["panel"] == light["surface"]
    assert _luminance(light["panel"]) > _luminance(light["bg"])


def test_light_page_is_softer_than_the_jog_pads():
    # Lists and dialogs still use a white card on the page grey. The control
    # page itself is painted separately so it can match the window.
    light = load_palette("light")
    assert _contrast(light["surface_raised"], light["surface"]) >= 1.15
    assert _luminance(light["surface"]) < _luminance(light["surface_raised"])
    assert light["surface"] != light["bg"]


def test_light_mdi_status_text_is_readable_on_the_list():
    # Machine replies and status lines use info_text on the white list rows.
    # The dark palette's info color is a light cyan and must not be inherited.
    light = load_palette("light")
    for background in ("surface_raised", "surface", "field_bg"):
        ratio = _contrast(light["info_text"], light[background])
        assert ratio >= 7, (background, round(ratio, 2))
    assert _contrast(light["hint_text"], light["field_bg"]) >= 4.5


def test_light_theme_text_is_readable():
    light = load_palette("light")
    for background in ("bg", "surface", "panel", "menu", "row", "control"):
        assert _contrast(light["text"], light[background]) >= 7, background
    for background in ("bg", "surface", "panel"):
        assert _contrast(light["text_muted"], light[background]) >= 4.5, background
    for fill in ("accent", "primary", "danger", "help"):
        assert _contrast(light["text_on_fill"], light[fill]) >= 4.5, fill
    assert _contrast(light["text_disabled"], light["control_disabled"]) >= 2.5
    # Icons are light artwork multiplied by this tint. It stays readable, and
    # lighter than body text so the chrome is not a high-contrast theme.
    for background in ("bg", "surface", "surface_raised", "menu", "control"):
        assert _contrast(light["icon"], light[background]) >= 4.5, background
    assert _luminance(light["icon"]) > _luminance(light["text"])


def test_monokai_gcode_syntax_is_readable_on_the_list():
    # Syntax colors are drawn on the g-code row and on the selected row.
    mono = load_palette("monokai")
    for category in GCODE_SYNTAX_CATEGORIES:
        color = mono[f"gcode_{category}"]
        for background in ("surface_raised", "control", "tooltip_bg"):
            ratio = _contrast(color, mono[background])
            assert ratio >= 4.5, (category, background, round(ratio, 2))
    for background in ("bg", "surface", "surface_raised"):
        ratio = _contrast(mono["active_color"], mono[background])
        assert ratio >= 4.5, (background, round(ratio, 2))


def test_monokai_text_is_readable():
    mono = load_palette("monokai")
    for background in ("bg", "surface", "panel", "menu", "row", "control", "field_bg"):
        assert _contrast(mono["text"], mono[background]) >= 7, background
    for background in ("bg", "surface", "panel", "control"):
        assert _contrast(mono["text_muted"], mono[background]) >= 4.5, background
        assert _contrast(mono["text_secondary"], mono[background]) >= 4.5, background
    for token in (
        "accent_text",
        "info_text",
        "warning_text",
        "danger_text",
        "axis_x",
        "axis_y",
        "axis_z",
        "axis_a",
    ):
        assert _contrast(mono[token], mono["bg"]) >= 4.5, token
    for fill in (
        "accent",
        "primary",
        "primary_down",
        "danger",
        "danger_down",
        "help",
        "help_down",
        "success",
        "warning",
    ):
        assert _contrast(mono["text_on_fill"], mono[fill]) >= 4.5, fill
    assert _contrast(mono["success_text"], mono["success_fill"]) >= 4.5
    assert _contrast(mono["text_disabled"], mono["control_disabled"]) >= 2.5


def test_solarized_dark_gcode_syntax_is_readable_on_the_list():
    # Syntax colors are drawn on the g-code row and on the selected row.
    solarized = load_palette("solarized_dark")
    for category in GCODE_SYNTAX_CATEGORIES:
        color = solarized[f"gcode_{category}"]
        for background in ("surface_raised", "control", "tooltip_bg"):
            ratio = _contrast(color, solarized[background])
            assert ratio >= 4.5, (category, background, round(ratio, 2))
    for background in ("bg", "surface", "surface_raised"):
        ratio = _contrast(solarized["active_color"], solarized[background])
        assert ratio >= 4.5, (background, round(ratio, 2))


def test_solarized_dark_text_is_readable():
    solarized = load_palette("solarized_dark")
    for background in ("bg", "surface", "panel", "menu", "row", "control", "field_bg"):
        assert _contrast(solarized["text"], solarized[background]) >= 7, background
    for background in ("bg", "surface", "panel", "control"):
        assert _contrast(solarized["text_muted"], solarized[background]) >= 4.5, background
        assert _contrast(solarized["text_secondary"], solarized[background]) >= 4.5, background
    for token in (
        "accent_text",
        "info_text",
        "warning_text",
        "danger_text",
        "axis_x",
        "axis_y",
        "axis_z",
        "axis_a",
    ):
        assert _contrast(solarized[token], solarized["bg"]) >= 4.5, token
    for fill in (
        "accent",
        "primary",
        "primary_down",
        "danger",
        "danger_down",
        "help",
        "help_down",
        "success",
        "warning",
    ):
        assert _contrast(solarized["text_on_fill"], solarized[fill]) >= 4.5, fill
    assert _contrast(solarized["success_text"], solarized["success_fill"]) >= 4.5
    assert _contrast(solarized["text_disabled"], solarized["control_disabled"]) >= 2.5
    # Jog pads draw a surface_raised circle on the surface page.
    assert _contrast(solarized["surface_raised"], solarized["surface"]) >= 1.08


def test_nord_gcode_syntax_is_readable_on_the_list():
    # Syntax colors are drawn on the g-code row and on the selected row.
    nord = load_palette("nord")
    for category in GCODE_SYNTAX_CATEGORIES:
        color = nord[f"gcode_{category}"]
        for background in ("surface_raised", "control", "tooltip_bg"):
            ratio = _contrast(color, nord[background])
            assert ratio >= 4.5, (category, background, round(ratio, 2))
    for background in ("bg", "surface", "surface_raised"):
        ratio = _contrast(nord["active_color"], nord[background])
        assert ratio >= 4.5, (background, round(ratio, 2))


def test_nord_text_is_readable():
    nord = load_palette("nord")
    for background in ("bg", "surface", "panel", "menu", "row", "control", "field_bg"):
        assert _contrast(nord["text"], nord[background]) >= 7, background
    for background in ("bg", "surface", "panel", "control"):
        assert _contrast(nord["text_muted"], nord[background]) >= 4.5, background
        assert _contrast(nord["text_secondary"], nord[background]) >= 4.5, background
    for token in (
        "accent_text",
        "info_text",
        "warning_text",
        "danger_text",
        "axis_x",
        "axis_y",
        "axis_z",
        "axis_a",
    ):
        assert _contrast(nord[token], nord["bg"]) >= 4.5, token
    for fill in (
        "accent",
        "primary",
        "primary_down",
        "danger",
        "danger_down",
        "help",
        "help_down",
        "success",
        "warning",
    ):
        assert _contrast(nord["text_on_fill"], nord[fill]) >= 4.5, fill
    assert _contrast(nord["success_text"], nord["success_fill"]) >= 4.5
    assert _contrast(nord["text_disabled"], nord["control_disabled"]) >= 2.5
    # Jog pads draw a surface_raised circle on the surface page.
    assert _contrast(nord["surface_raised"], nord["surface"]) >= 1.08


def test_solarized_light_gcode_syntax_is_readable_on_the_list():
    # Syntax colors are drawn on the g-code row and on the selected row.
    solarized = load_palette("solarized_light")
    for category in GCODE_SYNTAX_CATEGORIES:
        color = solarized[f"gcode_{category}"]
        for background in ("surface_raised", "control", "tooltip_bg"):
            ratio = _contrast(color, solarized[background])
            assert ratio >= 4.5, (category, background, round(ratio, 2))
    for background in ("bg", "surface", "surface_raised"):
        ratio = _contrast(solarized["active_color"], solarized[background])
        assert ratio >= 4.5, (background, round(ratio, 2))


def test_solarized_light_text_is_readable():
    solarized = load_palette("solarized_light")
    for background in ("bg", "surface", "panel", "menu", "row", "control", "field_bg"):
        assert _contrast(solarized["text"], solarized[background]) >= 7, background
    for background in ("bg", "surface", "panel", "control"):
        assert _contrast(solarized["text_muted"], solarized[background]) >= 4.5, background
        assert _contrast(solarized["text_secondary"], solarized[background]) >= 4.5, background
    for token in (
        "accent_text",
        "info_text",
        "warning_text",
        "danger_text",
        "axis_x",
        "axis_y",
        "axis_z",
        "axis_a",
    ):
        assert _contrast(solarized[token], solarized["bg"]) >= 4.5, token
    for fill in (
        "accent",
        "primary",
        "primary_down",
        "danger",
        "danger_down",
        "help",
        "help_down",
        "success",
        "warning",
    ):
        assert _contrast(solarized["text_on_fill"], solarized[fill]) >= 4.5, fill
    assert _contrast(solarized["success_text"], solarized["success_fill"]) >= 4.5
    assert _contrast(solarized["text_disabled"], solarized["control_disabled"]) >= 2.5
    # Jog pads draw a surface_raised circle on the surface page.
    assert _contrast(solarized["surface_raised"], solarized["surface"]) >= 1.08


def test_dark_theme_text_on_fills_is_readable():
    dark = load_palette("dark")
    for fill in ("accent", "primary", "danger", "help"):
        assert _contrast(dark["text_on_fill"], dark[fill]) >= 4.5, fill


def test_load_palette_returns_independent_copies():
    first = load_palette("dark")
    first["bg"][0] = 0.99
    assert load_palette("dark")["bg"][0] != 0.99


def test_unknown_or_invalid_names_are_rejected():
    for name in ("nope", "../dark", "Dark", ""):
        with pytest.raises(ThemeError):
            load_palette(name)


@pytest.fixture
def scratch_themes(tmp_path, monkeypatch):
    """Point the registry at a temp directory seeded with a copy of the base theme."""
    monkeypatch.setattr(themes, "THEMES_DIR", tmp_path)
    themes._load_cached.cache_clear()
    (tmp_path / "dark.json").write_text((_ROOT / "carveracontroller/ui/themes/dark.json").read_text())
    yield tmp_path
    themes._load_cached.cache_clear()


def _write(directory, name, data):
    (directory / f"{name}.json").write_text(json.dumps(data))


def test_extends_merges_over_parent(scratch_themes):
    _write(scratch_themes, "child", {"extends": "dark", "bg": "#112233"})
    palette = load_palette("child")
    assert palette["bg"] == pytest.approx(parse_hex_color("#112233"))
    assert palette["surface"] == pytest.approx(load_palette("dark")["surface"])


def test_theme_without_extends_must_be_complete(scratch_themes):
    _write(scratch_themes, "partial", {"bg": "#112233"})
    with pytest.raises(ThemeError, match="missing tokens"):
        load_palette("partial")


def test_unknown_tokens_and_kind_changes_are_rejected(scratch_themes):
    _write(scratch_themes, "extra", {"extends": "dark", "not_a_token": "#112233"})
    with pytest.raises(ThemeError, match="unknown tokens"):
        load_palette("extra")
    _write(scratch_themes, "kind", {"extends": "dark", "bg": 4})
    with pytest.raises(ThemeError, match="changes kind"):
        load_palette("kind")


def test_inheritance_loops_and_bad_json_are_rejected(scratch_themes):
    _write(scratch_themes, "a", {"extends": "b"})
    _write(scratch_themes, "b", {"extends": "a"})
    with pytest.raises(ThemeError, match="loop"):
        load_palette("a")
    (scratch_themes / "broken.json").write_text("{not json")
    with pytest.raises(ThemeError, match="not valid JSON"):
        load_palette("broken")


def test_list_themes_skips_invalid_files(scratch_themes):
    _write(scratch_themes, "good", {"title": "Good One", "extends": "dark", "bg": "#112233"})
    _write(scratch_themes, "bad", {"extends": "dark", "bg": "nope"})
    assert dict(list_themes()) == {"dark": "Dark", "good": "Good One"}
