"""Theme settings page: a draft preview, applied with the settings popup."""

import json
from pathlib import Path

import pytest
from kivy.app import App
from kivy.metrics import dp

from carveracontroller.translation import tr
from carveracontroller.ui import themes
from carveracontroller.ui.fonts import fonts
from carveracontroller.ui.themes import (
    BASE_THEME,
    CUSTOM_THEME,
    format_hex_color,
    load_palette,
    parse_hex_color,
    theme_title,
)
from carveracontroller.ui.themes.editor import (
    MIN_PANE_HEIGHT,
    PREVIEW_PANE_WIDTH,
    SettingThemeEditor,
    fields_pane_width,
    preview_shown_for_width,
)
from carveracontroller.ui.themes.preview import _GCODE_PREVIEW_LINES, JOG_PREVIEW_SIDE

_ROOT = Path(__file__).resolve().parents[2]
_DARK_FILE = _ROOT / "carveracontroller" / "ui" / "themes" / "bundled" / f"{BASE_THEME}.json"


class _Panel:
    def __init__(self, value=BASE_THEME):
        self.value = value

    def get_value(self, _section, _key):
        return self.value

    def set_value(self, _section, _key, value):
        self.value = value


@pytest.fixture
def user_themes(tmp_path):
    from kivy.config import Config

    app = App.get_running_app()
    previous_name = app.theme.name if app is not None and getattr(app, "theme", None) is not None else None
    had_theme = Config.has_option("carvera", "theme")
    previous_config = Config.get("carvera", "theme") if had_theme else None
    themes.set_user_themes_dir(tmp_path)
    yield tmp_path
    themes.set_user_themes_dir(None)
    if previous_name and app is not None and hasattr(app, "set_theme"):
        app.set_theme(previous_name)
    if had_theme:
        Config.set("carvera", "theme", previous_config)
    elif Config.has_option("carvera", "theme"):
        Config.remove_option("carvera", "theme")
    Config.write()


@pytest.fixture(autouse=True)
def listed_font_families(monkeypatch):
    """The font menus list a fixed pair, not whatever this machine has installed."""
    monkeypatch.setattr(fonts, "_load_font_index", lambda: {})
    fonts._index_cache = None
    monkeypatch.setattr(
        "carveracontroller.ui.themes.editor.available_families",
        lambda: ["ARIALUNI", "DejaVu Sans"],
    )
    yield
    fonts._index_cache = None


def _editor():
    return SettingThemeEditor(panel=_Panel(), section="carvera", key="theme", title="Theme", desc="")


def _reset_editor(editor, body_width, font_values):
    """Drop edits on the shared page and show the theme it was opened on."""
    from kivy.uix.settings import SettingsPanel

    for role, row in editor._font_fields.items():
        row.field.values = list(font_values[role])

    settings_panel = editor.parent if isinstance(editor.parent, SettingsPanel) else None
    if settings_panel is not None and editor._panel_hooks:
        settings_panel.unbind(height=editor._sync_viewport_height, parent=editor._on_panel_parent)
        editor._panel_hooks = False
    scroll = editor._viewport_scroll
    if scroll is not None:
        scroll.unbind(height=editor._sync_viewport_height)
        editor._viewport_scroll = None
    if editor.parent is not None:
        editor.parent.remove_widget(editor)

    editor._force_reload = False
    editor._committing = False
    editor._opened_name = BASE_THEME
    editor._assign_value(BASE_THEME)
    editor._load_form(BASE_THEME)
    editor._show_section("colors")
    editor._sync_fields_column_height()

    # Restoring a narrow width would hide the preview. Put the widgets back by hand.
    editor._body_row.unbind(width=editor._on_body_width)
    editor._body_row.width = body_width
    editor._body_row.bind(width=editor._on_body_width)
    editor._preview_visible = True
    editor._fields_pane.size_hint_x = 1
    editor._fields_pane.size_hint_min_x = fields_pane_width()
    editor._preview_column.disabled = False
    editor._preview_column.opacity = 1
    editor._preview_column.size_hint_x = None
    editor._preview_column.width = PREVIEW_PANE_WIDTH
    if editor._preview_column.parent is None:
        editor._body_row.add_widget(editor._preview_column)
    editor._pane_height = MIN_PANE_HEIGHT
    editor._apply_pane_heights()
    editor._editor_height = editor._measure_editor_height()
    editor._restore_editor_height(0)


