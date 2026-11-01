"""
Tests for what M495 does before a program that moves in several work coordinate systems: a scan
margin around the feed moves of each WCS in program order, Z probe and leveling in the start WCS
or, when it has no feed moves, in the first WCS that cuts, and a start WCS that only probes the part
for the first WCS that cuts after it, which Z probe and leveling then run in.
"""

from unittest.mock import Mock

import pytest

from carveracontroller.CNC import CNC
from carveracontroller.Controller import Controller

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


def _controller(monkeypatch, wcs_extents, writes=()):
    """
    A controller for a parsed program with these WCS extents and M468 writes (wcs, written wcs), the
    origins in ORIGINS read with "get wcs" and G59 active.
    """
    cnc = CNC()
    cnc.init()
    cnc.wcs_extents = dict(wcs_extents)
    cnc.wcs_writes = list(writes)
    controller = Controller(cnc, lambda _line: None, False)
    controller.wcs_table = {name: [x, y, 0, 0, 0, rotation] for name, (x, y, rotation) in ORIGINS.items()}
    controller.executeCommand = Mock()
    monkeypatch.setitem(CNC.vars, "active_coord_system", CNC.wcs_names.index("G59"))
    return controller


def _sent(controller):
    return [call.args[0] for call in controller.executeCommand.call_args_list]


@pytest.fixture
def program(monkeypatch):
    """A program that starts in G55, rotated by 90°, and then moves in G54."""
    return _controller(monkeypatch, {"G55": [2.0, 20.0, 1.0, 10.0], "G54": [0.0, 30.0, 0.0, 40.0]})


def test_rotary_jobs_have_no_plan(program):
    program.cnc.has_4axis = True

    assert program.autoProbePlan(_config()) is None


def test_margins_per_wcs_in_program_order(program):
    plan = program.autoProbePlan(_config())

    assert plan["start"] == "G55"
    assert plan["probe_wcs"] == "G55"
    assert plan["follower"] is None
    assert plan["margins"] == [("G55", [2.0, 20.0, 1.0, 10.0]), ("G54", [0.0, 30.0, 0.0, 40.0])]


def test_leveling_covers_the_machine_box_of_the_start_wcs(program):
    plan = program.autoProbePlan(_config(offsets=(1, 2, 3, 4)))

    # G55 rotated by 90° covers machine X 190 to 199, Y 52 to 70
    assert plan["leveling"] == pytest.approx((191.0, 55.0, 6.0, 11.0))
    # M495 starts the grid there, given in G55
    assert plan["path"] == pytest.approx(CNC.machineToWCS(ORIGINS["G55"], 191.0, 55.0))


def test_z_probe_in_the_start_wcs(program):
    assert program.autoProbePlan(_config(zprobe_origin=1))["zprobe"] == (5.0, 5.0)
    assert program.autoProbePlan(_config(zprobe_origin=0))["zprobe"] == (7.0, 6.0)


def test_outside_is_checked_against_the_start_area_in_machine_coordinates(program, monkeypatch):
    # over the G54 part at machine X 100 to 130, Y 50 to 90, which the program cuts later
    monkeypatch.setitem(CNC.vars, "mx", 110.0)
    monkeypatch.setitem(CNC.vars, "my", 60.0)
    assert program.autoProbePlan(_config())["outside"] is True

    # over the G55 area, rotated by 90° at machine X 190 to 199, Y 52 to 70
    monkeypatch.setitem(CNC.vars, "mx", 195.0)
    assert program.autoProbePlan(_config())["outside"] is False


def test_without_leveling_m495_starts_at_the_start_path_origin(program):
    assert program.autoProbePlan(_config(leveling=False))["path"] == pytest.approx((2.0, 1.0))


