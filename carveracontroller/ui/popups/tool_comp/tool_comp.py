"""Popup for stored tool diameter/wear (M493.3) and cutter compensation mode."""

from __future__ import annotations

import math
from functools import partial
from typing import Any, cast

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.modalview import ModalView

from carveracontroller.CNC import CNC
from carveracontroller.translation import tr
from carveracontroller.ui import widget_helpers

# Status |CC: mode is 0 off, 41 G41 left, 42 G42 right.
# Ignore edits smaller than the 0.001 mm shown in the form.
_VALUE_EPSILON = 0.0005
MODES = (
    ("none", "None"),
    ("left", "Left"),
    ("right", "Right"),
)
_MODE_GCODE = {
    "none": "G40",
    "left": "G41",
    "right": "G42",
}


def mode_key_from_status(mode: int) -> str:
    """Map a |CC: mode code to none, left, or right."""
    if mode == 41:
        return "left"
    if mode == 42:
        return "right"
    return "none"


def cutter_comp_mode_label(mode: int) -> str:
    """User-facing name for a |CC: mode code."""
    if mode == 41:
        return tr._("Left")
    if mode == 42:
        return tr._("Right")
    if mode == 0:
        return tr._("None")
    return str(int(mode))


def _labels(options):
    return [tr._(label) for _key, label in options]


def _key_from_label(options, text: str) -> str:
    for key, label in options:
        if text == tr._(label) or text == label:
            return key
    return "none"


def build_tool_comp_commands(
    diameter: float | None,
    wear: float | None,
    mode: str,
    current_mode: str,
) -> list[str]:
    """G-code lines that store diameter and wear, then set compensation mode.

    A missing value is left unchanged. Diameter and wear changes are rejected
    while G41/G42 is active, so any stored value is preceded by G40. Both words
    go on one M493.3. Wear is sent with the opposite sign of the form value, so
    3 becomes W-3.000 and -3 becomes W3.000. The requested mode is sent
    afterwards unless the cancel already left compensation in that mode.
    """
    if mode not in _MODE_GCODE:
        raise ValueError("Unknown cutter comp mode: %s" % mode)

    commands = []
    words = []
    if diameter is not None:
        words.append("D%.3f" % diameter)
    if wear is not None:
        wire_wear = -wear
        if wire_wear == 0.0:
            wire_wear = 0.0
        words.append("W%.3f" % wire_wear)
    if words:
        commands.append("G40")
        commands.append("M493.3 " + " ".join(words))
        effective_mode = "none"
    else:
        effective_mode = current_mode if current_mode in _MODE_GCODE else "none"
    if mode != effective_mode:
        commands.append(_MODE_GCODE[mode])
    return commands


def _status_int(name: str, default: int = 0) -> int:
    # CNC.vars mixes strings and numbers, so mypy types each value as object.
    return int(cast(int, CNC.vars.get(name, default)))


def _status_float(name: str, default: float = 0.0) -> float:
    return float(cast(float, CNC.vars.get(name, default)))


def _show_error(message: str) -> None:
    app = App.get_running_app()
    Clock.schedule_once(partial(app.root.show_message_popup, message, False), 0)


def _parse_optional_number(text: str) -> float | None:
    raw = text.strip().replace(",", ".")
    if not raw:
        return None
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError
    return value


def _show_text(field, text: str) -> None:
    if field.text == text:
        field.text = ""
    field.text = text


def _changed(value: float | None, stored: float) -> float | None:
    if value is None or abs(value - stored) <= _VALUE_EPSILON:
        return None
    return value


class ToolCompPopup(ModalView):
    def __init__(self, **kwargs: Any) -> None:
        self._auto_select_bound = False
        self._height_tracking = False
        super().__init__(**kwargs)

    def on_kv_post(self, _base_widget) -> None:
        self._ensure_height_tracking()

    def _ensure_height_tracking(self) -> None:
        # Same approach as the jog popup: the modal height follows the inner
        # layout once every child has a fixed height.
        if self._height_tracking:
            return
        body = self.ids.get("tool_comp_body")
        if body is None:
            return
        self._height_tracking = True
        body.bind(minimum_height=self._snap_height)
        self._snap_height()

    def _snap_height(self, *_args) -> None:
        body = self.ids.get("tool_comp_body")
        if body is None:
            return
        height = body.minimum_height
        if height > 0:
            self.height = height

    def on_pre_open(self) -> None:
        super().on_pre_open()
        self._fill_from_status()

    def on_open(self) -> None:
        # TextInput with right alignment ignores a value set before it has a
        # width, so fill again once the popup is on screen.
        super().on_open()
        self._fill_from_status()

    def _fill_from_status(self) -> None:
        ids = self.ids
        ids.sp_mode.values = _labels(MODES)
        mode = _status_int("cutter_comp_mode")
        mode_text = tr._(dict(MODES)[mode_key_from_status(mode)])
        diameter_text = "%.3f" % _status_float("tool_diameter")
        wear_text = "%.3f" % _status_float("tool_diameter_wear")
        # AliasProperty skips a refresh when the string is unchanged, which
        # leaves right-aligned text drawn at the old width.
        ids.sp_mode.text = mode_text
        _show_text(ids.txt_diameter, diameter_text)
        _show_text(ids.txt_wear, wear_text)
        Clock.schedule_once(self._snap_height, 0)
        if not self._auto_select_bound:
            widget_helpers.bind_auto_select_to_text_input(ids.txt_diameter)
            widget_helpers.bind_auto_select_to_text_input(ids.txt_wear)
            self._auto_select_bound = True

    def on_apply_pressed(self) -> None:
        mode = _key_from_label(MODES, self.ids.sp_mode.text)
        try:
            diameter = _parse_optional_number(self.ids.txt_diameter.text)
            wear = _parse_optional_number(self.ids.txt_wear.text)
        except ValueError:
            _show_error(tr._("Enter a valid number."))
            return

        stored_diameter = _status_float("tool_diameter")
        stored_wear = _status_float("tool_diameter_wear")
        send_diameter = _changed(diameter, stored_diameter)
        send_wear = _changed(wear, stored_wear)
        if send_diameter is not None and send_diameter <= 0:
            _show_error(tr._("Nominal diameter must be greater than 0."))
            return

        effective_diameter = stored_diameter if diameter is None else diameter
        # Blank or unchanged wear keeps the stored firmware value. A new form
        # value is stored with the opposite sign.
        effective_wear = stored_wear if send_wear is None else -send_wear
        if mode in ("left", "right"):
            if effective_diameter <= 0:
                _show_error(tr._("Cutter compensation needs a nominal diameter greater than 0."))
                return
            if effective_diameter + effective_wear <= 0:
                _show_error(tr._("Effective diameter (nominal plus wear) must be greater than 0."))
                return

        current_mode = mode_key_from_status(_status_int("cutter_comp_mode"))
        commands = build_tool_comp_commands(send_diameter, send_wear, mode, current_mode)
        if commands:
            app = App.get_running_app()
            app.root.controller.executeCommands(commands)
        self.dismiss()
