"""IntelliSense popups must not appear over modal dialogs."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from kivy.uix.dropdown import DropDown
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup

from carveracontroller.addons.intellisense import ui as intel_ui
from carveracontroller.addons.tooltips.Tooltips import is_blocked_by_modal


def _modal():
    return ModalView.__new__(ModalView)


@contextmanager
def _window_children(children):
    with patch("carveracontroller.addons.tooltips.Tooltips.Window", SimpleNamespace(children=children)):
        yield


def test_is_blocked_when_modal_is_on_window():
    with _window_children([_modal()]):
        assert is_blocked_by_modal()
        assert is_blocked_by_modal(SimpleNamespace(parent=None))


def test_is_blocked_when_popup_is_on_window():
    with _window_children([Popup.__new__(Popup)]):
        assert is_blocked_by_modal()


def test_not_blocked_without_modal():
    with _window_children([SimpleNamespace()]):
        assert not is_blocked_by_modal()
        assert not is_blocked_by_modal(SimpleNamespace(parent=None))


def test_not_blocked_by_dropdown_alone():
    with _window_children([DropDown.__new__(DropDown)]):
        assert not is_blocked_by_modal()


def test_widget_inside_modal_is_not_blocked():
    modal = _modal()
    child = SimpleNamespace(parent=modal)
    with _window_children([modal]):
        assert not is_blocked_by_modal(child)


def test_widget_behind_modal_is_blocked():
    modal = _modal()
    other = SimpleNamespace(parent=SimpleNamespace(parent=None))
    with _window_children([modal]):
        assert is_blocked_by_modal(other)


def test_show_gcode_does_not_display_when_modal_open(monkeypatch):
    host = intel_ui._IntellisenseHost()
    monkeypatch.setattr(intel_ui, "is_blocked_by_modal", lambda widget=None: True)
    row = SimpleNamespace(plain_text="G54", get_root_window=lambda: True)

    host.show_gcode(row, reason="hover")

    assert host.gcode_popup.showing is False


def test_mouse_pos_dismisses_instead_of_hovering_when_modal_open(monkeypatch):
    host = intel_ui._IntellisenseHost()
    scheduled = []
    dismissed = []
    monkeypatch.setattr(intel_ui, "is_blocked_by_modal", lambda widget=None: True)
    monkeypatch.setattr(intel_ui, "schedule_gcode_hover", lambda row: scheduled.append(row))
    host._dismiss_for_overlay = lambda: dismissed.append(True)

    host._on_window_mouse_pos(None, (10, 10))

    assert scheduled == []
    assert dismissed == [True]


def test_display_refuses_when_modal_open(monkeypatch):
    popup = intel_ui.IntellisensePopupBase()
    monkeypatch.setattr(intel_ui, "is_blocked_by_modal", lambda widget=None: True)

    popup.display()

    assert popup.showing is False
    assert popup.parent is None


def test_scheduled_hover_aborts_if_modal_opens_during_delay(monkeypatch):
    captured = {}
    monkeypatch.setattr(intel_ui.Clock, "schedule_once", lambda cb, dt: captured.setdefault("cb", cb))
    monkeypatch.setattr(intel_ui.Clock, "unschedule", lambda cb: None)
    monkeypatch.setattr(intel_ui, "is_blocked_by_modal", lambda widget=None: True)
    hidden = []
    shown = []
    monkeypatch.setattr(intel_ui, "hide_gcode_explain", lambda row=None: hidden.append(row))
    monkeypatch.setattr(intel_ui, "show_gcode_explain", lambda row, reason="hover": shown.append(row))
    row = SimpleNamespace(get_root_window=lambda: True, plain_text="G54")

    intel_ui.schedule_gcode_hover(row)
    captured["cb"](0)

    assert hidden == [row]
    assert shown == []


def test_window_children_change_dismisses_open_popup(monkeypatch):
    host = intel_ui._IntellisenseHost()
    host.gcode_popup.showing = True
    dismissed = []
    monkeypatch.setattr(intel_ui, "is_blocked_by_modal", lambda widget=None: True)
    host._dismiss_for_overlay = lambda: dismissed.append(True)

    host._on_window_children(None, [])

    assert dismissed == [True]