@pytest.fixture(scope="module")
def _shared_editor():
    """Building the page takes about a second, so the module keeps one instance."""
    slot = {}
    yield slot
    editor = slot.get("editor")
    if editor is None:
        return
    from kivy.core.window import Window

    Window.unbind(size=editor._sync_viewport_height)
    if editor.parent is not None:
        editor.parent.remove_widget(editor)


@pytest.fixture
def editor(listed_font_families, _shared_editor, request):
    if "user_themes" in request.fixturenames:
        request.getfixturevalue("user_themes")
    if "editor" not in _shared_editor:
        built = _editor()
        _shared_editor["editor"] = built
        _shared_editor["body_width"] = built._body_row.width
        _shared_editor["font_values"] = {role: list(row.field.values) for role, row in built._font_fields.items()}
    current = _shared_editor["editor"]
    _reset_editor(current, _shared_editor["body_width"], _shared_editor["font_values"])
    return current


def test_color_edit_updates_the_draft_and_preview_only(editor):
    app = App.get_running_app()
    app_primary = list(app.theme.primary) if app is not None and getattr(app, "theme", None) is not None else None
    builtin = _DARK_FILE.read_bytes()
    bg = list(editor.draft.bg)
    body = list(editor.preview.body.color)

    assert editor.set_token("primary", "#112233") is True
    assert editor.draft.primary == pytest.approx(parse_hex_color("#112233"))
    assert list(editor.draft.bg) == pytest.approx(bg)
    assert list(editor.preview.run_button.fill_color.rgba) == pytest.approx(editor.draft.primary)
    assert list(editor.preview.bg_color.rgba) == pytest.approx(bg)
    assert list(editor._preview_backdrop.rgba) == pytest.approx(bg)
    assert list(editor.preview.body.color) == pytest.approx(body)

    assert editor.set_token("primary", "not-a-color") is False
    assert editor.draft.primary == pytest.approx(parse_hex_color("#112233"))
    if app_primary is not None:
        assert list(app.theme.primary) == pytest.approx(app_primary)
    assert _DARK_FILE.read_bytes() == builtin


def test_save_writes_grouped_custom_theme_and_leaves_the_builtin(user_themes, editor):
    builtin = _DARK_FILE.read_bytes()
    assert editor._draft_is_dirty() is False
    assert editor.set_token("primary", "#112233") is True
    assert editor._draft_is_dirty() is True
    assert editor.value == CUSTOM_THEME
    expected = editor.draft.to_dict()

    editor.commit_for_apply()
    assert editor._draft_is_dirty() is False

    saved = json.loads((user_themes / "custom.json").read_text())
    assert saved["name"] == CUSTOM_THEME
    assert saved["title"] == "Custom"
    assert saved["extends"] == BASE_THEME
    assert "gcode" in saved
    assert "gcode_comment" not in saved
    assert saved["fonts"]["top_bar"] is None
    assert saved["fonts"]["jog_pad"] is None
    assert saved["fonts"]["code_list"] is None
    assert saved["behaviors"]["jog_pad_axis_colors"] is False
    assert saved["behaviors"]["jog_pad_sign_colors"] is False
    assert saved["behaviors"]["jog_pad_axis_background"] is False
    assert saved["primary"] == "#112233"

    loaded = load_palette(CUSTOM_THEME)
    for key, value in expected.items():
        if key == "name":
            continue
        if isinstance(value, list):
            assert loaded[key] == pytest.approx(value), key
        else:
            assert loaded[key] == value, key
    assert editor._selected == CUSTOM_THEME
    assert _DARK_FILE.read_bytes() == builtin


