"""Theme tokens stay the single source of chrome colors."""

import logging
from pathlib import Path

import pytest
from kivy.app import App
from kivy.graphics import Color, Rectangle
from kivy.graphics.instructions import InstructionGroup
from kivy.lang import Builder
from kivy.properties import ObjectProperty
from kivy.uix.settings import SettingBoolean, SettingItem, SettingSidebarLabel, SettingString

from carveracontroller.ui.theme import Theme

_ROOT = Path(__file__).resolve().parents[2]
_THEME_KV = _ROOT / "carveracontroller" / "ui" / "theme.kv"


def test_apply_updates_tokens_and_snapshot_round_trips():
    theme = Theme()
    theme.apply({"accent": (255, 0, 0, 255), "radius_m": 12}, name="custom")
    assert theme.name == "custom"
    assert theme.accent == pytest.approx([1, 0, 0, 1])
    assert theme.radius_m == 12
    restored = Theme()
    restored.apply(theme.to_dict())
    assert restored.accent == pytest.approx([1, 0, 0, 1])
    assert restored.name == "custom"


def test_apply_ignores_unknown_tokens(caplog):
    theme = Theme()
    accent = list(theme.accent)
    with caplog.at_level(logging.WARNING):
        theme.apply({"not_a_token": 1, "radius_m": 12})
    assert theme.radius_m == 12
    assert list(theme.accent) == pytest.approx(accent)
    assert "not_a_token" in caplog.text


def test_apply_palette_rejects_unknown_name():
    theme = Theme()
    with pytest.raises(ValueError, match="no_such_theme"):
        theme.apply_palette("no_such_theme")


def test_button_fill_follows_role_and_revision_is_explicit():
    theme = Theme()
    assert theme.button_fill("normal", "normal", False, True) == pytest.approx(list(theme.control))
    assert theme.button_fill("normal", "down", False, True) == pytest.approx(list(theme.accent))
    assert theme.button_fill("primary", "normal", False, True) == pytest.approx(list(theme.primary))
    assert theme.button_fill("primary", "down", False, True) == pytest.approx(list(theme.primary_down))
    assert theme.button_fill("danger", "down", False, True) == pytest.approx(list(theme.danger_down))
    assert theme.button_fill("help", "normal", False, True) == pytest.approx(list(theme.help))
    assert theme.button_fill("help", "down", False, True) == pytest.approx(list(theme.help_down))
    assert theme.button_fill("danger", "normal", True, True) == pytest.approx(list(theme.control_disabled))
    assert theme.button_fill("normal", "normal", False, False) == [0, 0, 0, 0]

    before = theme.revision
    theme.accent = [0, 1, 0, 1]
    assert theme.revision == before + 1
    assert theme.button_fill("normal", "down", False, True, theme.revision) == pytest.approx([0, 1, 0, 1])


def test_jog_axis_background_colors_the_face_and_keeps_the_caption_readable():
    theme = Theme()
    theme.text = [0.93, 0.93, 0.94, 1]
    theme.text_inverse = [0.12, 0.12, 0.12, 1]
    theme.text_on_fill = [0.98, 0.98, 0.2, 1]
    theme.axis_x = [0.8, 0.1, 0.1, 1]
    theme.axis_a = [0.97, 0.86, 0.44, 1]
    assert theme.jog_axis_fill("X+", "normal", False, True) == pytest.approx(list(theme.control))
    assert theme.jog_axis_text("X+", "down", False, True) == pytest.approx(list(theme.text_on_fill))

    theme.jog_pad_axis_background = True
    assert theme.jog_axis_fill("X+", "normal", False, True) == pytest.approx(list(theme.axis_x))
    assert theme.jog_axis_fill("A-", "normal", False, True) == pytest.approx(list(theme.axis_a))
    assert theme.jog_axis_fill("X+", "down", False, True) == pytest.approx(
        [channel * 0.75 if index < 3 else channel for index, channel in enumerate(theme.axis_x)]
    )
    assert theme.jog_axis_fill("X+", "normal", True, True) == pytest.approx(list(theme.control_disabled))
    assert theme.jog_axis_fill("X+", "normal", False, False) == [0, 0, 0, 0]
    assert theme.jog_axis_fill("Home", "normal", False, True) == pytest.approx(list(theme.control))
    assert theme.jog_axis_text("X+", "normal", False, True) == pytest.approx(list(theme.text))
    assert theme.jog_axis_text("A+", "normal", False, True) == pytest.approx(list(theme.text_inverse))
    assert theme.jog_axis_text("X+", "normal", True, True) == pytest.approx(list(theme.text_disabled))
    assert theme.jog_axis_text("Home", "down", False, True) == pytest.approx(list(theme.text_on_fill))


def test_selection_fill_uses_accent_and_alpha():
    theme = Theme()
    assert theme.selection_fill(1) == pytest.approx(list(theme.accent))
    assert theme.selection_fill(0)[:3] == pytest.approx(list(theme.accent)[:3])
    assert theme.selection_fill(0)[3] == 0
    theme.accent = [1, 0, 0, 1]
    filled = theme.selection_fill(0.4, theme.revision)
    assert filled[:3] == pytest.approx([1, 0, 0])
    assert filled[3] == pytest.approx(0.4)


