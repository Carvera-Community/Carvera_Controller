"""Theme palette files in ``ui/themes``: loading, inheritance and contrast."""

import json
from pathlib import Path

import pytest

from carveracontroller.ui import themes
from carveracontroller.ui.themes import (
    BASE_THEME,
    ThemeError,
    format_hex_color,
    list_themes,
    load_palette,
    parse_hex_color,
    theme_title,
)

_ROOT = Path(__file__).resolve().parents[2]

# Normal text on the surface it is drawn on. 4.5 is the WCAG AA contrast ratio.
_TEXT_ON_SURFACE = (
    ("text", ("bg", "surface", "surface_raised", "panel", "menu", "row", "control", "field_bg")),
    ("text_muted", ("bg", "surface", "panel")),
    ("text_secondary", ("bg", "surface", "panel")),
    ("text_on_fill", ("accent", "primary", "primary_down", "danger", "danger_down", "help", "help_down")),
    ("info_text", ("surface", "surface_raised", "field_bg")),
)


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
    assert names[0] == BASE_THEME
    assert theme_title("") == ""
    assert theme_title("missing") == "missing"


def test_every_built_in_theme_has_exactly_the_base_tokens():
    base = load_palette(BASE_THEME)
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


def test_text_is_readable_on_its_surfaces():
    for name, _title in list_themes():
        palette = load_palette(name)
        for foreground, backgrounds in _TEXT_ON_SURFACE:
            for background in backgrounds:
                ratio = _contrast(palette[foreground], palette[background])
                assert ratio >= 4.5, (name, foreground, background, round(ratio, 2))


def test_load_palette_returns_independent_copies():
    first = load_palette(BASE_THEME)
    first["bg"][0] = 0.99
    assert load_palette(BASE_THEME)["bg"][0] != 0.99


def test_unknown_or_invalid_names_are_rejected():
    for name in ("nope", "../palette", "NotATheme", ""):
        with pytest.raises(ThemeError):
            load_palette(name)


@pytest.fixture
def scratch_themes(tmp_path, monkeypatch):
    """Point the registry at a temp directory seeded with a copy of the base theme."""
    monkeypatch.setattr(themes, "THEMES_DIR", tmp_path)
    themes._load_cached.cache_clear()
    source = _ROOT / "carveracontroller/ui/themes" / f"{BASE_THEME}.json"
    (tmp_path / f"{BASE_THEME}.json").write_text(source.read_text())
    yield tmp_path
    themes._load_cached.cache_clear()


def _write(directory, name, data):
    (directory / f"{name}.json").write_text(json.dumps(data))


def test_extends_merges_over_parent(scratch_themes):
    _write(scratch_themes, "child", {"extends": BASE_THEME, "bg": "#112233"})
    palette = load_palette("child")
    assert palette["bg"] == pytest.approx(parse_hex_color("#112233"))
    assert palette["surface"] == pytest.approx(load_palette(BASE_THEME)["surface"])


def test_theme_without_extends_must_be_complete(scratch_themes):
    _write(scratch_themes, "partial", {"bg": "#112233"})
    with pytest.raises(ThemeError, match="missing tokens"):
        load_palette("partial")


def test_unknown_tokens_and_kind_changes_are_rejected(scratch_themes):
    _write(scratch_themes, "extra", {"extends": BASE_THEME, "not_a_token": "#112233"})
    with pytest.raises(ThemeError, match="unknown tokens"):
        load_palette("extra")
    _write(scratch_themes, "kind", {"extends": BASE_THEME, "bg": 4})
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
    _write(scratch_themes, "good", {"title": "Good One", "extends": BASE_THEME, "bg": "#112233"})
    _write(scratch_themes, "bad", {"extends": BASE_THEME, "bg": "nope"})
    listed = dict(list_themes())
    assert set(listed) == {BASE_THEME, "good"}
    assert listed["good"] == "Good One"