def test_save_records_the_edited_theme_and_keeps_it_when_saving_custom(user_themes, editor):
    title = next(text for text, name in editor._title_to_name.items() if name == "light")
    editor._spinner.text = title
    assert editor.set_token("primary", "#112233") is True

    editor.commit_for_apply()

    saved = json.loads((user_themes / "custom.json").read_text())
    assert saved["extends"] == "light"
    assert editor._selected == CUSTOM_THEME
    assert editor.set_token("primary", "#445566") is True

    editor.commit_for_apply()

    saved = json.loads((user_themes / "custom.json").read_text())
    assert saved["extends"] == "light"
    assert saved["primary"] == "#445566"


def test_choosing_a_theme_drops_unsaved_edits_without_applying(user_themes, editor):
    from kivy.config import Config

    app = App.get_running_app()
    live_name = app.theme.name if app is not None and getattr(app, "theme", None) is not None else None
    had_theme = Config.has_option("carvera", "theme")
    config_before = Config.get("carvera", "theme") if had_theme else None
    assert editor.set_token("primary", "#112233") is True
    title = next(text for text, name in editor._title_to_name.items() if name == "light")

    editor._spinner.text = title

    assert editor._selected == "light"
    assert editor.value == "light"
    assert editor._draft_is_dirty() is False
    assert editor.draft.primary == pytest.approx(load_palette("light")["primary"])
    assert format_hex_color(editor.draft.primary) != "#112233"
    assert theme_title("light") == title
    if had_theme:
        assert Config.get("carvera", "theme") == config_before
    else:
        assert not Config.has_option("carvera", "theme")
    if live_name is not None:
        assert app.theme.name == live_name

    editor.commit_for_apply()

    assert editor.value == "light"
    assert editor._force_reload is False
    assert not (user_themes / "custom.json").exists()
    if had_theme:
        assert Config.get("carvera", "theme") == config_before
    if live_name is not None:
        assert app.theme.name == live_name


class _ApplyButton:
    def __init__(self):
        self.disabled = True


class _PendingRoot:
    def __init__(self):
        self.config_loading = False
        self.controller_setting_change_list = {}
        self.setting_change_list = {}
        self.config_popup = type("Popup", (), {"btn_apply": _ApplyButton()})()


def test_theme_value_is_not_written_before_the_window_exists(editor, monkeypatch):
    original = editor.panel.set_value
    calls = []
    editor.panel.set_value = lambda *args: calls.append(args)
    # The full suite may already have built the interface. This case is the
    # startup path, where Kivy has not assigned that window yet.
    monkeypatch.setattr(editor, "_settings_root", lambda: None)
    try:
        editor._assign_value("light")
        assert editor.value == "light"
        assert calls == []
    finally:
        editor.panel.set_value = original


def test_theme_value_is_written_once_the_window_exists(editor, monkeypatch):
    original = editor.panel.set_value
    calls = []
    editor.panel.set_value = lambda *args: calls.append(args)
    monkeypatch.setattr(editor, "_settings_root", lambda: _PendingRoot())
    try:
        editor._assign_value("light")
        assert editor.value == "light"
        assert calls == [("carvera", "theme", "light")]
    finally:
        editor.panel.set_value = original


def test_config_change_before_the_window_exists_is_ignored():
    from kivy.app import App

    from carveracontroller.main import MakeraConfigPanel

    app = App.get_running_app()
    created = app is None
    if created:
        app = App()
    previous = app.root
    app.root = None
    try:
        MakeraConfigPanel.on_config_change(None, None, "carvera", "theme", "dark")
    finally:
        app.root = previous
        if created:
            App._running_app = None


