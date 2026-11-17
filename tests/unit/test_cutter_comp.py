"""Cutter compensation status parsing and M493.3 / G40-G42 command building."""

import pytest

from carveracontroller.CNC import CNC
from carveracontroller.Controller import Controller
from carveracontroller.ui.popups.tool_comp import build_tool_comp_commands


@pytest.fixture(autouse=True)
def reset_cutter_comp():
    CNC.vars["cutter_comp_mode"] = 0
    CNC.vars["cutter_comp_radius"] = 0.0
    CNC.vars["tool_diameter"] = 0.0
    CNC.vars["tool_diameter_wear"] = 0.0
    yield
    CNC.vars["cutter_comp_mode"] = 0
    CNC.vars["cutter_comp_radius"] = 0.0
    CNC.vars["tool_diameter"] = 0.0
    CNC.vars["tool_diameter_wear"] = 0.0


def _parse_status_line(line):
    controller = Controller(CNC(), lambda _line: None, False)
    controller.parseBracketAngle(line)


def test_cc_field_stores_mode_radius_diameter_and_wear():
    _parse_status_line("<Idle|MPos:1.0,2.0,3.0|WPos:1.0,2.0,3.0|CC:41,3.175,6.350,-0.050>")
    assert CNC.vars["cutter_comp_mode"] == 41
    assert CNC.vars["cutter_comp_radius"] == pytest.approx(3.175)
    assert CNC.vars["tool_diameter"] == pytest.approx(6.350)
    assert CNC.vars["tool_diameter_wear"] == pytest.approx(-0.050)


def test_cc_field_does_not_collide_with_machine_state():
    _parse_status_line("<Idle|MPos:0,0,0|WPos:0,0,0|C:2,4,0,1|CC:42,1.500,3.000,0.100|O:0.250>")
    assert CNC.vars["MachineModel"] == 2
    assert CNC.vars["FuncSetting"] == 4
    assert CNC.vars["inch_mode"] == 0
    assert CNC.vars["absolute_mode"] == 1
    assert CNC.vars["cutter_comp_mode"] == 42
    assert CNC.vars["tool_diameter"] == pytest.approx(3.0)
    assert CNC.vars["max_delta"] == pytest.approx(0.250)


def test_missing_cc_field_clears_previous_compensation():
    _parse_status_line("<Idle|MPos:0,0,0|WPos:0,0,0|CC:41,1.000,2.000,0.000>")
    _parse_status_line("<Idle|MPos:0,0,0|WPos:0,0,0>")
    assert CNC.vars["cutter_comp_mode"] == 0
    assert CNC.vars["cutter_comp_radius"] == 0.0
    assert CNC.vars["tool_diameter"] == 0.0
    assert CNC.vars["tool_diameter_wear"] == 0.0


def test_off_mode_keeps_stored_diameter():
    _parse_status_line("<Idle|MPos:0,0,0|WPos:0,0,0|CC:0,0.000,6.000,0.200>")
    assert CNC.vars["cutter_comp_mode"] == 0
    assert CNC.vars["tool_diameter"] == pytest.approx(6.0)
    assert CNC.vars["tool_diameter_wear"] == pytest.approx(0.2)


def test_diameter_and_left_cancels_before_storing_then_enables():
    commands = build_tool_comp_commands(6.35, None, "left", "left")
    assert commands == ["G40", "M493.3 D6.350", "G41"]


def test_wear_and_off_does_not_send_a_second_cancel():
    commands = build_tool_comp_commands(None, 0.05, "none", "left")
    assert commands == ["G40", "M493.3 W-0.050"]


def test_positive_ui_wear_is_sent_negative():
    commands = build_tool_comp_commands(None, 3, "none", "none")
    assert commands == ["G40", "M493.3 W-3.000"]


def test_negative_ui_wear_is_sent_positive():
    commands = build_tool_comp_commands(None, -3, "none", "none")
    assert commands == ["G40", "M493.3 W3.000"]


def test_diameter_and_wear_share_one_m493_command():
    commands = build_tool_comp_commands(6.35, 0.05, "right", "none")
    assert commands == ["G40", "M493.3 D6.350 W-0.050", "G42"]


def test_mode_only_change():
    assert build_tool_comp_commands(None, None, "right", "none") == ["G42"]
    assert build_tool_comp_commands(None, None, "none", "left") == ["G40"]


def test_unchanged_mode_sends_nothing():
    assert build_tool_comp_commands(None, None, "left", "left") == []


def test_execute_commands_sends_each_line(monkeypatch):
    sent = []
    controller = Controller(CNC(), lambda _line: None, False)
    monkeypatch.setattr(controller, "executeCommand", lambda line: sent.append(line))
    controller.executeCommands(["G40", "M493.3 D6.350", "G41"])
    assert sent == ["G40\n", "M493.3 D6.350\n", "G41\n"]
