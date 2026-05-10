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

import pytest
from kivy.config import ConfigParser
from kivy.uix.settings import SettingItem, Settings

from carveracontroller.addons.pendant.pendant import SettingPendantSelector
from carveracontroller.custom_widgets import SettingColorPicker, SettingGCodeSnippet
from carveracontroller.main import DeferredSettingsPanel


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
        f"{reg_type}: Config was written before Apply. "
        f"Deferred semantics broken — Discard would not revert."
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
        "Pendant change did not reach widget.value — would silently drop "
        "user selections on restart."
    )
    assert config.get("test", "key") == "None", "Config write must remain deferred"
