"""Jog keys stay square when the pad itself is not."""

import pytest
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget

from carveracontroller.ui.SquareGrid import SquareGrid


def _packed(cols, rows, size, spacing=0, padding=0):
    grid = SquareGrid(cols=cols, rows=rows, spacing=spacing, padding=padding, size=size, pos=(0, 0))
    children = [Widget() for _ in range(cols * rows)]
    for child in children:
        grid.add_widget(child)
    grid.do_layout()
    return grid, children


def test_cells_are_square_and_top_row_is_first():
    _ignored, children = _packed(3, 3, (310, 400), spacing=10, padding=20)
    side = min((310 - 40 - 20) / 3, (400 - 40 - 20) / 3)
    assert side == pytest.approx(250 / 3)
    for child in children:
        assert child.width == pytest.approx(side)
        assert child.height == pytest.approx(child.width)
    assert children[0].y > children[6].y
    assert children[0].x < children[1].x
    assert children[3].y < children[0].y


def test_two_column_pad_matches_three_column_button_size():
    square = (300, 300)
    _xy, xy_keys = _packed(3, 3, square)
    _az, az_keys = _packed(2, 3, square)
    assert xy_keys[0].width == pytest.approx(100)
    assert az_keys[0].width == pytest.approx(xy_keys[0].width)
    assert az_keys[0].height == pytest.approx(az_keys[0].width)
    # The narrower group is centered, not stretched across the pad.
    assert az_keys[0].x == pytest.approx(50)
    assert az_keys[1].x == pytest.approx(150)


def test_grid_stays_inside_a_moved_float_parent():
    host = FloatLayout(size=(400, 500), pos=(30, 80))
    grid = SquareGrid(cols=3, rows=3, spacing=8, padding=20, size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
    button = Button(text="X+")
    grid.add_widget(button)
    host.add_widget(grid)
    host.do_layout()
    grid.do_layout()
    assert tuple(grid.pos) == pytest.approx((30, 80))
    assert tuple(grid.size) == pytest.approx((400, 500))
    assert button.width == pytest.approx(button.height)
    assert button.x >= host.x
    assert button.y >= host.y
    assert button.right <= host.right
    assert button.top <= host.top


def test_tall_pad_keeps_two_and_three_column_keys_equal():
    tall = (300, 450)
    _xy, xy_keys = _packed(3, 3, tall)
    _az, az_keys = _packed(2, 3, tall)
    assert xy_keys[0].width == pytest.approx(100)
    assert az_keys[0].width == pytest.approx(xy_keys[0].width)
    assert az_keys[0].height == pytest.approx(az_keys[0].width)


def test_wide_short_pad_sizes_from_height():
    _ignored, children = _packed(3, 3, (480, 150), spacing=8, padding=4)
    side = ((150 - 8) - 16) / 3
    assert children[0].width == pytest.approx(side)
    assert children[0].height == pytest.approx(side)
    group_width = side * 3 + 16
    assert children[0].x == pytest.approx((480 - group_width) / 2)
