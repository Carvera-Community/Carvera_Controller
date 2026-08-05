"""Phase splitting and ProbeRunner sequencing for CMM Workbench probe runs.

The probe move must stay on its own line so it can be sent apart from the short
setup and result commands; batching them stops the firmware answering status
queries long enough for the host to declare the connection lost.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from carveracontroller.addons.cmm_workbench.core.gcode import (
    ProbeProgram,
    build_m463,
    build_m466,
)
from carveracontroller.addons.cmm_workbench.ui import probe_runner as probe_runner_mod
from carveracontroller.addons.cmm_workbench.ui.probe_runner import ProbeRunner


def test_probe_program_keeps_the_probe_move_on_its_own():
    program = build_m466(x="10")

    assert program.setup == ["G21", "G90", "G17", "G94"]
    assert program.probe.startswith("M466 X10 ")
    assert program.tail[0].startswith("M118 CMMProbe START M466 ")
    assert program.tail[-1] == "M118 CMMProbe END"
    assert "M118" not in program.probe
    assert "\n" not in program.probe


def test_probe_program_echoes_one_variable_per_tail_line():
    program = build_m463(10, 10)

    echoes = [ln for ln in program.tail if ln.startswith("M118.1")]
    assert echoes == ["M118.1 P#154", "M118.1 P#155"]


class _FakeClockEvent:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def runner_harness(monkeypatch):
    """ProbeRunner with controllable clock, wall-clock, and machine state."""
    now = {"t": 1000.0}
    state = {"value": "Idle"}
    executed: list[str] = []
    aborted: list[str] = []
    machine_aborts: list[str] = []
    is_probing = {"value": False}
    status_text = {"value": ""}
    scheduled_once: list[tuple[object, float, _FakeClockEvent]] = []

    def fake_time():
        return now["t"]

    def schedule_interval(callback, dt):
        return _FakeClockEvent()

    def schedule_once(callback, dt):
        event = _FakeClockEvent()
        scheduled_once.append((callback, dt, event))
        return event

    monkeypatch.setattr(probe_runner_mod.time, "time", fake_time)
    monkeypatch.setattr(
        probe_runner_mod,
        "Clock",
        SimpleNamespace(schedule_interval=schedule_interval, schedule_once=schedule_once),
    )

    program = ProbeProgram(
        setup=["G21", "G90", "G17", "G94"],
        probe="M466 X10 F100",
        tail=[
            "M118 CMMProbe START M466 X",
            "M118.1 P#150",
            "M118 CMMProbe END",
        ],
    )

    runner = ProbeRunner(
        set_is_probing=lambda v: is_probing.__setitem__("value", v),
        set_status_text=lambda v: status_text.__setitem__("value", v),
        on_is_probing_changed=lambda: None,
        controller_abort=lambda: machine_aborts.append("abort"),
        get_state=lambda: state["value"],
        execute_line=lambda line: executed.append(line),
        on_aborted=lambda reason: aborted.append(reason),
    )

    return SimpleNamespace(
        runner=runner,
        program=program,
        now=now,
        state=state,
        executed=executed,
        aborted=aborted,
        machine_aborts=machine_aborts,
        is_probing=is_probing,
        status_text=status_text,
        scheduled_once=scheduled_once,
    )


def _advance_past_setup(h):
    """Send setup, wait out settle, poll until the probe command is sent."""
    h.runner.start(h.program)
    assert h.executed == list(h.program.setup)
    h.now["t"] += probe_runner_mod._SETUP_SETTLE_S
    h.runner._poll()
    assert h.executed[-1] == h.program.probe
    assert h.executed == list(h.program.setup) + [h.program.probe]


def test_setup_is_sent_immediately_and_probe_waits_for_settle(runner_harness):
    h = runner_harness
    h.runner.start(h.program)

    assert h.is_probing["value"] is True
    assert h.executed == list(h.program.setup)

    h.runner._poll()
    assert h.executed == list(h.program.setup)

    h.now["t"] += probe_runner_mod._SETUP_SETTLE_S - 0.01
    h.runner._poll()
    assert h.executed == list(h.program.setup)

    h.now["t"] += 0.01
    h.runner._poll()
    assert h.executed == list(h.program.setup) + [h.program.probe]


def test_setup_does_not_advance_while_machine_is_running(runner_harness):
    h = runner_harness
    h.runner.start(h.program)
    h.now["t"] += probe_runner_mod._SETUP_SETTLE_S
    h.state["value"] = "Run"
    h.runner._poll()

    assert h.executed == list(h.program.setup)


def test_tail_is_sent_after_busy_then_idle(runner_harness):
    h = runner_harness
    _advance_past_setup(h)

    h.state["value"] = "Run"
    h.runner._poll()
    assert h.executed == list(h.program.setup) + [h.program.probe]

    h.state["value"] = "Idle"
    h.runner._poll()
    assert h.executed == list(h.program.setup) + [h.program.probe] + list(h.program.tail)


def test_tail_is_not_sent_while_still_running(runner_harness):
    h = runner_harness
    _advance_past_setup(h)

    h.state["value"] = "Run"
    h.runner._poll()
    h.runner._poll()

    assert h.executed == list(h.program.setup) + [h.program.probe]


def test_tail_is_sent_after_grace_when_run_was_never_seen(runner_harness):
    h = runner_harness
    _advance_past_setup(h)

    h.now["t"] += probe_runner_mod._MOTION_GRACE_S - 0.01
    h.runner._poll()
    assert h.executed == list(h.program.setup) + [h.program.probe]

    h.now["t"] += 0.01
    h.runner._poll()
    assert h.executed == list(h.program.setup) + [h.program.probe] + list(h.program.tail)


def test_unexpected_state_aborts_the_run(runner_harness):
    h = runner_harness
    _advance_past_setup(h)

    h.state["value"] = "Alarm"
    h.runner._poll()

    assert h.is_probing["value"] is False
    assert h.runner.get_active_token() is None
    assert h.machine_aborts == ["abort"]
    assert len(h.aborted) == 1
    assert "Alarm" in h.aborted[0]
    assert h.executed == list(h.program.setup) + [h.program.probe]


def test_timeout_aborts_the_run(runner_harness):
    h = runner_harness
    token = h.runner.start(h.program)
    assert len(h.scheduled_once) == 1
    timeout_cb, timeout_s, _event = h.scheduled_once[0]
    assert timeout_s == probe_runner_mod._PROBE_TIMEOUT_S

    timeout_cb(0)

    assert h.is_probing["value"] is False
    assert h.runner.is_token_valid(token) is False
    assert h.aborted == ["Probe timed out."]


def test_stale_timeout_is_ignored_after_complete(runner_harness):
    h = runner_harness
    h.runner.start(h.program)
    timeout_cb, _timeout_s, _event = h.scheduled_once[0]

    h.runner.complete()
    timeout_cb(0)

    assert h.aborted == []
    assert h.is_probing["value"] is False