def test_dirty_edit_of_the_open_theme_stays_pending(user_themes, monkeypatch, editor):
    assert editor.set_token("primary", "#112233") is True
    editor.commit_for_apply()
    assert editor.value == CUSTOM_THEME
    assert editor._opened_name == CUSTOM_THEME

    root = _PendingRoot()
    monkeypatch.setattr(editor, "_settings_root", lambda: root)
    assert editor.set_token("primary", "#445566") is True

    assert editor.value == CUSTOM_THEME
    assert root.controller_setting_change_list["theme"] == CUSTOM_THEME
    assert root.config_popup.btn_apply.disabled is False

    editor.revert_token("primary")

    assert "theme" not in root.controller_setting_change_list
    assert root.config_popup.btn_apply.disabled is True


def test_revert_pending_restores_the_opened_theme_without_writing(user_themes, editor):
    opened = editor._opened_name
    primary = list(editor.draft.primary)
    assert editor.set_token("primary", "#112233") is True
    title = next(text for text, name in editor._title_to_name.items() if name == "light")
    editor._spinner.text = title
    assert editor.set_token("surface", "#abcdef") is True

    editor.revert_pending()

    assert editor._selected == opened
    assert editor.value == opened
    assert editor.draft.primary == pytest.approx(primary)
    assert editor._draft_is_dirty() is False
    assert not (user_themes / "custom.json").exists()


def test_editor_bypasses_setting_item_selection_highlight(editor):
    from unittest.mock import patch

    from kivy.uix.floatlayout import FloatLayout

    touch = object()
    with patch.object(FloatLayout, "on_touch_down", return_value=True) as dispatch:
        assert editor.on_touch_down(touch) is True
    dispatch.assert_called_once_with(editor, touch)
    assert editor.selected_alpha == 0


def test_color_swatch_opens_the_picker(monkeypatch, editor):
    row = editor._rows["primary"]
    opened = {}

    def _capture(rgba, on_color):
        opened["rgba"] = list(rgba)
        opened["on_color"] = on_color

    monkeypatch.setattr("carveracontroller.ui.themes.editor._open_color_picker", _capture)
    row.swatch.dispatch("on_release")
    assert opened["on_color"] == row._picked
    assert opened["rgba"] == pytest.approx(list(editor.draft.primary))


def test_color_picker_updates_draft_like_set_token(editor):
    app = App.get_running_app()
    app_primary = list(app.theme.primary) if app is not None and getattr(app, "theme", None) is not None else None
    row = editor._rows["bg"]
    chosen = parse_hex_color("#445566")

    row._picked(chosen)

    assert row.field.text == format_hex_color(chosen)
    assert editor.draft.bg == pytest.approx(chosen)
    assert list(editor.preview.bg_color.rgba) == pytest.approx(chosen)
    assert list(editor._preview_backdrop.rgba) == pytest.approx(chosen)
    if app_primary is not None:
        assert list(app.theme.primary) == pytest.approx(app_primary)


def test_revert_one_color_keeps_other_draft_edits(editor):
    baseline_primary = list(editor.draft.primary)
    assert editor.set_token("primary", "#112233") is True
    assert editor.set_token("surface", "#aabbcc") is True

    editor._rows["primary"].revert.dispatch("on_release")

    assert editor.draft.primary == pytest.approx(baseline_primary)
    assert format_hex_color(editor.draft.surface).lower() == "#aabbcc"
    assert editor._draft_is_dirty() is True
    editor._rows["surface"].revert.dispatch("on_release")
    assert editor._draft_is_dirty() is False


def test_jog_pad_font_updates_the_preview(editor):
    from carveracontroller.ui.fonts import arialuni_path

    path = arialuni_path()
    editor.font_jog_pad_field.field.text = path
    editor._apply_font_fields()

    assert editor.draft.font_jog_pad == path
    assert editor.preview.jog_x.label.text == "X+"
    assert editor.preview.jog_y.label.text == "Y+"
    assert editor.preview.jog_x.size == pytest.approx((JOG_PREVIEW_SIDE, JOG_PREVIEW_SIDE))
    assert editor.preview.jog_row.height == pytest.approx(JOG_PREVIEW_SIDE)
    assert editor.preview.jog_x.label.font_name == path
    assert editor.preview.jog_y.label.font_name == path
    assert editor.preview.body.font_name == editor.draft.font_default


