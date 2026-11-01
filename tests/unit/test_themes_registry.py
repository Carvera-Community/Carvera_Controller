"""Theme palette files: loading and inheritance."""

import json
from pathlib import Path

import pytest

from carveracontroller.ui import themes
from carveracontroller.ui.themes import (
    BASE_THEME,
    CUSTOM_THEME,
    CUSTOM_TITLE,
    ThemeError,
    custom_theme_document,
    format_hex_color,
    list_themes,
    load_palette,
    parse_hex_color,
    theme_names,
    theme_title,
)

_ROOT = Path(__file__).resolve().parents[2]


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
    source = _ROOT / "carveracontroller/ui/themes/bundled" / f"{BASE_THEME}.json"
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


def test_unknown_tokens_are_dropped_and_the_theme_still_loads(scratch_themes, caplog):
    _write(
        scratch_themes,
        "extra",
        {"extends": BASE_THEME, "bg": "#112233", "layout": {"bar_pad": 9, "radius_pad": 3}},
    )
    with caplog.at_level("WARNING"):
        palette = load_palette("extra")
        listed = dict(list_themes())
    assert "extra" in listed
    assert palette["bg"] == pytest.approx(parse_hex_color("#112233"))
    assert "bar_pad" not in palette
    assert "radius_pad" not in palette
    base = load_palette(BASE_THEME)
    assert palette["bar_padding"] == base["bar_padding"]
    assert palette["pad_radius"] == base["pad_radius"]
    assert "bar_pad" in caplog.text
    assert "radius_pad" in caplog.text


def test_obsolete_object_token_is_ignored_and_the_theme_still_loads(scratch_themes, caplog):
    _write(
        scratch_themes,
        "old",
        {"extends": BASE_THEME, "bg": "#abcdef", "sim": {"bar": "#112233", "marker": "#445566"}},
    )
    with caplog.at_level("WARNING", logger="carveracontroller.ui.themes"):
        palette = load_palette("old")
        listed = dict(list_themes())
    assert "old" in listed
    assert "sim" not in palette
    assert palette["bg"] == pytest.approx(parse_hex_color("#abcdef"))
    assert palette["surface"] == pytest.approx(load_palette(BASE_THEME)["surface"])
    assert "Ignoring invalid tokens in theme old: sim" in caplog.text
    assert "Ignoring theme" not in caplog.text


def test_kind_changes_are_rejected(scratch_themes):
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


def test_theme_without_fonts_inherits_the_base_roles(scratch_themes):
    _write(scratch_themes, "child", {"extends": BASE_THEME, "bg": "#112233"})
    assert themes.load_fonts("child") == themes.load_fonts(BASE_THEME)


def test_omitted_font_roles_follow_the_default(scratch_themes):
    from carveracontroller.ui.fonts import resolve_theme_fonts

    _write(scratch_themes, "child", {"extends": BASE_THEME, "fonts": {"default": "Child Sans"}})
    assert themes.load_fonts("child") == {"default": "Child Sans"}
    resolved = resolve_theme_fonts(themes.load_fonts("child"))
    for role in ("top_bar", "jog_pad", "code_list"):
        assert resolved[role] == resolved["default"]


def test_fonts_merge_through_extends_and_null_drops_a_role(scratch_themes):
    _write(
        scratch_themes, "parent", {"extends": BASE_THEME, "fonts": {"default": "Parent Sans", "top_bar": "Bar Sans"}}
    )
    _write(scratch_themes, "child", {"extends": "parent", "fonts": {"default": "Child Sans"}})
    _write(scratch_themes, "dropped", {"extends": "parent", "fonts": {"top_bar": None}})
    assert themes.load_fonts("parent") == {"default": "Parent Sans", "top_bar": "Bar Sans"}
    assert themes.load_fonts("child") == {"default": "Child Sans", "top_bar": "Bar Sans"}
    assert themes.load_fonts("dropped") == {"default": "Parent Sans"}


def test_fonts_are_not_color_tokens(scratch_themes):
    _write(scratch_themes, "styled", {"extends": BASE_THEME, "fonts": {"default": "Some Sans"}})
    assert set(load_palette("styled")) == set(load_palette(BASE_THEME))


def test_font_paths_resolve_against_the_theme_file_directory(scratch_themes):
    (scratch_themes / "fonts").mkdir()
    nested = scratch_themes / "fonts" / "Nested.ttf"
    nested.write_bytes(b"")
    absolute = scratch_themes / "Absolute.otf"
    absolute.write_bytes(b"")
    _write(
        scratch_themes,
        "paths",
        {
            "extends": BASE_THEME,
            "fonts": {"default": "fonts/Nested.ttf", "top_bar": str(absolute)},
        },
    )
    fonts = themes.load_fonts("paths")
    assert fonts["default"] == str(nested.resolve())
    assert fonts["top_bar"] == str(absolute)