def test_probing_start_wcs_stands_for_the_wcs_it_writes(monkeypatch):
    # G58 only probes the part and writes G54 with M468, G54 and then G55 cut
    controller = _controller(
        monkeypatch,
        {"G58": None, "G54": [0.0, 30.0, 0.0, 40.0], "G55": [2.0, 20.0, 1.0, 10.0]},
        [("G58", "G54")],
    )
    plan = controller.autoProbePlan(_config(zprobe_origin=0, offsets=(1, 2, 3, 4)))

    assert plan["start"] == "G58"
    assert plan["follower"] == "G54"
    assert plan["start_extents"] == [0.0, 30.0, 0.0, 40.0]
    # G54 is scanned once, as G58 with its current origin
    assert plan["margins"] == [("G58", [0.0, 30.0, 0.0, 40.0]), ("G55", [2.0, 20.0, 1.0, 10.0])]
    # G58 at machine 300, 100 without rotation
    assert plan["leveling"] == pytest.approx((301.0, 103.0, 27.0, 33.0))
    # the Z probe is for G54, which cuts: given in G54 at machine 100, 50
    assert plan["probe_wcs"] == "G54"
    assert plan["zprobe"] == pytest.approx((205.0, 55.0))
    assert plan["path"] == pytest.approx((201.0, 53.0))


def test_wcs_without_feed_moves_between_the_probing_start_and_its_follower(monkeypatch):
    # G57 only moves between G58, which probes the part and writes G54, and G54
    controller = _controller(
        monkeypatch,
        {"G58": None, "G57": None, "G54": [0.0, 30.0, 0.0, 40.0]},
        [("G58", "G54")],
    )
    plan = controller.autoProbePlan(_config(zprobe_origin=0, leveling=False))

    assert plan["follower"] == "G54"
    assert plan["margins"] == [("G58", [0.0, 30.0, 0.0, 40.0])]

    controller.autoCommand(margin=True, zprobe=True, buffer=True, plan=plan)

    # the scan margin in G58 around the area, Z probe in G54 at the same machine point, then back
    assert _sent(controller) == [
        "buffer G58",
        "buffer M495 X0Y0C30D40",
        "buffer G54",
        "buffer M495 X200Y50O5F5\n",
        "buffer G58",
    ]


def test_probing_start_probes_itself_while_the_follower_origin_is_unknown(monkeypatch):
    # G58 writes G56, which "get wcs" has not read yet
    controller = _controller(monkeypatch, {"G58": None, "G56": [0.0, 30.0, 0.0, 40.0]}, [("G58", "G56")])
    plan = controller.autoProbePlan(_config(zprobe_origin=0, leveling=False))

    assert plan["follower"] == "G56"
    assert plan["probe_wcs"] == "G58"
    assert plan["zprobe"] == (5.0, 5.0)


def test_writing_a_wcs_that_does_not_follow_is_no_probing_start(monkeypatch):
    controller = _controller(
        monkeypatch,
        {"G58": None, "G54": [0.0, 30.0, 0.0, 40.0], "G55": [2.0, 20.0, 1.0, 10.0]},
        [("G58", "G55")],
    )
    plan = controller.autoProbePlan(_config(zprobe_origin=0))

    assert plan["follower"] is None
    assert plan["start_extents"] is None
    # G55 gets its origin in the job, so it has no scan margin yet
    assert plan["margins"] == [("G54", [0.0, 30.0, 0.0, 40.0])]
    # Z probe and leveling run in G54, the first WCS that cuts at a known origin
    assert plan["probe_wcs"] == "G54"
    assert plan["leveling"] == pytest.approx((100.0, 50.0, 30.0, 40.0))
    # given in G54
    assert plan["path"] == pytest.approx((0.0, 0.0))
    assert plan["zprobe"] == pytest.approx((5.0, 5.0))