def test_jog_pad_axis_colors_color_only_the_letter_in_the_preview(user_themes, editor):
    row = editor._behavior_fields["jog_pad_axis_colors"]
    assert row.switch.active is False
    assert editor.preview.jog_x.label.text == "X+"
    assert editor.preview.jog_x.label.markup is False

    row.switch.active = True

    assert editor.draft.jog_pad_axis_colors is True
    assert editor._draft_is_dirty() is True
    assert editor.preview.jog_x.label.markup is True
    assert editor.preview.jog_x.label.text == f"[color={format_hex_color(editor.draft.axis_x)}]X[/color]+"
    assert editor.preview.jog_y.label.text == f"[color={format_hex_color(editor.draft.axis_y)}]Y[/color]+"
    assert editor.set_token("axis_x", "#112233") is True
    assert editor.preview.jog_x.label.text == "[color=#112233]X[/color]+"
    assert "#112233" not in editor.preview.jog_y.label.text

    row.revert.dispatch("on_release")

    assert row.switch.active is False
    assert editor.draft.jog_pad_axis_colors is False
    assert editor.preview.jog_x.label.text == "X+"
    assert editor.preview.jog_x.label.markup is False
    assert editor._draft_is_dirty() is True
    editor.revert_token("axis_x")
    assert editor._draft_is_dirty() is False


def test_jog_pad_sign_colors_color_the_sign_in_the_preview(user_themes, editor):
    row = editor._behavior_fields["jog_pad_sign_colors"]
    row.switch.active = True

    painted_x = format_hex_color(editor.draft.axis_x)
    painted_y = format_hex_color(editor.draft.axis_y)
    assert editor.draft.jog_pad_sign_colors is True
    assert editor.preview.jog_x.label.text == f"X[color={painted_x}]+[/color]"
    assert editor.preview.jog_y.label.text == f"Y[color={painted_y}]+[/color]"

    editor._behavior_fields["jog_pad_axis_colors"].switch.active = True

    assert editor.preview.jog_x.label.text == f"[color={painted_x}]X+[/color]"
    assert editor.preview.jog_y.label.text == f"[color={painted_y}]Y+[/color]"

    row.revert.dispatch("on_release")

    assert editor.draft.jog_pad_sign_colors is False
    assert editor.preview.jog_x.label.text == f"[color={painted_x}]X[/color]+"


def test_jog_pad_axis_background_colors_the_key_in_the_preview(user_themes, editor):
    editor._behavior_fields["jog_pad_axis_colors"].switch.active = True
    editor._behavior_fields["jog_pad_sign_colors"].switch.active = True
    row = editor._behavior_fields["jog_pad_axis_background"]
    row.switch.active = True

    assert editor.draft.jog_pad_axis_background is True
    assert editor.preview.jog_x.label.text == "X+"
    assert editor.preview.jog_x.label.markup is False
    assert editor.preview.jog_y.label.text == "Y+"
    assert list(editor.preview.jog_x.fill_color.rgba) == pytest.approx(list(editor.draft.axis_x))
    assert list(editor.preview.jog_y.fill_color.rgba) == pytest.approx(list(editor.draft.axis_y))
    assert list(editor.preview.jog_x.label.color) == pytest.approx(
        editor.draft.jog_axis_text("X+", "normal", False, True)
    )

    row.revert.dispatch("on_release")

    assert editor.draft.jog_pad_axis_background is False
    assert editor.preview.jog_x.label.markup is True
    assert editor.preview.jog_x.label.text == f"[color={format_hex_color(editor.draft.axis_x)}]X+[/color]"
    assert list(editor.preview.jog_x.fill_color.rgba) == pytest.approx(
        editor.draft.button_fill("normal", "normal", False, True)
    )