def test_missing_font_file_and_family_names_pass_through(scratch_themes):
    _write(
        scratch_themes, "raw", {"extends": BASE_THEME, "fonts": {"default": "fonts/Gone.ttf", "top_bar": "DejaVu Sans"}}
    )
    assert themes.load_fonts("raw") == {"default": "fonts/Gone.ttf", "top_bar": "DejaVu Sans"}


def test_unknown_font_roles_and_bad_values_are_rejected(scratch_themes):
    _write(scratch_themes, "role", {"extends": BASE_THEME, "fonts": {"sidebar": "X"}})
    with pytest.raises(ThemeError, match="unknown font roles"):
        load_palette("role")
    for index, bad in enumerate((5, "", ["X"], True)):
        _write(scratch_themes, f"value{index}", {"extends": BASE_THEME, "fonts": {"default": bad}})
        with pytest.raises(ThemeError, match="font role"):
            load_palette(f"value{index}")
    _write(scratch_themes, "shape", {"extends": BASE_THEME, "fonts": "X"})
    with pytest.raises(ThemeError, match="'fonts' must be an object"):
        load_palette("shape")
    _write(
        scratch_themes,
        "face",
        {"extends": BASE_THEME, "fonts": {"default": {"family": "DejaVu Sans", "weight": "Bold", "style": "Oblique"}}},
    )
    assert themes.load_fonts("face") == {"default": {"family": "DejaVu Sans", "weight": "Bold", "style": "Italic"}}
    _write(
        scratch_themes,
        "plain",
        {"extends": BASE_THEME, "fonts": {"default": {"family": "DejaVu Sans", "weight": "Regular", "style": "Roman"}}},
    )
    assert themes.load_fonts("plain") == {"default": "DejaVu Sans"}
    _write(
        scratch_themes,
        "weight",
        {"extends": BASE_THEME, "fonts": {"default": {"family": "DejaVu Sans", "weight": "Nope"}}},
    )
    with pytest.raises(ThemeError, match="font role"):
        load_palette("weight")


def test_behaviors_inherit_and_unknown_or_non_bool_values_are_rejected(scratch_themes):
    _write(scratch_themes, "off", {"extends": BASE_THEME, "behaviors": {"jog_pad_axis_colors": False}})
    _write(scratch_themes, "child", {"extends": "off"})
    _write(scratch_themes, "colored", {"extends": "off", "behaviors": {"jog_pad_axis_colors": True}})
    _write(
        scratch_themes,
        "face",
        {"extends": BASE_THEME, "behaviors": {"jog_pad_sign_colors": True, "jog_pad_axis_background": True}},
    )
    assert "jog_pad_axis_colors" not in load_palette("off")
    assert themes.load_behaviors("child")["jog_pad_axis_colors"] is False
    assert themes.load_behaviors("colored")["jog_pad_axis_colors"] is True
    assert "jog_pad_axis_colors" not in load_palette("colored")
    face = themes.load_behaviors("face")
    assert face["jog_pad_sign_colors"] is True
    assert face["jog_pad_axis_background"] is True
    assert face["jog_pad_axis_colors"] is False

    _write(scratch_themes, "unknown", {"extends": BASE_THEME, "behaviors": {"nope": True}})
    with pytest.raises(ThemeError, match="unknown behaviors"):
        load_palette("unknown")
    _write(scratch_themes, "text", {"extends": BASE_THEME, "behaviors": {"jog_pad_axis_colors": "yes"}})
    with pytest.raises(ThemeError, match="must be true or false"):
        load_palette("text")
    _write(scratch_themes, "shape", {"extends": BASE_THEME, "behaviors": True})
    with pytest.raises(ThemeError, match="'behaviors' must be an object"):
        load_palette("shape")


