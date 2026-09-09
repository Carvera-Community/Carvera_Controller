"""Tests for G-code file pager label and visibility helpers."""

from carveracontroller.ui.GCodePageBar import gcode_page_bar_state


def test_hidden_when_file_fits_on_one_page():
    state = gcode_page_bar_state(1, 1, 41, 10000)
    assert state.visible is False
    assert state.page_label == "1 / 1"
    assert state.range_label == "1–41"


def test_hidden_when_file_is_empty():
    state = gcode_page_bar_state(1, 1, 0, 10000)
    assert state.visible is False
    assert state.page_label == "1 / 1"
    assert state.range_label == ""


def test_first_page_of_multipage_file():
    state = gcode_page_bar_state(1, 3, 25000, 10000)
    assert state.visible is True
    assert state.page_label == "1 / 3"
    assert state.range_label == "1–10000"
    assert state.start == 1
    assert state.end == 10000


def test_middle_page_range():
    state = gcode_page_bar_state(2, 3, 25000, 10000)
    assert state.visible is True
    assert state.page_label == "2 / 3"
    assert state.range_label == "10001–20000"


def test_last_partial_page_range():
    state = gcode_page_bar_state(3, 3, 25000, 10000)
    assert state.visible is True
    assert state.page_label == "3 / 3"
    assert state.range_label == "20001–25000"


def test_exact_page_size_multiple():
    state = gcode_page_bar_state(2, 2, 20000, 10000)
    assert state.visible is True
    assert state.range_label == "10001–20000"


def test_zero_total_pages_is_treated_as_single_page():
    state = gcode_page_bar_state(1, 0, 0, 10000)
    assert state.visible is False
    assert state.page_label == "1 / 1"
