"""Tests for the G-code helpers exposed by the CNC module."""

from carveracontroller.CNC import CNC, LASER_TOOL_NUMBER, detect_document_unit, unit_scale_to_mm


class TestDocumentUnit:
    def test_detects_g21_as_mm(self):
        assert detect_document_unit(["G90 G94\n", "G17\n", "G21\n", "G0 X0\n"]) == "mm"

    def test_detects_g20_as_inches(self):
        assert detect_document_unit(["G90\n", "G20\n", "G0 X1\n"]) == "in"

    def test_defaults_to_mm_when_absent(self):
        assert detect_document_unit(["G90 G94\n", "G0 X10\n"]) == "mm"

    def test_ignores_unit_command_inside_paren_comment(self):
        assert detect_document_unit(["(G20 inches)\n", "G21\n", "G0 X0\n"]) == "mm"

    def test_ignores_unit_command_inside_semicolon_comment(self):
        assert detect_document_unit(["; G20\n", "G21\n"]) == "mm"

    def test_accepts_lowercase_and_leading_zeros(self):
        assert detect_document_unit(["g020\n"]) == "in"
        assert detect_document_unit(["g021\n"]) == "mm"

    def test_unit_scale_to_mm(self):
        assert unit_scale_to_mm("mm") == 1.0
        assert unit_scale_to_mm("in") == 25.4
        assert unit_scale_to_mm("unknown") == 1.0


class TestLaserModalS:
    def test_m321_clears_mill_rpm_so_g1_is_travel_until_laser_s(self):
        cnc = CNC()
        lines = [
            "G90 G21",
            "G0 X0 Y0 Z0",
            "S12000 M3",
            "G1 X1 Y0 F500",
            "M321",
            "G1 X2 Y0 F100",
            "G1 X3 Y0 S0.03 F100",
            "G1 X4 Y0",
            "G1 S0",
            "G1 X5 Y0",
        ]
        for i, line in enumerate(lines, 1):
            cnc.parseLine(line, i)

        by_x = {round(p[0], 3): p for p in cnc.coordinates}
        mill = by_x[1.0]
        assert mill[4] == 1
        assert mill[6] != LASER_TOOL_NUMBER
        assert mill[8] == 12000.0

        travel = by_x[2.0]
        assert travel[4] == 0
        assert travel[6] == LASER_TOOL_NUMBER
        assert travel[8] == 0.0

        burn = by_x[3.0]
        assert burn[4] == 1
        assert burn[6] == LASER_TOOL_NUMBER
        assert burn[8] == 0.03

        outline = by_x[4.0]
        assert outline[4] == 1
        assert outline[8] == 0.03

        off = by_x[5.0]
        assert off[4] == 0
        assert off[8] == 0.0


def _parse_lines(cnc, lines):
    for i, line in enumerate(lines, 1):
        cnc.parseLine(line, i)


class TestOffAxisYCounts:
    def test_wrapping_g1_xa_at_y0_is_on_axis(self):
        cnc = CNC()
        _parse_lines(
            cnc,
            [
                "G90 G21",
                "G0 X0 Y0 Z5",
                "G1 Z1 F200",
                "G1 X10 A90",
                "G1 X20 A180",
                "G1 X30 A270",
            ],
        )
        assert cnc.has_4axis
        assert cnc.feed_move_count >= 3
        assert cnc.off_axis_y_count == 0
        assert not cnc.has_off_axis_y

    def test_g0_y_is_ignored(self):
        cnc = CNC()
        _parse_lines(
            cnc,
            [
                "G90 G21",
                "G0 X0 Y0 Z5 A0",
                "G0 Y50",
                "G0 Y0",
                "G1 X10 A90 F200",
            ],
        )
        assert cnc.has_4axis
        assert cnc.feed_move_count >= 1
        assert cnc.off_axis_y_count == 0

    def test_index_xy_after_a_counts_off_axis(self):
        cnc = CNC()
        _parse_lines(
            cnc,
            [
                "G90 G21",
                "G0 X0 Y0 Z5 A0",
                "G1 A90 F200",
                "G1 X10 Y20",
                "G1 X0 Y0",
            ],
        )
        assert cnc.has_4axis
        assert cnc.feed_move_count >= 2
        assert cnc.off_axis_y_count >= 1
        assert cnc.has_off_axis_y

    def test_three_axis_y_does_not_count(self):
        cnc = CNC()
        _parse_lines(
            cnc,
            [
                "G90 G21",
                "G0 X0 Y0 Z5",
                "G1 X10 Y20 F200",
            ],
        )
        assert not cnc.has_4axis
        assert cnc.feed_move_count == 0
        assert cnc.off_axis_y_count == 0
        assert not cnc.has_off_axis_y


def test_has_off_axis_y_ignores_outliers():
    cnc = CNC()
    cnc.feed_move_count = 100
    cnc.off_axis_y_count = 0
    assert not cnc.has_off_axis_y
    cnc.off_axis_y_count = 5
    assert not cnc.has_off_axis_y
    cnc.off_axis_y_count = 6
    assert cnc.has_off_axis_y
    cnc.feed_move_count = 95
    cnc.off_axis_y_count = 4
    assert not cnc.has_off_axis_y
    cnc.feed_move_count = 50
    cnc.off_axis_y_count = 25
    assert cnc.has_off_axis_y
