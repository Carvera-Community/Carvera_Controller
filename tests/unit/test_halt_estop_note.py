"""Tests for halt-popup e-stop note appending."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from carveracontroller.CNC import CNC
from carveracontroller.main import HALT_REASON_ESTOP, Makera

NOTE = (
    "The emergency stop is engaged and may be the cause of this alarm. "
    "Disengage it before clearing the alarm or resetting the machine."
)
HALTED_TITLE = "Machine Is Halted: Home Fail"
HALTED_BANG_TITLE = "Machine Is Halted!"
BODY = "Choose unlock option:"

ZH_COLON = "机器告警: "
ZH_BANG = "机器告警!"
ZH_TITLE = "机器告警: 回零失败"


class _Label:
    def __init__(self, text=""):
        self.text = text


class _Popup:
    def __init__(self, showing=False, is_open=None, title="", content=""):
        self.showing = showing
        self._is_open = showing if is_open is None else is_open
        self.lb_title = _Label(title)
        self.lb_content = _Label(content)


@pytest.fixture
def halt_host():
    return SimpleNamespace(
        unlock_popup=_Popup(showing=True, title=HALTED_TITLE, content=BODY),
        confirm_popup=_Popup(),
    )


@pytest.fixture(autouse=True)
def alarm_vars():
    CNC.vars["halt_reason"] = 2
    CNC.vars["st_e_stop"] = 0
    yield
    CNC.vars["halt_reason"] = 1
    CNC.vars["st_e_stop"] = 0


def _apply(host):
    with patch("carveracontroller.main.App.get_running_app", return_value=SimpleNamespace(state="Alarm")):
        Makera._apply_estop_note_to_halt_popup(host)


def test_does_not_append_when_estop_not_engaged(halt_host):
    _apply(halt_host)
    assert halt_host.unlock_popup.lb_content.text == BODY


def test_appends_note_when_estop_engaged(halt_host):
    CNC.vars["st_e_stop"] = 1
    _apply(halt_host)
    assert halt_host.unlock_popup.lb_content.text == NOTE + "\n\n" + BODY


def test_append_is_idempotent(halt_host):
    CNC.vars["st_e_stop"] = 1
    _apply(halt_host)
    once = halt_host.unlock_popup.lb_content.text
    _apply(halt_host)
    assert halt_host.unlock_popup.lb_content.text == once


def test_empty_body_becomes_note_when_engaged(halt_host):
    halt_host.unlock_popup.lb_content.text = ""
    CNC.vars["st_e_stop"] = 1
    _apply(halt_host)
    assert halt_host.unlock_popup.lb_content.text == NOTE


def test_skips_when_halt_reason_is_estop(halt_host):
    CNC.vars["halt_reason"] = HALT_REASON_ESTOP
    CNC.vars["st_e_stop"] = 1
    _apply(halt_host)
    assert halt_host.unlock_popup.lb_content.text == BODY


def test_appends_during_open_animation_before_showing(halt_host):
    halt_host.unlock_popup.showing = False
    halt_host.unlock_popup._is_open = True
    CNC.vars["st_e_stop"] = 1
    _apply(halt_host)
    assert halt_host.unlock_popup.lb_content.text == NOTE + "\n\n" + BODY


def test_removes_stale_note_when_estop_clears(halt_host):
    halt_host.unlock_popup.lb_content.text = NOTE + "\n\n" + BODY
    CNC.vars["st_e_stop"] = 0
    _apply(halt_host)
    assert halt_host.unlock_popup.lb_content.text == BODY


def test_appends_for_unknown_halt_bang_title(halt_host):
    halt_host.unlock_popup.lb_title.text = HALTED_BANG_TITLE
    CNC.vars["st_e_stop"] = 1
    _apply(halt_host)
    assert halt_host.unlock_popup.lb_content.text == NOTE + "\n\n" + BODY


def test_skips_non_halt_popup_title(halt_host):
    halt_host.unlock_popup.lb_title.text = "Delete File or Dir"
    CNC.vars["st_e_stop"] = 1
    _apply(halt_host)
    assert halt_host.unlock_popup.lb_content.text == BODY


def test_appends_when_title_uses_translated_halt_prefix(halt_host):
    halt_host.unlock_popup.lb_title.text = ZH_TITLE
    CNC.vars["st_e_stop"] = 1

    def fake_tr(s):
        return {
            "Machine Is Halted: ": ZH_COLON,
            "Machine Is Halted!": ZH_BANG,
            NOTE: NOTE,
        }.get(s, s)

    with (
        patch("carveracontroller.main.tr._", side_effect=fake_tr),
        patch("carveracontroller.main.App.get_running_app", return_value=SimpleNamespace(state="Alarm")),
    ):
        Makera._apply_estop_note_to_halt_popup(halt_host)
    assert halt_host.unlock_popup.lb_content.text == NOTE + "\n\n" + BODY
