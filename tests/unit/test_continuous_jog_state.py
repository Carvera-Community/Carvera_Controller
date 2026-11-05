"""Continuous-jog state updates from firmware stop lines."""

import time
from types import SimpleNamespace

import pytest

from carveracontroller.addons.pendant.pendant import WHB04, GamepadPendant
from carveracontroller.CNC import CNC
from carveracontroller.Controller import CONTINUOUS_JOG_STOP_TIMEOUT, Controller

STOP_LINES = ("Internal stop request reset", "Stop request timeout")


@pytest.fixture
def controller():
    return Controller(CNC(), lambda _line: None, False)


def _logged_lines(controller):
    lines = []
    while not controller.log.empty():
        level, text = controller.log.get_nowait()
        lines.append((level, text))
    return lines


@pytest.mark.parametrize("line", STOP_LINES)
def test_leftover_stop_line_leaves_an_active_jog_running(controller, line):
    controller.continuous_jog_active = True

    controller.parseLine(line)

    assert controller.continuous_jog_active is True
    assert controller._continuous_jog_stop_requested_at == 0.0
    assert _logged_lines(controller) == [(Controller.MSG_NORMAL, line)]


@pytest.mark.parametrize("line", STOP_LINES)
def test_leftover_stop_line_does_not_clear_a_jog_that_is_stopping(controller, line):
    stop_requested_at = time.monotonic()
    controller.continuous_jog_active = True
    controller._continuous_jog_stop_requested_at = stop_requested_at

    controller.parseLine(line)

    assert controller.continuous_jog_active is True
    assert controller._continuous_jog_stop_requested_at == stop_requested_at
    assert _logged_lines(controller) == [(Controller.MSG_NORMAL, line)]


def test_firmware_jog_end_clears_an_active_jog(controller):
    controller.continuous_jog_active = True

    controller.parseLine("^Y")

    assert controller.continuous_jog_active is False
    assert controller._continuous_jog_stop_requested_at == 0.0
    assert _logged_lines(controller) == []


def test_stale_stop_allows_a_new_jog(controller):
    commands = []
    controller.executeCommand = commands.append
    controller.jog_mode = Controller.JOG_MODE_CONTINUOUS
    controller.jog_speed = 1000
    controller.continuous_jog_active = True
    controller._continuous_jog_stop_requested_at = time.monotonic() - CONTINUOUS_JOG_STOP_TIMEOUT - 0.1

    controller.startContinuousJog("X-")

    assert controller.continuous_jog_active is True
    assert controller._continuous_jog_stop_requested_at == 0.0
    assert commands == ["$J -c X- F1000"]


def test_continuous_jog_busy_clears_a_stale_stop(controller):
    controller.continuous_jog_active = True
    controller._continuous_jog_stop_requested_at = time.monotonic() - CONTINUOUS_JOG_STOP_TIMEOUT - 0.1

    assert controller.continuousJogBusy() is False
    assert controller.continuous_jog_active is False
    assert controller._continuous_jog_stop_requested_at == 0.0


def test_continuous_jog_busy_while_stop_is_recent(controller):
    controller.continuous_jog_active = True
    controller._continuous_jog_stop_requested_at = time.monotonic()

    assert controller.continuousJogBusy() is True
    assert controller.continuous_jog_active is True


def test_continuous_jog_busy_while_jogging(controller):
    controller.continuous_jog_active = True

    assert controller.continuousJogBusy() is True
    assert controller._continuous_jog_stop_requested_at == 0.0


def test_recent_stop_still_blocks_a_new_jog(controller):
    commands = []
    stop_requested_at = time.monotonic()
    controller.executeCommand = commands.append
    controller.jog_mode = Controller.JOG_MODE_CONTINUOUS
    controller.continuous_jog_active = True
    controller._continuous_jog_stop_requested_at = stop_requested_at

    controller.startContinuousJog("X-")

    assert controller.continuous_jog_active is True
    assert controller._continuous_jog_stop_requested_at == stop_requested_at
    assert commands == []


def _stale_stop(controller):
    controller.jog_mode = Controller.JOG_MODE_CONTINUOUS
    controller.jog_speed = 1000
    controller.continuous_jog_active = True
    controller._continuous_jog_stop_requested_at = time.monotonic() - CONTINUOUS_JOG_STOP_TIMEOUT - 0.1


def _gamepad(controller):
    pendant = GamepadPendant.__new__(GamepadPendant)
    pendant._controller = controller
    pendant._last_jog_direction = {}
    pendant._active_continuous_jog_action = None
    pendant._step_index = 1
    return pendant


