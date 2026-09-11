"""Persistence-contract tests for DeferredSettingsPanel.

DeferredSettingsPanel defers Config writes until the user clicks Apply.
ConfigPopup._apply_changes detects what to persist by comparing each
SettingItem's `value` ObjectProperty against a snapshot taken on popup
open. That diff-detection only works if `widget.value` reflects user input.

A custom SettingItem subclass that calls `panel.set_value(...)` without
first updating `self.value` (the original SettingPendantSelector bug, see
issue #576) would otherwise be invisible to the Apply loop and silently
lose data on application restart.

These tests pin the panel's contract so future custom SettingItem types
can't reintroduce the same class of bug. When adding a new custom widget
type, register it in CASES.
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from kivy.clock import Clock
from kivy.config import ConfigParser
from kivy.metrics import dp
from kivy.uix.settings import SettingItem, Settings

from carveracontroller.addons.keyboard_shortcuts import SettingKeyboardShortcuts
from carveracontroller.addons.keyboard_shortcuts.bindings import KeyChord
from carveracontroller.addons.keyboard_shortcuts.ui import _CategoryHeader, _CategorySection
from carveracontroller.addons.pendant.pendant import SettingPendantSelector
from carveracontroller.custom_widgets import SettingColorPicker, SettingGCodeSnippet
from carveracontroller.main import DeferredSettingsPanel, MakeraConfigPanel

# (test_id, registered_type, type_class_or_None, initial, new_value, panel_def_extras)
# type_class_or_None is None for built-in Kivy types that Settings registers
# automatically (bool, numeric, string, options, etc.).
CASES = [
    ("bool", "bool", None, "0", "1", {}),
    ("numeric", "numeric", None, "0", "42", {}),
    ("string", "string", None, "old", "new", {}),
    ("options", "options", None, "a", "b", {"options": ["a", "b"]}),
    ("pendant", "pendant", SettingPendantSelector, "None", "WHB04", {}),
    ("colorpicker", "colorpicker", SettingColorPicker, "0,255,255,255", "255,0,0,255", {}),
    (
        "keyboard_shortcuts",
        "keyboard_shortcuts",
        SettingKeyboardShortcuts,
        "",
        '{"version":1,"bindings":{"open_online_docs":null}}',
        {},
    ),
    (
        "gcodesnippet",
        "gcodesnippet",
        SettingGCodeSnippet,
        "{}",
        '{"name":"x","gcode":"y"}',
        {},
    ),
]


def _make_panel(reg_type, cls, initial, extras):
    """Build a DeferredSettingsPanel containing one SettingItem of the
    requested type. Mirrors how MakeraConfigPanel.create_json_panel
    constructs panels in production (subclass swizzle on the result of
    Settings.create_json_panel)."""
    config = ConfigParser()
    config.add_section("test")
    config.set("test", "key", initial)

    settings = Settings()
    if cls is not None:
        settings.register_type(reg_type, cls)

    panel_def = {"type": reg_type, "title": "T", "section": "test", "key": "key"}
    panel_def.update(extras)

    panel = settings.create_json_panel("T", config, data=json.dumps([panel_def]))
    panel.__class__ = DeferredSettingsPanel
    item = next(w for w in panel.walk() if isinstance(w, SettingItem))
    return panel, item, config


@pytest.mark.parametrize(
    "reg_type,cls,initial,new_value,extras",
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_panel_set_value_syncs_widget_value(reg_type, cls, initial, new_value, extras):
    """After panel.set_value(...), the matching SettingItem's `value` must
    reflect the new value. _apply_changes relies on this to detect what
    needs persisting; a widget that fails this check silently loses data
    on app restart."""
    panel, item, _config = _make_panel(reg_type, cls, initial, extras)
    assert str(item.value) == initial, "fixture sanity check"

    panel.set_value("test", "key", new_value)

    assert str(item.value) == new_value, (
        f"{reg_type}: widget.value did not sync after panel.set_value. "
        f"This widget would be invisible to ConfigPopup._apply_changes "
        f"and silently lose data on app restart."
    )


@pytest.mark.parametrize(
    "reg_type,cls,initial,new_value,extras",
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_panel_set_value_defers_config_write(reg_type, cls, initial, new_value, extras):
    """The deferred panel must not touch Config until Apply.

    If Config gets written eagerly, Discard cannot revert and other parts
    of the app would observe pending changes before the user confirms."""
    panel, _item, config = _make_panel(reg_type, cls, initial, extras)

    panel.set_value("test", "key", new_value)

    assert config.get("test", "key") == initial, (
        f"{reg_type}: Config was written before Apply. Deferred semantics broken — Discard would not revert."
    )


def test_pendant_spinner_change_propagates():
    """Changing the spinner text on SettingPendantSelector must end up in
    widget.value so the Apply loop can persist it. Catches regressions in
    either the panel sync logic or the pendant's on_spinner_select handler."""
    panel, item, config = _make_panel("pendant", SettingPendantSelector, "None", {})

    # Mimic the user picking an entry from the spinner dropdown. Spinner
    # text changes fire the bound on_spinner_select callback.
    item.spinner.text = "WHB04"

    assert str(item.value) == "WHB04", (
        "Pendant change did not reach widget.value — would silently drop user selections on restart."
    )
    assert config.get("test", "key") == "None", "Config write must remain deferred"