def test_jog_axis_markup_colors_only_the_letter():
    import re
    from types import SimpleNamespace

    theme = SimpleNamespace(
        jog_pad_axis_colors=False,
        jog_pad_sign_colors=False,
        jog_pad_axis_background=False,
        axis_x=[1, 0, 0, 1],
        axis_y=[0, 1, 0, 1],
        axis_z=[0, 0, 1, 1],
        axis_a=[1, 1, 0, 1],
    )
    assert themes.jog_axis_markup("X+", theme) == ("X+", False)
    theme.jog_pad_axis_colors = True
    for caption, color in (
        ("X+", theme.axis_x),
        ("X-", theme.axis_x),
        ("Y+", theme.axis_y),
        ("Z-", theme.axis_z),
        ("A+", theme.axis_a),
    ):
        text, markup = themes.jog_axis_markup(caption, theme)
        match = re.fullmatch(r"\[color=(#[0-9a-fA-F]+)\](.)\[/color\](.*)", text)
        assert markup is True
        assert match is not None
        hex_color, letter, rest = match.groups()
        assert letter == caption[0]
        assert rest == caption[1:]
        assert parse_hex_color(hex_color) == pytest.approx(color)
    assert themes.jog_axis_markup("", theme) == ("", False)
    assert themes.jog_axis_markup("Home", theme) == ("Home", False)


def test_jog_axis_markup_can_color_the_sign_and_yields_to_the_background():
    from types import SimpleNamespace

    theme = SimpleNamespace(
        jog_pad_axis_colors=False,
        jog_pad_sign_colors=True,
        jog_pad_axis_background=False,
        axis_x=[1, 0, 0, 1],
        axis_y=[0, 1, 0, 1],
    )
    painted = format_hex_color(theme.axis_x)
    assert themes.jog_axis_markup("X+", theme) == (f"X[color={painted}]+[/color]", True)
    assert themes.jog_axis_markup("X-", theme) == (f"X[color={painted}]-[/color]", True)
    assert themes.jog_axis_markup("X", theme) == ("X", False)
    theme.jog_pad_axis_colors = True
    assert themes.jog_axis_markup("X+", theme) == (f"[color={painted}]X+[/color]", True)
    assert themes.jog_axis_markup("Y-", theme) == (f"[color={format_hex_color(theme.axis_y)}]Y-[/color]", True)
    theme.jog_pad_axis_background = True
    assert themes.jog_axis_markup("X+", theme) == ("X+", False)


def test_behavior_follows_the_palette_and_color_edits_leave_it(scratch_themes):
    from carveracontroller.ui.theme import Theme

    _write(scratch_themes, "colored", {"extends": BASE_THEME, "behaviors": {"jog_pad_axis_colors": True}})
    _write(scratch_themes, "plain", {"extends": BASE_THEME, "behaviors": {"jog_pad_axis_colors": False}})
    theme = Theme()
    theme.apply_palette("colored")
    assert theme.jog_pad_axis_colors is True
    assert theme.jog_pad_sign_colors is False
    assert theme.jog_pad_axis_background is False
    assert theme.group_main_menu is False
    theme.apply({"radius_m": 9})
    assert theme.jog_pad_axis_colors is True
    theme.apply_palette("plain")
    assert theme.jog_pad_axis_colors is False


def test_list_themes_skips_themes_with_bad_fonts(scratch_themes):
    _write(scratch_themes, "bad_fonts", {"extends": BASE_THEME, "fonts": {"nope": "X"}})
    assert "bad_fonts" not in dict(list_themes())


def test_nested_group_overrides_one_token_and_inherits_the_rest(scratch_themes):
    _write(scratch_themes, "child", {"extends": BASE_THEME, "gcode": {"comment": "#112233"}, "layout": {"spacing": 9}})
    palette = load_palette("child")
    base = load_palette(BASE_THEME)
    assert palette["gcode_comment"] == pytest.approx(parse_hex_color("#112233"))
    assert palette["gcode_g_command"] == pytest.approx(base["gcode_g_command"])
    assert palette["spacing"] == 9
    assert palette["radius_s"] == base["radius_s"]


def test_flat_token_that_belongs_in_a_group_is_rejected(scratch_themes):
    _write(scratch_themes, "flat_color", {"extends": BASE_THEME, "gcode_comment": "#112233"})
    with pytest.raises(ThemeError, match="belongs in 'gcode'"):
        load_palette("flat_color")
    _write(scratch_themes, "flat_size", {"extends": BASE_THEME, "spacing": 9})
    with pytest.raises(ThemeError, match="belongs in 'layout'"):
        load_palette("flat_size")


def test_unknown_group_key_is_dropped(scratch_themes, caplog):
    _write(scratch_themes, "inner", {"extends": BASE_THEME, "gcode": {"nope": "#112233"}})
    with caplog.at_level("WARNING"):
        palette = load_palette("inner")
    assert "gcode_nope" not in palette
    assert "gcode_nope" in caplog.text
    assert palette["gcode_comment"] == pytest.approx(load_palette(BASE_THEME)["gcode_comment"])