def test_saving_jog_pad_axis_colors_reloads_the_behavior(user_themes, editor):
    editor._behavior_fields["jog_pad_axis_colors"].switch.active = True

    editor.commit_for_apply()

    saved = json.loads((user_themes / "custom.json").read_text())
    assert saved["behaviors"]["jog_pad_axis_colors"] is True
    assert themes.load_behaviors(CUSTOM_THEME)["jog_pad_axis_colors"] is True
    assert editor.draft.jog_pad_axis_colors is True
    assert editor._behavior_fields["jog_pad_axis_colors"].switch.active is True
    assert editor._draft_is_dirty() is False


def test_code_list_font_updates_the_gcode_preview(editor):
    from carveracontroller.ui.fonts import arialuni_path

    path = arialuni_path()
    editor.font_code_list_field.field.text = path
    editor._apply_font_fields()

    row = editor.preview.gcode_sample.rows[0]
    assert editor.draft.font_code_list == path
    assert row.number.font_name == path
    assert row.code.font_name == path
    assert editor.preview.body.font_name == editor.draft.font_default


def test_font_weight_lists_installed_faces_and_same_as_default_mirrors_it(monkeypatch, editor):
    from carveracontroller.ui.fonts import FontFace, arialuni_path

    path = arialuni_path()
    faces = (
        FontFace("DejaVu Sans", "Regular", False, path, 400),
        FontFace("DejaVu Sans", "Regular", True, path, 400),
        FontFace("DejaVu Sans", "Bold", False, path, 700),
    )
    monkeypatch.setattr(fonts, "_load_font_index", lambda: {"DejaVu Sans": faces})
    fonts._index_cache = None
    default = editor.font_default_field
    default.field.text = "DejaVu Sans"

    assert default.weight.values == ["Regular", "Bold"]
    assert default.style.values == ["Roman", "Italic"]
    default.weight.text = "Bold"
    assert default.style.values == ["Roman"]
    assert default.spec() == {"family": "DejaVu Sans", "weight": "Bold", "style": "Roman"}
    assert editor.draft.font_default == "DejaVu Sans [Bold Roman]"

    top = editor.font_top_bar_field
    assert top.spec() == ""
    assert top.weight.disabled is True
    assert top.style.disabled is True
    assert top.weight.text == "Bold"


def test_font_family_search_ignores_case_spaces_and_punctuation():
    from carveracontroller.ui.fonts.dropdown import matching_font_families

    families = ["Same as default", "ARIALUNI", "DejaVu Sans", "Liberation Mono"]
    assert matching_font_families(families, "") == families
    assert matching_font_families(families, "deja") == ["DejaVu Sans"]
    assert matching_font_families(families, "liberationmono") == ["Liberation Mono"]
    assert matching_font_families(families, "DEFAULT") == ["Same as default"]
    assert matching_font_families(families, "zzz") == []


def test_font_family_field_opens_a_filtered_list(editor):
    field = editor.font_default_field.field
    field.values = ["ARIALUNI", "DejaVu Sans", "Liberation Mono"]
    field._open()
    popup = field._popup
    try:
        assert popup.list.viewclass is not None
        assert [row["text"] for row in popup.list.data] == ["ARIALUNI", "DejaVu Sans", "Liberation Mono"]
        from kivy.clock import Clock

        for _step in range(5):
            Clock.tick()
        shown = [child.text for child in popup.list.layout_manager.children]
        assert "ARIALUNI" in shown
        popup.search.text = "liberationmono"
        for _step in range(5):
            Clock.tick()
        assert [child.text for child in popup.list.layout_manager.children] == ["Liberation Mono"]
        assert [row["text"] for row in popup.list.data] == ["Liberation Mono"]
        popup.list.dispatch("on_choose", "Liberation Mono")
        assert field.text == "Liberation Mono"
        assert popup._is_open is False
    finally:
        if popup.parent is not None:
            popup.dismiss()


def test_font_edit_enables_save_until_the_field_matches_again(editor):
    field = editor.font_top_bar_field.field
    original = field.text

    field.text = "DejaVuSans"
    assert editor._draft_is_dirty() is True

    field.text = original
    assert editor._draft_is_dirty() is False


