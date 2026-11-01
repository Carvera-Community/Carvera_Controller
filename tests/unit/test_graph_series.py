"""Derived monitoring series: spindle speed deviation."""

from carveracontroller.ui.graph_series import format_graph_value, rpm_deviation_percent


def test_graph_values_are_not_written_in_scientific_notation():
    assert format_graph_value(0) == "0"
    assert format_graph_value(500) == "500"
    assert format_graph_value(5e2) == "500"
    assert format_graph_value(10000) == "10000"
    assert format_graph_value(-5.25) == "-5.25"
    assert format_graph_value(42.1) == "42.1"


def test_rpm_deviation_percent_is_signed_against_the_request():
    assert rpm_deviation_percent(9500, 10000) == -5.0
    assert rpm_deviation_percent(11000, 10000) == 10.0


def test_rpm_deviation_is_zero_when_no_speed_was_requested():
    assert rpm_deviation_percent(0, 0) == 0.0
    assert rpm_deviation_percent(12000, 0) == 0.0
