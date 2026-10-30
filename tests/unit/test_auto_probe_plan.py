"""
Tests for what M495 does before a program that moves in several work coordinate systems: a scan
margin around the feed moves of each WCS in program order, Z probe and leveling in the start WCS,
and a start WCS that only probes the part for the WCS following it.
"""

import importlib
from types import SimpleNamespace

import pytest

from carveracontroller.CNC import CNC
from carveracontroller.Controller import Controller

# the package exports the CoordPopup class under the module name
CoordPopup = importlib.import_module("carveracontroller.ui.config_run.CoordPopup")

ORIGINS = {"G54": (100.0, 50.0, 0.0), "G55": (200.0, 50.0, 90.0), "G58": (300.0, 100.0, 0.0)}


def _config(zprobe_origin=1, leveling=True, offsets=(0, 0, 0, 0)):
    return {
        "zprobe": {"active": True, "origin": zprobe_origin, "x_offset": 5.0, "y_offset": 5.0},
        "leveling": {
            "active": leveling,
            "xn_offset": offsets[0],
            "xp_offset": offsets[1],
            "yn_offset": offsets[2],
            "yp_offset": offsets[3],
        },
    }


def _program(monkeypatch, wcs, start, writes=()):
    """writes: (wcs, written wcs) for each WCS written before its feed moves"""
    monkeypatch.setattr(CoordPopup.App, "get_running_app", lambda: SimpleNamespace(has_4axis=False))
    monkeypatch.setattr(CoordPopup, "program_wcs_extents", lambda: wcs)
    monkeypatch.setattr(CoordPopup, "program_wcs_writes", lambda: list(writes))
    monkeypatch.setattr(CoordPopup, "start_wcs_origin", lambda: (start, *ORIGINS[start]))
    monkeypatch.setattr(CoordPopup, "wcs_origin", ORIGINS.get)


@pytest.fixture
def program(monkeypatch):
    """A program that starts in G55, rotated by 90°, and then moves in G54."""
    _program(monkeypatch, [("G55", [2.0, 20.0, 1.0, 10.0]), ("G54", [0.0, 30.0, 0.0, 40.0])], "G55")


@pytest.fixture
def probing_program(monkeypatch):
    """G58 only probes the part and writes G54 with M468, G54 and then G55 cut."""
    _program(
        monkeypatch,
        [("G58", None), ("G54", [0.0, 30.0, 0.0, 40.0]), ("G55", [2.0, 20.0, 1.0, 10.0])],
        "G58",
        [("G58", "G54")],
    )


def test_margins_per_wcs_in_program_order(program):
    plan = CoordPopup.auto_probe_plan(_config())

    assert plan["start"] == "G55"
    assert plan["follower"] is None
    assert plan["margins"] == [("G55", [2.0, 20.0, 1.0, 10.0]), ("G54", [0.0, 30.0, 0.0, 40.0])]


def test_leveling_covers_the_machine_box_of_the_start_wcs(program):
    plan = CoordPopup.auto_probe_plan(_config(offsets=(1, 2, 3, 4)))

    # G55 rotated by 90° covers machine X 190 to 199, Y 52 to 70
    assert plan["leveling"] == pytest.approx((191.0, 55.0, 6.0, 11.0))
    # M495 starts the grid there, given in G55
    assert plan["path"] == pytest.approx(CoordPopup.machine_to_wcs(ORIGINS["G55"], 191.0, 55.0))


def test_z_probe_in_the_start_wcs(program):
    assert CoordPopup.auto_probe_plan(_config(zprobe_origin=1))["zprobe"] == (5.0, 5.0)
    assert CoordPopup.auto_probe_plan(_config(zprobe_origin=0))["zprobe"] == (7.0, 6.0)


def test_without_leveling_m495_starts_at_the_start_path_origin(program):
    assert CoordPopup.auto_probe_plan(_config(leveling=False))["path"] == pytest.approx((2.0, 1.0))


def test_probing_start_wcs_stands_for_the_wcs_it_writes(probing_program):
    plan = CoordPopup.auto_probe_plan(_config(zprobe_origin=0, offsets=(1, 2, 3, 4)))

    assert plan["start"] == "G58"
    assert plan["follower"] == "G54"
    assert plan["start_extents"] == [0.0, 30.0, 0.0, 40.0]
    # G54 is scanned once, as G58 with its current origin
    assert plan["margins"] == [("G58", [0.0, 30.0, 0.0, 40.0]), ("G55", [2.0, 20.0, 1.0, 10.0])]
    assert plan["zprobe"] == (5.0, 5.0)
    # G58 at machine 300, 100 without rotation
    assert plan["leveling"] == pytest.approx((301.0, 103.0, 27.0, 33.0))
    assert plan["path"] == pytest.approx((1.0, 3.0))


def test_writing_a_wcs_that_does_not_follow_is_no_probing_start(monkeypatch):
    _program(
        monkeypatch,
        [("G58", None), ("G54", [0.0, 30.0, 0.0, 40.0]), ("G55", [2.0, 20.0, 1.0, 10.0])],
        "G58",
        [("G58", "G55")],
    )
    plan = CoordPopup.auto_probe_plan(_config(zprobe_origin=0))

    assert plan["follower"] is None
    assert plan["start_extents"] is None
    # G55 gets its origin in the job, so it has no scan margin yet
    assert plan["margins"] == [("G54", [0.0, 30.0, 0.0, 40.0])]
    # Z probe and leveling cover G54, the first WCS that cuts at a known origin
    assert plan["leveling"] == pytest.approx((100.0, 50.0, 30.0, 40.0))
    # given in G58 at machine 300, 100
    assert plan["path"] == pytest.approx((-200.0, -50.0))
    assert plan["zprobe"] == pytest.approx((-195.0, -45.0))


def test_commands_for_a_plan(program):
    plan = CoordPopup.auto_probe_plan(_config(zprobe_origin=0, offsets=(1, 2, 3, 4)))
    controller = Controller(CNC(), lambda _line: None, False)
    sent = []
    controller.executeCommand = sent.append

    controller.autoCommand(margin=True, zprobe=True, leveling=True, i=4, j=3, h=5, buffer=True, plan=plan)

    path_x, path_y = round(plan["path"][0], 4), round(plan["path"][1], 4)
    assert "e" not in sent[5].removeprefix("buffer ")
    assert sent[:5] == [
        "buffer G55",
        "buffer M495 X2Y1C20D10",
        "buffer G54",
        "buffer M495 X0Y0C30D40",
        "buffer G55",
    ]
    assert sent[5] == "buffer M495 X%gY%gO%gF%gA6B11I4J3H5\n" % (path_x, path_y, 7 - path_x, 6 - path_y)
    assert len(sent) == 6


def test_margin_alone_sends_no_second_m495(program):
    controller = Controller(CNC(), lambda _line: None, False)
    sent = []
    controller.executeCommand = sent.append

    controller.autoCommand(margin=True, plan=CoordPopup.auto_probe_plan(_config()))

    assert sent == ["G55", "M495 X2Y1C20D10", "G54", "M495 X0Y0C30D40", "G55"]