def _whb04(controller, *, jogging_enabled=True):
    pendant = WHB04.__new__(WHB04)
    pendant._controller = controller
    pendant._jog_mode = Controller.JOG_MODE_CONTINUOUS
    pendant._last_jog_direction = 0
    pendant._is_jogging_enabled = lambda: jogging_enabled
    return pendant


def _wheel(axis="X"):
    return SimpleNamespace(active_axis_name=axis, step_size_value=0.1)


def test_gamepad_stale_stop_starts_a_new_jog(controller):
    commands = []
    controller.executeCommand = commands.append
    _stale_stop(controller)
    pendant = _gamepad(controller)

    pendant._handle_continuous_jog("jog_x", "X", 1.0, 1)

    # jog_speed=1000 × 10% step fraction
    assert commands == ["$J -c X1 F100.0"]
    assert pendant._active_continuous_jog_action == "jog_x"
    assert controller._continuous_jog_stop_requested_at == 0.0


def test_gamepad_continuous_jog_scales_selected_jog_speed(controller):
    commands = []
    controller.executeCommand = commands.append
    controller.jog_mode = Controller.JOG_MODE_CONTINUOUS
    controller.jog_speed = 2000
    pendant = _gamepad(controller)

    pendant._handle_continuous_jog("jog_x", "X", 1.0, 1)

    assert commands == ["$J -c X1 F200.0"]


def test_gamepad_continuous_jog_max_uses_firmware_scale(controller):
    commands = []
    controller.executeCommand = commands.append
    controller.jog_mode = Controller.JOG_MODE_CONTINUOUS
    controller.jog_speed = 10000
    pendant = _gamepad(controller)

    pendant._handle_continuous_jog("jog_x", "X", 1.0, 1)

    assert commands == ["$J -c X1 S0.1"]


def test_gamepad_continuous_jog_z_caps_at_800(controller):
    commands = []
    controller.executeCommand = commands.append
    controller.jog_mode = Controller.JOG_MODE_CONTINUOUS
    controller.jog_speed = 2000
    pendant = _gamepad(controller)

    pendant._handle_continuous_jog("jog_z", "Z", 1.0, 1)

    # min(800, 2000) × 10%
    assert commands == ["$J -c Z1 F80.0"]


def test_gamepad_recent_stop_does_not_start(controller):
    commands = []
    controller.executeCommand = commands.append
    controller.jog_mode = Controller.JOG_MODE_CONTINUOUS
    controller.continuous_jog_active = True
    controller._continuous_jog_stop_requested_at = time.monotonic()
    pendant = _gamepad(controller)

    pendant._handle_continuous_jog("jog_x", "X", 1.0, 1)

    assert commands == []
    assert controller.continuous_jog_active is True
    assert pendant._active_continuous_jog_action is None


def test_gamepad_active_jog_is_not_restarted(controller):
    commands = []
    controller.executeCommand = commands.append
    controller.jog_mode = Controller.JOG_MODE_CONTINUOUS
    controller.continuous_jog_active = True
    pendant = _gamepad(controller)

    pendant._handle_continuous_jog("jog_x", "X", 1.0, 1)

    assert commands == []
    assert controller.continuous_jog_active is True


def test_whb04_stale_stop_starts_a_new_jog(controller):
    commands = []
    controller.executeCommand = commands.append
    _stale_stop(controller)
    pendant = _whb04(controller)

    pendant._handle_jogging(_wheel(), 1)

    assert commands == ["$J -c X1 F100.0"]
    assert controller._continuous_jog_stop_requested_at == 0.0


def test_whb04_recent_stop_does_not_start(controller):
    commands = []
    controller.executeCommand = commands.append
    controller.jog_mode = Controller.JOG_MODE_CONTINUOUS
    controller.jog_speed = 1000
    controller.continuous_jog_active = True
    controller._continuous_jog_stop_requested_at = time.monotonic()
    pendant = _whb04(controller)

    pendant._handle_jogging(_wheel(), 1)

    assert commands == []
    assert controller.continuous_jog_active is True


def test_whb04_disabled_jogging_leaves_a_stale_stop_alone(controller):
    commands = []
    controller.executeCommand = commands.append
    _stale_stop(controller)
    pendant = _whb04(controller, jogging_enabled=False)

    pendant._handle_jogging(_wheel(), 1)

    assert commands == []
    assert controller.continuous_jog_active is True