class _SettingsThemeApp(App):
    theme = ObjectProperty(None, rebind=True)

    def load_kv(self, filename=None):
        return False

    def build(self):
        return None


def _colors(instruction_group):
    found = []
    for child in instruction_group.children:
        if isinstance(child, Color):
            found.append(list(child.rgba))
        elif isinstance(child, InstructionGroup):
            found.extend(_colors(child))
    return found


def _textured(instruction_group):
    found = []
    for child in instruction_group.children:
        if isinstance(child, Rectangle) and child.texture is not None:
            found.append(child)
        elif isinstance(child, InstructionGroup):
            found.extend(_textured(child))
    return found


def _rounded_rects(instruction_group):
    from kivy.graphics import RoundedRectangle

    found = []
    children = list(instruction_group.children)
    for index, child in enumerate(children):
        if isinstance(child, RoundedRectangle):
            previous = children[index - 1] if index else None
            found.append((previous, child))
        elif isinstance(child, InstructionGroup):
            found.extend(_rounded_rects(child))
    return found


def _restore_kivy_settings_rules():
    # theme.kv clears these Kivy rules. Unloading the file does not put them back.
    names = (
        "SettingSpacer",
        "SettingTitle",
        "SettingsPanel",
        "MenuSidebar",
        "SettingSidebarLabel",
        "SettingItem",
    )
    Builder.load_string("\n".join(_kivy_rule(name) for name in names), filename="kivy-settings-restore.kv")


def _kivy_rule(name):
    import kivy

    text = (Path(kivy.__file__).resolve().parent / "data" / "style.kv").read_text()
    marker = f"<{name}>:"
    start = text.find(marker)
    assert start >= 0, marker
    lines = text[start:].splitlines(keepends=True)
    body = [lines[0].replace(marker, f"<-{name}>:", 1)]
    for line in lines[1:]:
        if line.startswith("<") or line.startswith("# ="):
            break
        body.append(line)
    return "".join(body)


def _settings_theme_rules():
    text = _THEME_KV.read_text()
    start = text.index("<-SettingSidebarLabel>:")
    import_line = next(line for line in text.splitlines() if line.startswith("#:import rgba_to_hex "))
    return f"{import_line}\n{text[start:]}"


def _drop_stub_app(app):
    # Kv caches the first app it sees until on_stop.
    app.dispatch("on_stop")
    App._running_app = None


def _ensure_theme(app):
    if "theme" not in app.properties():
        app.apply_property(theme=ObjectProperty(None, rebind=True))
    if app.theme is None:
        app.theme = Theme()
    return app


def _other_palette(name):
    from carveracontroller.ui.themes import theme_names

    return next(other for other in theme_names() if other != name)


def test_settings_tabs_follow_theme_accent():
    # Canvas color expressions refresh on Builder.sync(), the same flush the
    # frame loop performs. Drop a stub app afterwards so later tests still see
    # no running app.
    created = App.get_running_app() is None
    app = _ensure_theme(App.get_running_app() or _SettingsThemeApp())
    previous = list(app.theme.accent)
    previous_on_fill = list(app.theme.text_on_fill)
    Builder.load_string(_settings_theme_rules(), filename="settings-theme-test.kv")
    try:
        tab = SettingSidebarLabel(text="General", selected=True)
        tab.texture_update()
        assert _colors(tab.canvas.before)[0] == pytest.approx(list(app.theme.accent))
        assert list(tab.color) == pytest.approx(list(app.theme.text_on_fill))
        assert _textured(tab.canvas)
        # A distinct fill color, so this checks the selected tab uses text_on_fill.
        app.theme.text_on_fill = [0.2, 0.8, 0.3, 1]
        Builder.sync()
        assert list(tab.color) == pytest.approx([0.2, 0.8, 0.3, 1])
        tab.selected = False
        Builder.sync()
        assert list(tab.color) == pytest.approx(list(app.theme.text))
        tab.selected = True
        Builder.sync()
        assert list(tab.color) == pytest.approx(list(app.theme.text_on_fill))

        app.theme.accent = [0, 1, 0, 1]
        Builder.sync()
        assert _colors(tab.canvas.before)[0][:3] == pytest.approx([0, 1, 0])

        panel = type(
            "Panel",
            (),
            {
                "get_value": staticmethod(lambda _section, _key: "1"),
                "set_value": staticmethod(lambda _section, _key, _value: None),
            },
        )()
        row = SettingItem(panel=panel, section="s", key="k", title="Light", desc="")
        row.selected_alpha = 1
        Builder.sync()
        assert _colors(row.canvas)[0] == pytest.approx(list(app.theme.accent))

        from kivy.uix.label import Label
        from kivy.uix.switch import Switch

        toggle = SettingBoolean(panel=panel, section="s", key="k", title="Tips", desc="")
        assert any(isinstance(child, Switch) for child in toggle.content.children)
        field = SettingString(panel=panel, section="s", key="k", title="Name", desc="")
        value_labels = [child for child in field.content.children if isinstance(child, Label)]
        assert value_labels[0].text == "1"
        assert list(value_labels[0].color) == pytest.approx(list(app.theme.text))
    finally:
        app.theme.accent = previous
        app.theme.text_on_fill = previous_on_fill
        Builder.unload_file("settings-theme-test.kv")
        _restore_kivy_settings_rules()
        if created:
            _drop_stub_app(app)