def test_probing_in_the_first_wcs_that_cuts_returns_to_the_start_wcs(monkeypatch):
    # G58 moves without cutting, G54 cuts first
    controller = _controller(monkeypatch, {"G58": None, "G54": [0.0, 30.0, 0.0, 40.0]})
    plan = controller.autoProbePlan(_config(zprobe_origin=0, leveling=False))

    controller.autoCommand(margin=True, zprobe=True, buffer=True, plan=plan)

    # the Z probe is stored in G54, the job then starts in G58
    assert _sent(controller) == [
        "buffer G54",
        "buffer M495 X0Y0C30D40",
        "buffer G54",
        "buffer M495 X0Y0O5F5\n",
        "buffer G58",
    ]


def test_commands_for_a_plan(program):
    plan = program.autoProbePlan(_config(zprobe_origin=0, offsets=(1, 2, 3, 4)))

    program.autoCommand(zprobe=True, leveling=True, i=4, j=3, h=5, buffer=True, plan=plan)

    # M495 runs in the active WCS, so the plan selects its start WCS also without scan margin
    path_x, path_y = round(plan["path"][0], 4), round(plan["path"][1], 4)
    sent = _sent(program)
    assert sent == [
        "buffer G55",
        "buffer M495 X%gY%gO%gF%gA6B11I4J3H5\n" % (path_x, path_y, 7 - path_x, 6 - path_y),
    ]
    assert "e" not in sent[1].removeprefix("buffer ")


def test_a_plan_selects_its_start_wcs_once(program):
    program.autoCommand(buffer=True, plan=program.autoProbePlan(_config()))

    assert _sent(program) == ["buffer G55"]


def test_margin_alone_sends_no_second_m495(program):
    program.autoCommand(margin=True, buffer=True, plan=program.autoProbePlan(_config()))

    assert _sent(program) == [
        "buffer G55",
        "buffer M495 X2Y1C20D10",
        "buffer G54",
        "buffer M495 X0Y0C30D40",
        "buffer G55",
    ]


def test_margin_button_scans_the_area_of_the_probe_wcs(program):
    # sent directly, a second M495 or WCS change would cut into the first
    program.autoCommand(margin=True, plan=program.autoProbePlan(_config()))

    assert _sent(program) == ["G55", "M495 X2Y1C20D10"]


def test_margin_button_of_a_probing_start_scans_in_the_wcs_it_writes(monkeypatch):
    # G58 at machine 300, 100 probes the part and writes G54, at machine 100, 50 before the job
    controller = _controller(monkeypatch, {"G58": None, "G54": [0.0, 30.0, 0.0, 40.0]}, [("G58", "G54")])

    controller.autoCommand(margin=True, plan=controller.autoProbePlan(_config()))

    # the area where G58 places it, given in G54
    assert _sent(controller) == ["G54", "M495 X200Y50C230D90"]


def test_z_probe_and_leveling_buttons_stay_in_the_probe_wcs(monkeypatch):
    # G58 probes the part and writes G54, which cuts
    controller = _controller(monkeypatch, {"G58": None, "G54": [0.0, 30.0, 0.0, 40.0]}, [("G58", "G54")])
    plan = controller.autoProbePlan(_config(zprobe_origin=0, offsets=(1, 2, 3, 4)))

    controller.autoCommand(zprobe=True, leveling=True, i=4, j=3, h=5, plan=plan)

    # no G58 after it, which would make M495 store the Z probe there while it still runs
    assert _sent(controller) == ["G54", "M495 X201Y53O4F2A27B33I4J3H5\n"]


def test_goto_path_origin_of_the_start_area_in_the_active_wcs(program, monkeypatch):
    for key, value in {"wcox": 10.0, "wcoy": 20.0, "rotation_angle": 0.0, "worksize_x": 360, "worksize_y": 240}.items():
        monkeypatch.setitem(CNC.vars, key, value)

    program.gotoPathOrigin()

    # G55 rotated by 90° has its path origin at machine 199, 52, G59 is active at 10, 20
    assert _sent(program) == ["M496.5 X189Y32\n"]
