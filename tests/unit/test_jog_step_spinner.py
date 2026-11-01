"""Jog step spinners stay within the key and open a list wide enough to read."""

import pytest
from kivy.metrics import dp
from kivy.uix.widget import Widget

from carveracontroller.ui.JogStepSpinner import JogStepSpinner, _text_size

_STEPS = ["10", "1", "0.1", "0.01", "0.005"]


def test_step_spinner_shrinks_to_a_short_jog_key():
    parent = Widget(size_hint=(None, None), size=(dp(80), dp(28)))
    spinner = JogStepSpinner(text="10", values=_STEPS)
    parent.add_widget(spinner)
    assert spinner.height == pytest.approx(parent.height)

    parent.height = dp(80)
    assert spinner.height == pytest.approx(dp(40))

    parent.height = dp(22)
    assert spinner.height == pytest.approx(dp(22))


def test_step_spinner_stays_at_the_cap_inside_a_tall_key():
    parent = Widget(size_hint=(None, None), size=(dp(90), dp(90)))
    spinner = JogStepSpinner(text="10", values=_STEPS, size_hint=(None, None), width=dp(90))
    parent.add_widget(spinner)
    assert spinner.height == pytest.approx(dp(40))


def test_step_menu_is_wider_than_a_narrow_key():
    spinner = JogStepSpinner(
        text="0.005",
        values=_STEPS,
        size_hint=(None, None),
        size=(dp(28), dp(28)),
    )
    spinner._size_menu()
    dropdown = spinner._dropdown
    text_w, _text_h = _text_size("0.005", dp(14))
    assert dropdown.auto_width is False
    assert dropdown.width > spinner.width
    assert dropdown.width >= text_w + dp(16)


def test_step_menu_stays_at_least_as_wide_as_a_wide_key():
    spinner = JogStepSpinner(
        text="10",
        values=["10", "1"],
        size_hint=(None, None),
        size=(dp(140), dp(40)),
    )
    spinner._size_menu()
    assert spinner._dropdown.width >= spinner.width


def test_step_font_matches_the_numeric_fields():
    parent = Widget(size_hint=(None, None), size=(dp(28), dp(28)))
    spinner = JogStepSpinner(text="0.005", values=_STEPS, size_hint=(None, None), width=dp(28))
    parent.add_widget(spinner)
    assert spinner.font_size == pytest.approx(dp(14))
    assert spinner._dropdown.container.children[0].font_size == pytest.approx(dp(14))