def test_main_menu_buttons_share_one_square_size():
    from kivy.factory import Factory
    from kivy.metrics import dp
    from kivy.uix.dropdown import DropDown

    from carveracontroller.addons.tooltips.Tooltips import ToolTipButton
    from carveracontroller.main import IconButton

    assert Factory.get("IconButton") is IconButton
    kv = (_ROOT / "carveracontroller" / "makera.kv").read_text()
    menu_rule = kv[kv.index("<MenuButton@IconButton>:") : kv.index("<TransparentButton>:")]

    padded = DropDown()
    assert padded.pad_menu is True
    assert padded.menu_fill is True
    assert padded.container.padding[0] == pytest.approx(dp(6))
    flush = DropDown(pad_menu=False)
    assert list(flush.container.padding) == pytest.approx([0, 0, 0, 0])
    assert list(flush.container.spacing) == pytest.approx([dp(4), dp(4)])
    bare = DropDown(pad_menu=False, menu_fill=False)
    gap = bare.container.spacing[1]
    assert list(bare.container.padding) == pytest.approx([0, gap, 0, gap])

    created = App.get_running_app() is None
    app = _ensure_theme(App.get_running_app() or _SettingsThemeApp())
    build_tooltip = ToolTipButton._build_tooltip
    ToolTipButton._build_tooltip = lambda *_args, **_kwargs: None
    try:
        if "menu-button-test.kv" not in Builder.files:
            Builder.load_string(menu_rule, filename="menu-button-test.kv")
        opener = Factory.MenuButton()
        item = Factory.MenuButton()
        side = dp(app.theme.top_bar_height - app.theme.bar_padding * 2)
        assert opener.width == pytest.approx(side)
        assert opener.height == pytest.approx(opener.width)
        assert tuple(item.size) == pytest.approx(tuple(opener.size))
        from kivy.graphics import Line

        assert any(isinstance(child, Line) for child in opener.canvas.after.children)
    finally:
        ToolTipButton._build_tooltip = build_tooltip
        if created:
            _drop_stub_app(app)


def test_grouped_main_menu_rounds_only_the_first_and_last_buttons():
    from kivy.metrics import dp
    from kivy.uix.button import Button
    from kivy.uix.gridlayout import GridLayout

    from carveracontroller.main import apply_main_menu_grouping

    grid = GridLayout(cols=1, spacing=(dp(4), dp(4)), size_hint_y=None)
    buttons = [Button(size_hint_y=None, height=10) for _ in range(3)]
    for button in buttons:
        grid.add_widget(button)

    apply_main_menu_grouping(grid, True, 8)
    visual = list(reversed(grid.children))
    assert visual[0].corner_radii == [8, 8, 0, 0]
    assert visual[1].corner_radii == [0, 0, 0, 0]
    assert visual[2].corner_radii == [0, 0, 8, 8]
    assert list(grid.spacing) == [0, 0]

    apply_main_menu_grouping(grid, False, 8)
    assert all(button.corner_radii == [] for button in visual)
    assert list(grid.spacing) == pytest.approx([dp(4), dp(4)])


def test_menu_grouping_survives_the_dropdown_spacing_applied_after_kv():
    from kivy.metrics import dp
    from kivy.uix.button import Button
    from kivy.uix.dropdown import DropDown

    from carveracontroller.main import apply_main_menu_grouping

    class GroupedMenu(DropDown):
        def on_kv_post(self, _base):
            for _ in range(3):
                self.add_widget(Button())
            apply_main_menu_grouping(self.container, True, 8)
            self._apply_menu_grouping = lambda *_args: apply_main_menu_grouping(self.container, True, 8)

    menu = GroupedMenu(pad_menu=False, menu_fill=False)
    visual = list(reversed(menu.container.children))
    assert list(menu.container.spacing) == [0, 0]
    assert list(menu.container.padding) == pytest.approx([0, dp(4), 0, dp(4)])
    assert visual[0].corner_radii == [8, 8, 0, 0]
    assert visual[1].corner_radii == [0, 0, 0, 0]
    assert visual[2].corner_radii == [0, 0, 8, 8]


def test_hidden_menu_row_does_not_leave_an_extra_gap():
    from kivy.uix.gridlayout import GridLayout
    from kivy.uix.widget import Widget

    from carveracontroller.main import sync_optional_menu_item

    grid = GridLayout(cols=1, spacing=4, size_hint_y=None)
    buttons = [Widget(size_hint_y=None, height=10) for _ in range(3)]
    for button in buttons:
        grid.add_widget(button)
    hidden = buttons[1]

    def height_after_layout():
        grid.do_layout()
        return grid.minimum_height

    sync_optional_menu_item(grid, hidden, show=False)
    assert hidden.parent is None
    assert height_after_layout() == pytest.approx(24)

    sync_optional_menu_item(grid, hidden, show=True)
    assert hidden.parent is grid
    assert grid.children[1] is hidden
    assert height_after_layout() == pytest.approx(38)