def test_font_fields_list_families_and_optional_roles_follow_the_default(monkeypatch, editor):
    from carveracontroller.ui.fonts import arialuni_path

    path = arialuni_path()
    monkeypatch.setattr(fonts, "_load_font_index", lambda: {"DejaVu Sans": path})
    fonts._index_cache = None
    same = tr._("Same as default")

    default = editor.font_default_field
    default.width = 800
    default.do_layout()
    assert default._name_column.center_y == pytest.approx(default._controls.center_y, abs=1)
    assert default.field.values == ["ARIALUNI", "DejaVu Sans"]
    assert default.spec() == "ARIALUNI"
    assert same not in default.field.values

    top = editor.font_top_bar_field
    assert top.field.values[0] == same
    assert "DejaVu Sans" in top.field.values
    assert top.spec() == ""

    top.field.text = "DejaVu Sans"
    assert top.weight.values == ["Regular"]
    assert top.style.values == ["Roman"]
    assert editor.draft.font_top_bar == "DejaVu Sans [Regular Roman]"
    assert editor._draft_is_dirty() is True

    top.show("")
    assert top.spec() == ""
    assert top.weight.disabled is True
    assert top.weight.text == default.weight.text
    assert editor._draft_is_dirty() is False


def test_token_rows_fit_below_the_theme_chooser(editor):
    column = editor._fields_column
    needed = editor._column_height(column)
    assert column.height == pytest.approx(needed)
    tabs = float(editor._tab_scroll.height) + float(editor._fields_pane.spacing)
    assert editor._fields_scroll.height == pytest.approx(editor._pane_height - tabs)
    assert editor._chooser.parent is editor._editor_layout
    assert editor._fields_pane.parent is editor._body_row
    assert editor._tab_scroll.parent is editor._fields_pane
    assert editor._fields_scroll.parent is editor._fields_pane
    assert editor._chooser not in editor._fields_scroll.walk()
    assert editor._tab_scroll not in editor._fields_scroll.walk()


def test_fields_and_preview_use_separate_scroll_views(editor):
    assert editor._fields_scroll is not editor._preview_scroll
    assert editor.preview.parent is editor._preview_scroll
    assert editor._fields_column.parent is editor._fields_scroll


def test_category_tabs_show_one_section_and_share_the_preview(editor):
    assert editor._active_section == "colors"
    assert editor._sections["colors"].parent is editor._fields_column
    assert editor._sections["axis"].parent is None
    assert editor._sections["fonts"].parent is None
    assert editor._section_tabs["colors"].state == "down"
    assert list(editor._fields_column.children) == [editor._sections["colors"]]
    preview = editor._preview_column

    editor._section_tabs["behaviors"].state = "down"

    assert editor._active_section == "behaviors"
    assert editor._sections["behaviors"].parent is editor._fields_column
    assert editor._sections["colors"].parent is None
    assert editor._section_tabs["colors"].state == "normal"
    assert editor._behavior_fields["jog_pad_axis_colors"] in editor._fields_column.walk()
    assert preview.parent is editor._body_row
    assert editor._rows["bg"].parent is editor._sections["colors"]


def test_gcode_preview_uses_multiple_draft_syntax_colors(editor):
    sample = editor.preview.gcode_sample
    assert editor.set_token("gcode_comment", "#111111") is True
    assert editor.set_token("gcode_g_command", "#222222") is True
    assert "[color=#111111]" in sample.text
    assert "[color=#222222]" in sample.text
    assert "M3" in sample.text
    assert "T1" in sample.text


def test_preview_gets_the_spare_width(editor):
    wide = fields_pane_width() + float(PREVIEW_PANE_WIDTH) + 400
    editor._body_row.width = wide
    editor._apply_pane_widths(wide)
    editor._body_row.do_layout()
    assert editor._preview_column.width == pytest.approx(float(PREVIEW_PANE_WIDTH))
    assert editor._fields_pane.width > editor._preview_column.width
    assert editor._fields_pane.x < editor._preview_column.x
    assert editor._tab_scroll.right <= editor._fields_pane.right + 1