def test_settings_page_switch_resets_shared_scroll_view_to_top():
    settings = MakeraConfigPanel()
    config = ConfigParser()
    config.add_section("test")
    config.set("test", "first", "a")
    config.set("test", "second", "b")
    settings.add_json_panel(
        "First",
        config,
        data=json.dumps([{"type": "string", "title": "First", "section": "test", "key": "first"}]),
    )
    content = settings.interface.content
    first_uid = next(iter(content.panels))
    settings.add_json_panel(
        "Second",
        config,
        data=json.dumps([{"type": "string", "title": "Second", "section": "test", "key": "second"}]),
    )
    second_uid = next(uid for uid in content.panels if uid != first_uid)
    content.current_uid = first_uid
    content.scroll_y = 0

    content.current_uid = second_uid
    Clock.tick()

    assert content.scroll_y == 1


def test_shortcut_editor_keeps_full_content_height_after_kivy_layout():
    panel, item, _config = _make_panel("keyboard_shortcuts", SettingKeyboardShortcuts, "", {})

    Clock.tick()

    assert item.height == item._editor_height
    assert item._editor_layout.height == item._editor_height
    assert panel.minimum_height >= item.height
    settled_height = item.height
    for _ in range(3):
        Clock.tick()
    assert item.height == settled_height
    assert item._editor_layout.height == settled_height


def test_shortcut_editor_visually_groups_categories_and_renders_keycaps():
    _panel, item, _config = _make_panel("keyboard_shortcuts", SettingKeyboardShortcuts, "", {})

    sections = [widget for widget in item._editor_layout.children if isinstance(widget, _CategorySection)]
    headers = [widget for section in sections for widget in section.children if isinstance(widget, _CategoryHeader)]

    assert len(sections) == 3
    assert len(headers) == 3
    assert all(header.height > dp(30) for header in headers)
    assert item._binding_displays["jog_y_positive"].key_labels == ("Down",)
    assert item._binding_displays["jog_y_negative"].key_labels == ("Up",)

    item._on_invert_y_axis_jogging(None, True)
    assert item._binding_displays["jog_y_positive"].key_labels == ("Down",)
    assert item._binding_displays["jog_y_negative"].key_labels == ("Up",)
    assert item._bindings.default_for("jog_y_positive") == KeyChord("up")
    assert item._bindings.default_for("jog_y_negative") == KeyChord("down")

    display = item._binding_displays["mdi_send"]
    assert display.key_labels == ("Ctrl", "Enter")
    assert [keycap.text for keycap in display._keycaps] == ["Ctrl", "Enter"]

    item._assign("mdi_send", KeyChord("f2"))
    assert display.key_labels == ("F2",)
    assert [keycap.text for keycap in display._keycaps] == ["F2"]

    item._assign("mdi_send", None)
    assert display.key_labels == ()
    assert display._keycaps == []
    assert display._content.children[0].text == "Unbound"


def test_shortcut_keycap_width_settles_without_layout_feedback():
    _panel, item, _config = _make_panel("keyboard_shortcuts", SettingKeyboardShortcuts, "", {})
    keycaps = item._binding_displays["mdi_send"]._keycaps

    Clock.tick()
    settled_widths = [keycap.width for keycap in keycaps]
    for _ in range(3):
        Clock.tick()

    assert [keycap.width for keycap in keycaps] == settled_widths
    assert all(width < dp(100) for width in settled_widths)