def test_removed_menu_row_survives_after_its_id_proxy_dies():
    import gc
    import weakref

    from kivy.uix.gridlayout import GridLayout
    from kivy.uix.widget import Widget

    from carveracontroller.main import hold_menu_button, sync_optional_menu_item

    grid = GridLayout(cols=1, size_hint_y=None)
    button = Widget(size_hint_y=None, height=10)
    grid.add_widget(button)
    proxy = weakref.proxy(button)
    held = hold_menu_button(grid, proxy)
    assert held is button
    sync_optional_menu_item(grid, held, show=False)
    assert held.parent is None
    sync_optional_menu_item(grid, held, show=True)
    assert held.parent is grid

    orphan = Widget()
    dead = weakref.proxy(orphan)
    del orphan
    gc.collect()
    sync_optional_menu_item(grid, dead, show=True)


def test_theme_helpers_return_tokens():
    from carveracontroller.ui.theme import get_theme, machine_state_color, watch_theme

    theme = get_theme()
    assert machine_state_color("Idle") == pytest.approx(list(theme.machine_idle))
    assert machine_state_color("Run") == pytest.approx(list(theme.machine_run))
    assert machine_state_color("Alarm") == pytest.approx(list(theme.machine_alarm))
    assert machine_state_color("N/A") == pytest.approx(list(theme.machine_not_connected))
    assert machine_state_color("unknown") == pytest.approx(list(theme.text_muted))

    seen = []
    stop = watch_theme(seen.append)
    assert len(seen) == 1
    stop()


def test_set_theme_repaints_the_status_color():
    """A palette switch must keep the machine-state tint, not text_muted."""
    from kivy.factory import Factory
    from kivy.uix.widget import Widget

    from carveracontroller.CNC import CNC
    from carveracontroller.main import MakeraApp
    from carveracontroller.ui.theme import machine_state_color
    from carveracontroller.ui.themes import theme_names

    created = App.get_running_app() is None
    app = _ensure_theme(App.get_running_app() or _SettingsThemeApp())
    previous_name = app.theme.name
    previous_root = app.root
    had_state = "state" in app.properties() or "state" in getattr(app, "__dict__", {})
    previous_state = getattr(app, "state", None)
    saved_color = CNC.vars.get("color")
    Builder.load_string(
        "<StatusColorProbe@Widget>:\n    color: app.theme.text_muted\n",
        filename="status-color-reapply-test.kv",
    )
    try:
        probe = Factory.StatusColorProbe()
        root = Widget()
        root.status_data_view = probe
        app.root = root
        app.state = "Run"
        probe.color = list(machine_state_color("Run"))
        app._reapply_status_color = MakeraApp._reapply_status_color.__get__(app)
        MakeraApp.set_theme(app, _other_palette(app.theme.name))
        expected = list(machine_state_color("Run"))
        assert list(probe.color) == pytest.approx(expected)
        assert list(CNC.vars["color"]) == pytest.approx(expected)
    finally:
        Builder.unload_file("status-color-reapply-test.kv")
        app.root = previous_root
        if had_state:
            app.state = previous_state
        elif "state" in getattr(app, "__dict__", {}):
            del app.state
        if previous_name in theme_names():
            app.theme.apply_palette(previous_name)
        if saved_color is not None:
            CNC.vars["color"] = saved_color
        if created:
            _drop_stub_app(app)


def test_remap_mdi_entry_moves_token_colors():
    from carveracontroller.main import remap_mdi_entry

    theme = Theme()
    pale = list(theme.info_text)
    entry = {
        "text": "Connected to machine!",
        "color": list(pale),
        "original_color": list(pale),
        "entry_type": "output",
    }
    theme.apply({"info_text": [0.15, 0.25, 0.35, 1]})
    remapped = remap_mdi_entry(entry, theme)
    assert remapped["text"] == "Connected to machine!"
    assert remapped["color"] == pytest.approx(list(theme.info_text))
    assert remapped["original_color"] == pytest.approx(list(theme.info_text))
    assert remapped["color"] != pytest.approx(pale)
    custom = {"text": "note", "color": [0.2, 0.3, 0.4, 1]}
    assert remap_mdi_entry(custom, theme)["color"] == [0.2, 0.3, 0.4, 1]


def test_apply_palette_switches_and_round_trips():
    theme = Theme()
    original_name = theme.name
    original = theme.to_dict()
    before = theme.revision
    other = _other_palette(original_name)

    theme.apply_palette(other)
    assert theme.name == other
    assert theme.revision > before

    theme.apply_palette(original_name)
    assert theme.name == original_name
    assert theme.to_dict() == original
    assert Theme(other).name == other