def test_group_must_be_an_object(scratch_themes):
    _write(scratch_themes, "shape", {"extends": BASE_THEME, "gcode": "#112233"})
    with pytest.raises(ThemeError, match="'gcode' must be an object"):
        load_palette("shape")


@pytest.fixture
def user_themes(tmp_path):
    """Point Custom at a temp directory and restore the built-in-only registry afterwards."""
    themes.set_user_themes_dir(tmp_path)
    yield tmp_path
    themes.set_user_themes_dir(None)


def test_missing_custom_file_leaves_builtin_names(tmp_path):
    before = theme_names()
    themes.set_user_themes_dir(tmp_path)
    try:
        assert theme_names() == before
        assert CUSTOM_THEME not in theme_names()
    finally:
        themes.set_user_themes_dir(None)


def test_custom_theme_is_listed_and_loads(user_themes):
    tokens = load_palette(BASE_THEME)
    tokens["bg"] = parse_hex_color("#112233")
    document = custom_theme_document(tokens, {"default": "ARIALUNI", "top_bar": ""})
    assert document["name"] == CUSTOM_THEME
    assert document["title"] == CUSTOM_TITLE
    assert "extends" not in document
    assert "gcode_comment" not in document
    assert document["gcode"]["comment"]
    assert document["fonts"]["top_bar"] is None
    assert document["fonts"]["jog_pad"] is None
    assert document["fonts"]["code_list"] is None
    assert document["behaviors"]["jog_pad_axis_colors"] is False
    assert document["behaviors"]["jog_pad_sign_colors"] is False
    assert document["behaviors"]["jog_pad_axis_background"] is False
    (user_themes / "custom.json").write_text(json.dumps(document))
    themes.clear_theme_cache()

    listed = list_themes()
    assert listed[0][0] == CUSTOM_THEME
    assert dict(listed)[CUSTOM_THEME] == CUSTOM_TITLE
    loaded = load_palette(CUSTOM_THEME)
    assert loaded["bg"] == pytest.approx(parse_hex_color("#112233"))
    assert loaded["surface"] == pytest.approx(load_palette(BASE_THEME)["surface"])


def test_custom_theme_uses_the_base_value_for_tokens_it_does_not_have(user_themes, caplog):
    document = json.loads((_ROOT / "carveracontroller/ui/themes/bundled" / f"{BASE_THEME}.json").read_text())
    document["name"] = CUSTOM_THEME
    document["title"] = CUSTOM_TITLE
    document.pop("extends", None)
    document["bg"] = "#112233"
    for key in ("jog_pad", "jog_page", "overlay", "menu"):
        del document[key]
    (user_themes / "custom.json").write_text(json.dumps(document))
    themes.clear_theme_cache()

    with caplog.at_level("WARNING", logger="carveracontroller.ui.themes"):
        loaded = load_palette(CUSTOM_THEME)
        assert CUSTOM_THEME in dict(list_themes())
    assert "Ignoring theme" not in caplog.text
    base = load_palette(BASE_THEME)
    for key in ("jog_pad", "jog_page", "overlay", "menu"):
        assert loaded[key] == pytest.approx(base[key]), key
    assert loaded["bg"] == pytest.approx(parse_hex_color("#112233"))
    loaded["jog_pad"][0] = 0.25
    assert load_palette(BASE_THEME)["jog_pad"][0] != 0.25


def test_custom_theme_inherits_a_missing_token_from_the_theme_it_extends(user_themes, scratch_themes):
    _write(scratch_themes, "parent", {"extends": BASE_THEME, "jog_page": "#112233"})
    document = custom_theme_document(load_palette("parent"), extends="parent")
    del document["jog_page"]
    (user_themes / "custom.json").write_text(json.dumps(document))
    themes.clear_theme_cache()

    loaded = load_palette(CUSTOM_THEME)
    assert loaded["jog_page"] == pytest.approx(parse_hex_color("#112233"))
    assert loaded["surface"] == pytest.approx(load_palette("parent")["surface"])


def test_flat_key_inside_custom_is_rejected(user_themes):
    (user_themes / "custom.json").write_text(
        json.dumps({"name": CUSTOM_THEME, "title": CUSTOM_TITLE, "extends": BASE_THEME, "gcode_comment": "#112233"})
    )
    themes.clear_theme_cache()
    with pytest.raises(ThemeError, match="belongs in 'gcode'"):
        load_palette(CUSTOM_THEME)
    assert CUSTOM_THEME not in dict(list_themes())