def test_shortcut_capture_waits_for_non_modifier_key():
    _panel, item, _config = _make_panel("keyboard_shortcuts", SettingKeyboardShortcuts, "", {})
    button = SimpleNamespace(text="")
    item._start_capture("mdi_send", button)
    try:
        assert item._capture_key(None, 305, 224, "i", ["ctrl"]) is True
        assert item._listening_for == "mdi_send"
        assert button.text != "Bind..."

        assert item._capture_key(None, 13, 40, "\r", ["ctrl"]) is True
        assert item._listening_for is None
        assert item._bindings.binding_for("mdi_send") == KeyChord("enter", ("ctrl",))
    finally:
        item._stop_capture()


def test_shortcut_capture_stops_when_settings_popup_dismisses():
    _panel, item, _config = _make_panel("keyboard_shortcuts", SettingKeyboardShortcuts, "", {})
    manager = SimpleNamespace(paused=False, release_all_jogs=Mock())
    modal = Mock()

    with (
        patch.object(item, "_shortcut_manager", return_value=manager),
        patch.object(item, "_containing_modal", return_value=modal),
    ):
        item._start_capture("mdi_send", SimpleNamespace(text=""))
        assert manager.paused is True
        item._on_capture_modal_dismiss()

    assert item._listening_for is None
    assert manager.paused is False
    assert item._error_label.text == ""
    modal.unbind.assert_called_once_with(on_dismiss=item._on_capture_modal_dismiss)


def test_shortcut_capture_stops_when_switching_settings_pages():
    settings = MakeraConfigPanel()
    config = ConfigParser()
    config.add_section("test")
    config.set("test", "shortcuts", "")
    config.set("test", "other", "")
    settings.add_json_panel(
        "Shortcuts",
        config,
        data=json.dumps(
            [
                {
                    "type": "keyboard_shortcuts",
                    "title": "Shortcuts",
                    "section": "test",
                    "key": "shortcuts",
                }
            ]
        ),
    )
    content = settings.interface.content
    shortcut_uid = next(iter(content.panels))
    panel = content.panels[shortcut_uid]
    item = next(widget for widget in panel.walk() if isinstance(widget, SettingKeyboardShortcuts))
    settings.add_json_panel(
        "Other",
        config,
        data=json.dumps([{"type": "string", "title": "Other", "section": "test", "key": "other"}]),
    )
    other_uid = next(uid for uid in content.panels if uid != shortcut_uid)
    content.current_uid = shortcut_uid
    manager = SimpleNamespace(paused=False, release_all_jogs=Mock())

    with patch.object(item, "_shortcut_manager", return_value=manager):
        item._start_capture("mdi_send", SimpleNamespace(text=""))
        content.current_uid = other_uid

    assert item._listening_for is None
    assert manager.paused is False
    assert item._error_label.text == ""


def test_shortcut_capture_reports_conflicts_and_escape_clears_the_prompt():
    _panel, item, _config = _make_panel("keyboard_shortcuts", SettingKeyboardShortcuts, "", {})
    button = SimpleNamespace(text="")
    item._start_capture("open_start_job", button)
    try:
        assert item._capture_key(None, 282, 58, "", []) is True
        assert item._listening_for == "open_start_job"
        assert item._bindings.binding_for("open_start_job") is None
        assert "Open Online Documentation" in item._error_label.text

        assert item._capture_key(None, 27, 41, "", []) is True
        assert item._listening_for is None
        assert item._error_label.text == ""
        assert button.text == "Bind..."
    finally:
        item._stop_capture()


def test_shortcut_reset_to_saved_value_dispatches_change_notification():
    initialized = '{"bindings":{},"version":1}'
    panel, item, config = _make_panel("keyboard_shortcuts", SettingKeyboardShortcuts, initialized, {})
    changes = []
    panel.settings.bind(on_config_change=lambda *_args: changes.append(_args[-1]))

    item._assign("open_online_docs", None)
    assert config.get("test", "key") == initialized
    changes.clear()

    item._reset_all()

    assert item.value == initialized
    assert changes == [initialized]
    assert config.get("test", "key") == initialized


def test_shortcut_editor_bypasses_setting_item_blue_selection_animation():
    _panel, item, _config = _make_panel("keyboard_shortcuts", SettingKeyboardShortcuts, "", {})
    touch = object()

    with patch(
        "carveracontroller.addons.keyboard_shortcuts.ui.FloatLayout.on_touch_down",
        return_value=True,
    ) as dispatch:
        assert item.on_touch_down(touch) is True

    dispatch.assert_called_once_with(item, touch)
    assert item.selected_alpha == 0