def test_descriptions_fit_and_controls_stay_centered(editor):
    row = editor._rows["axis_a"]
    row.width = fields_pane_width()
    row.do_layout()
    row._name_column.do_layout()
    description = row._description
    assert description.texture_size[0] <= description.width + 1
    assert description.height >= description.texture_size[1] - 1
    assert row.field.height == pytest.approx(row.revert.height)
    field_mid = row.field.y + row.field.height / 2
    row_mid = row.y + row.height / 2
    assert field_mid == pytest.approx(row_mid, abs=1)
    assert row.swatch.height == pytest.approx(row.revert.height)
    assert row.revert.width == pytest.approx(row.revert.height)
    assert row.revert.fill_color is not None


def test_preview_samples_keep_a_realistic_size(editor):
    preview = editor.preview
    assert editor._preview_header.parent is editor._preview_column
    assert preview.axis_row.parent is preview.bar
    assert preview.gcode_sample.parent is preview._page
    assert len(preview.gcode_sample.rows) == len(_GCODE_PREVIEW_LINES)
    assert preview.gcode_sample.rows[0].number.text == "1"
    preview.icon_button._sync_canvas()
    assert preview.icon_button._icon.center == pytest.approx(preview.icon_button.center)
    icon_fill = editor.draft.button_fill("normal", "normal", False, True)
    assert list(preview.icon_button.fill_color.rgba) == pytest.approx(icon_fill)
    assert [chip.letter.text for chip in preview.axis_chips] == ["X", "Y", "Z", "A"]
    assert preview.run_button.size_hint_x is None
    assert list(preview.close_button.fill_color.rgba) == pytest.approx(
        editor.draft.button_fill("normal", "normal", False, True)
    )
    assert list(preview.delete_button.fill_color.rgba) == pytest.approx(editor.draft.danger)
    assert list(preview.run_button.label.color) == pytest.approx(editor.draft.text_on_fill)
    assert editor.set_token("radius_m", "14") is True
    run_radii = [corner[0] for corner in preview.run_button.fill_rect.radius]
    assert run_radii == pytest.approx([dp(14)] * 4)
    assert preview.icon_button.width == pytest.approx(preview.icon_button.height)
    assert preview.axis_row.width < float(PREVIEW_PANE_WIDTH)
    assert editor.set_token("axis_x", "#112233") is True
    assert list(preview.axis_chips[0].letter.color) == pytest.approx(parse_hex_color("#112233"))
    assert editor.set_token("bg", "#f4f5f7") is True
    assert list(preview.bg_color.rgba) == pytest.approx(parse_hex_color("#f4f5f7"))
    assert list(editor._preview_backdrop.rgba) == pytest.approx(parse_hex_color("#f4f5f7"))
    assert editor.set_token("top_bar_radius", "20") is True
    radii = [corner[0] for corner in preview.axis_chips[0].fill_rect.radius]
    assert radii == pytest.approx([dp(20)] * 4)


def test_pane_fills_the_settings_viewport(editor):
    from kivy.uix.settings import ContentPanel, SettingsPanel

    panel = SettingsPanel()
    scroll = ContentPanel(size=(800, 900))
    scroll.add_widget(panel)
    panel.add_widget(editor)
    editor._sync_viewport_height()
    assert editor.height + editor._panel_chrome() == pytest.approx(900)
    assert editor._body_row.height == pytest.approx(editor._pane_height)


def test_preview_visibility_follows_body_width(editor):
    minimum = fields_pane_width() + float(PREVIEW_PANE_WIDTH)
    assert preview_shown_for_width(minimum - 1) is False
    assert preview_shown_for_width(minimum + float(PREVIEW_PANE_WIDTH)) is True

    editor._on_body_width(editor._body_row, minimum - 1)
    assert editor._preview_visible is False
    assert editor._preview_column.parent is None

    editor._on_body_width(editor._body_row, fields_pane_width() + float(PREVIEW_PANE_WIDTH) * 2)
    assert editor._preview_visible is True
    assert editor._preview_column.parent is editor._body_row