def test_button_text_and_icon_follow_role():
    theme = Theme()
    assert theme.button_text("normal", "normal", False, True) == pytest.approx(list(theme.text))
    assert theme.button_text("normal", "down", False, True) == pytest.approx(list(theme.text_on_fill))
    for role in ("primary", "danger", "help"):
        assert theme.button_text(role, "normal", False, True) == pytest.approx(list(theme.text_on_fill))
    assert theme.button_text("primary", "down", True, True) == pytest.approx(list(theme.text_disabled))
    assert theme.button_text("primary", "normal", False, False) == pytest.approx(list(theme.text))
    assert theme.icon_tint("normal", "normal", False, True) == pytest.approx(list(theme.icon))
    assert theme.icon_tint("normal", "down", False, True) == pytest.approx(list(theme.text_on_fill))
    assert theme.icon_tint("primary", "normal", False, True) == pytest.approx(list(theme.text_on_fill))
    assert theme.icon_tint("normal", "down", True, True) == pytest.approx(list(theme.text_disabled))
    assert theme.icon_rgba(True, "normal", "down", False, True) == [1, 1, 1, 1]
    assert theme.icon_rgba(True, "normal", "normal", True, True)[3] == pytest.approx(0.4)
    assert theme.icon_rgba(False, "normal", "normal", False, True) == pytest.approx(list(theme.icon))


def _builder_has(suffix):
    needle = suffix.replace("\\", "/")
    return any(str(path).replace("\\", "/").endswith(needle) for path in Builder.files)


def _kv_rule(text, name):
    marker = f"<{name}>:"
    start = text.index(marker)
    lines = text[start:].splitlines(keepends=True)
    body = [lines[0]]
    for line in lines[1:]:
        if line.startswith("<"):
            break
        body.append(line)
    return "".join(body)


def test_pressed_composite_buttons_use_fill_text():
    # Icon buttons and the top-bar readouts draw their caption in child labels.
    # The button face still turns accent while pressed, so those labels have to
    # take text_on_fill. The tokens below are distinct so a wrong one fails.
    from kivy.uix.label import Label

    from carveracontroller.addons.tooltips.Tooltips import ToolTipButton
    from carveracontroller.main import IconButton, TopDataView

    created = App.get_running_app() is None
    app = _ensure_theme(App.get_running_app() or _SettingsThemeApp())
    palette_name = app.theme.name
    app.theme.apply(
        {
            "text": [0.11, 0.12, 0.13, 1],
            "text_on_fill": [0.91, 0.92, 0.13, 1],
            "icon": [0.21, 0.51, 0.81, 1],
            "text_disabled": [0.61, 0.62, 0.63, 1],
            "text_muted": [0.41, 0.42, 0.43, 1],
            "axis_x": [0.81, 0.21, 0.21, 1],
        }
    )
    # The full app already loaded these files. Loading them again applies each
    # rule twice, and ScrollingLabel then tries to take a second child.
    loaded_theme = False
    if not _builder_has("ui/theme.kv"):
        Builder.load_string(_THEME_KV.read_text(), filename="composite-button-theme.kv")
        loaded_theme = True
    loaded_rules = False
    if not _builder_has("makera.kv"):
        bars = (_ROOT / "carveracontroller" / "makera.kv").read_text()
        Builder.load_string(
            _kv_rule(bars, "IconButton")
            + "\n"
            + _kv_rule(bars, "ScrollingLabel")
            + "\n"
            + _kv_rule(bars, "TopDataView"),
            filename="composite-button-rules.kv",
        )
        loaded_rules = True
    build_tooltip = ToolTipButton._build_tooltip
    ToolTipButton._build_tooltip = lambda self, *args: None
    try:
        icon = IconButton(text="Menu")
        caption = next(child for child in icon.children if isinstance(child, Label))
        assert list(caption.color) == pytest.approx(list(app.theme.text))
        assert _colors(caption.canvas.before)[0] == pytest.approx(list(app.theme.icon))
        icon.state = "down"
        Builder.sync()
        assert list(caption.color) == pytest.approx(list(app.theme.text_on_fill))
        assert _colors(caption.canvas.before)[0] == pytest.approx(list(app.theme.text_on_fill))
        icon.disabled = True
        Builder.sync()
        assert list(caption.color) == pytest.approx(list(app.theme.text_disabled))
        assert _colors(caption.canvas.before)[0] == pytest.approx(list(app.theme.text_disabled))

        # The e-stop PNG is red. Multiplying it by the light icon gray turns it brown.
        stop = IconButton(colored=True)
        stop_icon = next(child for child in stop.children if isinstance(child, Label))
        assert _colors(stop_icon.canvas.before)[0] == pytest.approx([1, 1, 1, 1])
        stop.state = "down"
        Builder.sync()
        assert _colors(stop_icon.canvas.before)[0] == pytest.approx([1, 1, 1, 1])
        stop.disabled = True
        Builder.sync()
        assert _colors(stop_icon.canvas.before)[0][:3] == pytest.approx([1, 1, 1])
        assert _colors(stop_icon.canvas.before)[0][3] < 1

        view = TopDataView()
        view.main_text = "N/A"
        view.minr_text = "disconnect"
        view.data_text = "X"
        view.color = list(app.theme.axis_x)
        captions = {
            label.text: label for label in view.walk() if isinstance(label, Label) and label is not view and label.text
        }
        assert list(captions["X"].color) == pytest.approx(list(app.theme.axis_x))
        assert list(captions["N/A"].color) == pytest.approx(list(app.theme.text))
        assert list(captions["disconnect"].color) == pytest.approx(list(app.theme.text_muted))
        view.state = "down"
        for label in captions.values():
            assert list(label.color) == pytest.approx(list(app.theme.text_on_fill)), label.text
        view.state = "normal"
        assert list(captions["X"].color) == pytest.approx(list(app.theme.axis_x))
        assert list(captions["N/A"].color) == pytest.approx(list(app.theme.text))
        assert list(captions["disconnect"].color) == pytest.approx(list(app.theme.text_muted))
    finally:
        ToolTipButton._build_tooltip = build_tooltip
        app.theme.apply_palette(palette_name)
        if loaded_rules:
            Builder.unload_file("composite-button-rules.kv")
        if loaded_theme:
            Builder.unload_file("composite-button-theme.kv")
            # Unloading does not restore the Kivy rules theme.kv cleared.
            _restore_kivy_settings_rules()
        if created:
            _drop_stub_app(app)


