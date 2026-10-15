"""Tests for finding the work coordinate system a program starts in."""

from carveracontroller.Controller import Controller


def program_start_wcs(lines):
    controller = Controller.__new__(Controller)
    return controller.program_start_wcs(lines)


def test_wcs_before_first_move_is_start_wcs():
    assert program_start_wcs(["G90 G21\n", "G55\n", "G0 X10 Y10\n", "G1 X20 F100\n"]) == "G55"


def test_last_wcs_before_first_move_wins():
    assert program_start_wcs(["G54\n", "G56\n", "G0 X0\n"]) == "G56"


def test_wcs_on_the_line_of_the_first_move_applies():
    assert program_start_wcs(["G0 G57 X10\n"]) == "G57"


def test_no_wcs_before_first_move():
    assert program_start_wcs(["G0 X10\n", "G55\n", "G1 X20 F100\n"]) is None


def test_machine_coordinate_move_is_not_the_first_move():
    assert program_start_wcs(["G53 G0 Z-2\n", "G58\n", "G0 X10\n"]) == "G58"


def test_extended_wcs_is_not_g59():
    assert program_start_wcs(["G59.1\n", "G0 X0\n", "G59\n", "G1 X1 F100\n"]) == "G59.1"


def test_comments_are_ignored():
    assert program_start_wcs(["(G55 in a comment)\n", "G54 ; G56\n", "G0 X0\n"]) == "G54"


def test_program_without_wcs():
    assert program_start_wcs(["G90\n", "G0 X0\n", "G1 X1 F100\n"]) is None
