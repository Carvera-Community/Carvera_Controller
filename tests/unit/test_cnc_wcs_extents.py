"""
Tests for the work coordinate systems and their feed extents found when parsing a program. As for
the program margins, a feed move counts with the points the parser keeps, the end of a line.
"""

from carveracontroller.CNC import CNC


def _parse(lines):
    cnc = CNC()
    cnc.init()
    for line_no, line in enumerate(lines, start=1):
        cnc.parseLine(line, line_no)
    return cnc


def test_feed_extents_per_wcs_in_program_order():
    extents = _parse(
        [
            "G55",
            "G0 X0 Y0",
            "G1 X10 Y5 F500",
            "G1 X2 Y8",
            "G54",
            "G0 X20 Y20",
            "G1 X30 Y25",
            "G1 X22 Y21",
        ]
    ).wcs_extents

    assert list(extents) == ["G55", "G54"]
    assert extents["G55"] == [2, 10, 5, 8]
    assert extents["G54"] == [22, 30, 21, 25]


def test_rapids_only_list_the_wcs_without_extents():
    cnc = _parse(
        [
            "G59.1",
            "G0 X5 Y5",
        ]
    )

    assert cnc.wcs_extents == {"G59.1": None}


def test_m468_notes_the_wcs_it_writes():
    cnc = _parse(
        [
            "G58",
            "G0 X0 Y0",
            "M468 X0 Y0 Z0 P1 S1",
            "M468 Z0 P0 S1",
            "G54",
            "G1 X10 Y10 F500",
        ]
    )

    assert cnc.wcs_writes == [("G58", "G54")]
    assert cnc.wcs_extents == {"G58": None, "G54": [10, 10, 10, 10]}


def test_m468_that_only_checks_writes_no_wcs():
    cnc = _parse(
        [
            "G58",
            "G0 X0 Y0",
            "M468 X0 Y0 P1 T0.1",
            "M468 X0 Y0 P2 S0",
            "M468 D20 E10 P3 S1",
        ]
    )

    assert cnc.wcs_writes == []


def test_m468_after_feed_moves_is_no_new_origin():
    cnc = _parse(
        [
            "G54",
            "G1 X10 Y10 F500",
            "G58",
            "M468 X0 Y0 Z0 P1 S1",
            "M468 X0 Y0 Z0 P2 S1",
        ]
    )

    # G54 cut already, G55 gets its origin from the probing
    assert cnc.wcs_writes == [("G58", "G55")]


def test_probing_words_are_no_move():
    cnc = _parse(
        [
            "G54",
            "G1 X5 Y5 F500",
            "M466 X40 Y40",
            "M468 X50 Y50 S1",
            "G1 Z-1",
        ]
    )

    assert cnc.wcs_extents == {"G54": [5, 5, 5, 5]}


def test_the_first_wcs_moved_in_is_the_start_wcs():
    cnc = _parse(["G54", "G56", "G53 G0 Z-2", "G0 X0 Y0", "G55", "G1 X1 F100"])

    # the program starts in G56, G54 is replaced before any move and G53 is no move in a WCS
    assert list(cnc.wcs_extents) == ["G56", "G55"]


def test_moves_before_selecting_a_wcs_run_in_the_active_one():
    cnc = _parse(["G0 X0 Y0", "G55", "G1 X1 F100"])

    assert list(cnc.wcs_extents) == [None, "G55"]