def test_display_menu_rows_have_no_idle_fill_and_softer_icons():
    from kivy.uix.label import Label

    from carveracontroller.main import GcodeViewerDisplayMenuButton

    created = App.get_running_app() is None
    app = _ensure_theme(App.get_running_app() or _SettingsThemeApp())
    palette_name = app.theme.name
    app.theme.apply(
        {
            "icon": [0.2, 0.5, 0.8, 1],
            "text": [0.1, 0.1, 0.1, 1],
            "text_on_fill": [0.95, 0.95, 0.2, 1],
            "accent": [0.1, 0.3, 0.8, 1],
        }
    )
    bars = (_ROOT / "carveracontroller" / "makera.kv").read_text()
    Builder.load_string(_kv_rule(bars, "GcodeViewerDisplayMenuButton"), filename="display-menu-rules.kv")
    try:
        row = GcodeViewerDisplayMenuButton()
        row.text = "Grid"
        Builder.sync()
        assert _colors(row.canvas.before)[0] == [0, 0, 0, 0]
        icon = next(child for child in row.children if not isinstance(child, Label))
        label = next(child for child in row.children if isinstance(child, Label))
        assert _colors(icon.canvas)[0] == pytest.approx(list(app.theme.icon))
        assert list(label.color) == pytest.approx(list(app.theme.text))
        row.state = "down"
        Builder.sync()
        assert _colors(row.canvas.before)[0] == pytest.approx(list(app.theme.accent))
        assert _colors(icon.canvas)[0] == pytest.approx(list(app.theme.text_on_fill))
        assert list(label.color) == pytest.approx(list(app.theme.text_on_fill))
    finally:
        app.theme.apply_palette(palette_name)
        Builder.unload_file("display-menu-rules.kv")
        if created:
            _drop_stub_app(app)


def test_separators_follow_the_theme_border():
    from kivy.uix.popup import Popup
    from kivy.uix.settings import MenuSidebar, SettingSpacer, SettingsPanel, SettingTitle
    from kivy.uix.splitter import SplitterStrip

    created = App.get_running_app() is None
    app = _ensure_theme(App.get_running_app() or _SettingsThemeApp())
    palette_name = app.theme.name
    Builder.load_string(_THEME_KV.read_text(), filename="separator-theme.kv")
    bars = (_ROOT / "carveracontroller" / "makera.kv").read_text()
    Builder.load_string(_kv_rule(bars, "SplitterStrip"), filename="separator-splitter.kv")
    try:
        border = list(app.theme.border)
        Builder.sync()
        assert _colors(SettingSpacer().canvas)[0] == pytest.approx(border)
        assert _colors(SettingTitle(text="Motion").canvas)[1] == pytest.approx(border)
        assert _colors(SettingTitle(text="Motion").canvas)[0] == pytest.approx(list(app.theme.row_heading))
        panel = SettingsPanel(title="Controller")
        title = next(child for child in panel.children if getattr(child, "text", "") == "Controller")
        assert _colors(title.canvas.after)[0] == pytest.approx(border)
        sidebar = MenuSidebar()
        assert _colors(sidebar.ids.menu.canvas.after)[0] == pytest.approx(border)
        strip = SplitterStrip()
        assert any(color == pytest.approx(border) for color in _colors(strip.canvas.before))
        popup = Popup(title="Theme")
        assert list(popup.separator_color) == pytest.approx(border)
        assert popup.separator_height == 1
        app.theme.apply_palette(_other_palette(palette_name))
        Builder.sync()
        assert list(popup.separator_color) == pytest.approx(list(app.theme.border))
    finally:
        app.theme.apply_palette(palette_name)
        Builder.unload_file("separator-splitter.kv")
        Builder.unload_file("separator-theme.kv")
        _restore_kivy_settings_rules()
        if created:
            _drop_stub_app(app)


def test_remap_color_moves_copied_token_colors_to_the_new_palette():
    theme = Theme()
    old_muted = list(theme.text_muted)
    theme.apply({"text_muted": [0.2, 0.3, 0.4, 1]})
    assert theme.remap_color(old_muted) == pytest.approx(list(theme.text_muted))
    assert theme.remap_color([0.123, 0.456, 0.789, 1.0]) is None
    assert theme.remap_color(None) is None


def test_follow_theme_keeps_colors_a_widget_chose_itself():
    from kivy.uix.label import Label

    from carveracontroller.ui.theme import follow_theme

    label = Label()
    assert follow_theme(label, "color", [0.1, 0.2, 0.3, 1], (1, 1, 1, 1)) is True
    assert list(label.color) == pytest.approx([0.1, 0.2, 0.3, 1])
    label.color = [0.9, 0.1, 0.1, 1]
    assert follow_theme(label, "color", [0.5, 0.5, 0.5, 1], (1, 1, 1, 1)) is False
    assert list(label.color) == pytest.approx([0.9, 0.1, 0.1, 1])


def test_labels_follow_the_palette_unless_they_set_a_color():
    from kivy.uix.button import Button
    from kivy.uix.label import Label

    created = App.get_running_app() is None
    app = _ensure_theme(App.get_running_app() or _SettingsThemeApp())
    theme = app.theme
    palette_name = theme.name
    Builder.load_string(_THEME_KV.read_text(), filename="themed-labels-test.kv")
    try:
        plain = Label(text="plain")
        copied = Label(text="copied", color=theme.text_muted)
        custom = Label(text="custom", color=[0.9, 0.1, 0.1, 1])
        button = Button(text="button")
        # Popups made in Python, like Kivy's own option chooser, use the panel color.
        from kivy.uix.modalview import ModalView
        from kivy.uix.popup import Popup

        assert list(Popup(title="t").background_color) == pytest.approx(list(theme.surface))
        assert list(ModalView().background_color) == pytest.approx(list(theme.surface))
        assert list(plain.color) == pytest.approx(list(theme.text))
        assert list(button.color) == pytest.approx(list(theme.text))

        theme.apply_palette(_other_palette(palette_name))
        assert list(plain.color) == pytest.approx(list(theme.text))
        assert list(copied.color) == pytest.approx(list(theme.text_muted))
        assert list(custom.color) == pytest.approx([0.9, 0.1, 0.1, 1])
        assert list(button.color) == pytest.approx(list(theme.text))
        primary = Button(text="primary", role="primary")
        assert list(primary.color) == pytest.approx(list(theme.text_on_fill))

        # A disabled label paints disabled_color, not color. Kivy's default is
        # white at 30% opacity.
        plain.disabled = True
        plain.texture_update()
        assert list(plain.disabled_color) == pytest.approx(list(theme.text_disabled))
        assert list(plain._label.options["color"]) == pytest.approx(list(theme.text_disabled))

        # Buttons declared in kv get their rules after __init__ returns, so the
        # starting color has to come from the kv expression, not from __init__.
        Builder.load_string(
            "<KvThemedHost@BoxLayout>:\n    Button:\n        id: plain\n    Button:\n        id: accent\n        role: 'primary'\n",
            filename="themed-kv-buttons-test.kv",
        )
        try:
            from kivy.factory import Factory

            host = Factory.KvThemedHost()
            assert list(host.ids.plain.color) == pytest.approx(list(theme.text))
            assert list(host.ids.accent.color) == pytest.approx(list(theme.text_on_fill))

            # A button that blanks its own disabled text must keep that over the label default.
            Builder.load_string(
                "<ClearDisabled@Button>:\n    disabled_color: 0, 0, 0, 0\n",
                filename="themed-clear-disabled-test.kv",
            )
            try:
                assert list(Factory.ClearDisabled().disabled_color) == pytest.approx([0, 0, 0, 0])
            finally:
                Builder.unload_file("themed-clear-disabled-test.kv")
        finally:
            Builder.unload_file("themed-kv-buttons-test.kv")
    finally:
        theme.apply_palette(palette_name)
        Builder.unload_file("themed-labels-test.kv")
        if created:
            _drop_stub_app(app)


def test_theme_setting_shows_titles_and_stores_names():
    from kivy.uix.label import Label
    from kivy.uix.togglebutton import ToggleButton

    from carveracontroller.ui.theme import SettingTheme
    from carveracontroller.ui.themes import theme_names, theme_title

    created = App.get_running_app() is None
    app = _ensure_theme(App.get_running_app() or _SettingsThemeApp())
    Builder.load_string(_THEME_KV.read_text(), filename="themed-setting-test.kv")
    current, other = theme_names()[:2]
    current_title, other_title = theme_title(current), theme_title(other)

    class _Panel:
        def get_value(self, _section, _key):
            return current

        def set_value(self, _section, _key, _value):
            return None

    try:
        item = SettingTheme(panel=_Panel(), section="carvera", key="theme", title="Theme", options=[current, other])
        assert item.shown_value(current) == current_title
        assert item.shown_value(other) == other_title
        assert item.shown_value("missing") == "missing"
        label = next(widget for widget in item.walk() if isinstance(widget, Label) and widget.text == current_title)
        item._create_popup(item)
        try:
            buttons = [child for child in reversed(item.popup.content.children) if isinstance(child, ToggleButton)]
            assert [button.text for button in buttons] == [current_title, other_title]
            assert buttons[0].state == "down"
            buttons[1].dispatch("on_release")
            assert item.value == other
            assert label.text == other_title
        finally:
            if item.popup is not None:
                item.popup.dismiss()
    finally:
        Builder.unload_file("themed-setting-test.kv")
        if created:
            _drop_stub_app(app)


def test_text_fields_use_a_flat_fill():
    from kivy.factory import Factory
    from kivy.graphics import BindTexture, BorderImage
    from kivy.uix.textinput import TextInput

    created = App.get_running_app() is None
    app = _ensure_theme(App.get_running_app() or _SettingsThemeApp())
    palette_name = app.theme.name
    other = _other_palette(palette_name)
    Builder.load_string(_THEME_KV.read_text(), filename="themed-text-field-test.kv")
    try:
        field = TextInput(text="12", size=(120, 40))
        assert field.background_normal == ""
        assert field.background_active == ""
        assert field.background_disabled_normal == ""
        assert list(field.background_color) == pytest.approx(list(app.theme.field_bg))
        assert list(field.foreground_color) == pytest.approx(list(app.theme.text))
        assert list(field.cursor_color) == pytest.approx(list(app.theme.text))

        def colors():
            return _colors(field.canvas.before)

        assert colors()[0] == pytest.approx(list(app.theme.field_bg))
        assert colors()[1][:3] == pytest.approx(list(app.theme.border)[:3])
        bound = _rounded_rects(field.canvas.before)
        assert bound
        previous, rect = bound[0]
        assert list(rect.pos) == pytest.approx(list(field.pos))
        assert list(rect.size) == pytest.approx(list(field.size))
        # The rect has to keep the texture bind that was inserted with it.
        # Without that bind it paints the previously drawn label, stretched.
        assert isinstance(previous, BindTexture)
        assert previous.texture is rect.texture
        # The shaded atlas image stays in the canvas; its tint is cleared so it
        # does not cover the flat fill.
        assert any(isinstance(child, BorderImage) for child in field.canvas.before.children)
        assert list(field._field_shade.rgba) == pytest.approx([0, 0, 0, 0])
        Builder.sync()
        # The text colour stays last, so the glyphs are not tinted with the fill.
        assert colors()[-1] == pytest.approx(list(app.theme.text))

        field.focus = True
        Builder.sync()
        assert colors()[1][:3] == pytest.approx(list(app.theme.accent)[:3])

        field.disabled = True
        Builder.sync()
        assert list(field.background_color) == pytest.approx(list(app.theme.control_disabled))
        assert colors()[0] == pytest.approx(list(app.theme.control_disabled))
        assert colors()[1][:3] == pytest.approx(list(app.theme.border)[:3])
        field.disabled = False

        app.theme.apply_palette(other)
        Builder.sync()
        assert list(field.background_color) == pytest.approx(list(app.theme.field_bg))
        assert colors()[0] == pytest.approx(list(app.theme.field_bg))
        assert list(field.foreground_color) == pytest.approx(list(app.theme.text))

        Builder.load_string(
            "<ClearField@TextInput>:\n    background_color: 0, 0, 0, 0\n",
            filename="themed-clear-field-test.kv",
        )
        try:
            clear = Factory.ClearField(size=(80, 30))
            clear_colors = _colors(clear.canvas.before)
            assert list(clear.background_color) == pytest.approx([0, 0, 0, 0])
            assert clear_colors[0][3] == pytest.approx(0)
            assert clear_colors[1][3] == pytest.approx(0)

            # A theme switch re-evaluates the shared field rule. A field that
            # cleared its background must stay clear, or it grows a border.
            app.theme.apply_palette(palette_name)
            Builder.sync()
            clear_colors = _colors(clear.canvas.before)
            assert list(clear.background_color) == pytest.approx([0, 0, 0, 0])
            assert clear_colors[0][3] == pytest.approx(0)
            assert clear_colors[1][3] == pytest.approx(0)
            assert list(field.background_color) == pytest.approx(list(app.theme.field_bg))
            assert _colors(field.canvas.before)[1][3] == pytest.approx(1)
        finally:
            Builder.unload_file("themed-clear-field-test.kv")
    finally:
        app.theme.apply_palette(palette_name)
        Builder.unload_file("themed-text-field-test.kv")
        if created:
            _drop_stub_app(app)


def test_theme_setting_is_on_its_own_page():
    import json

    from carveracontroller.ui.themes import DEFAULT_THEME

    controller = json.loads((_ROOT / "carveracontroller" / "controller_config.json").read_text())
    assert all(item.get("key") != "theme" for item in controller)
    settings = json.loads((_ROOT / "carveracontroller" / "ui" / "themes" / "config.json").read_text())
    option = next(item for item in settings if item.get("key") == "theme")
    assert option["section"] == "carvera"
    assert option["type"] == "theme_editor"
    assert option["default"] == DEFAULT_THEME
    assert not option.get("desc")
