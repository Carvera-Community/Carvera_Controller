"""Jog keys whose caption and face can follow the jogging colors.

``JogAxisButton`` is the plain key. ``JogAxisTipButton`` is the same key with
an axis-motion tooltip; the control page uses it for X, Y, and A.
"""

from kivy.properties import StringProperty
from kivy.uix.button import Button

from carveracontroller.addons.tooltips.Tooltips import ToolTipButton
from carveracontroller.ui.theme import get_theme, watch_theme
from carveracontroller.ui.themes import jog_axis_markup


def _show_jog_axis_caption(widget, caption: str, theme) -> None:
    """Show ``caption`` on ``widget``, coloring the letter and sign when asked.

    The colors only show while the key is enabled. A disabled key keeps the
    plain disabled text color. A pressed key uses the "pressed" colors.
    """
    if widget.disabled:
        text, markup = caption, False
    else:
        text, markup = jog_axis_markup(caption, theme, widget.state)
    if markup:
        widget.markup = True
        widget.text = text
        return
    widget.text = text
    widget.markup = False


def _refresh_jog_axis_label(widget, *_args) -> None:
    _show_jog_axis_caption(widget, widget.axis_label, get_theme())


def _bind_jog_axis_label(widget) -> None:
    widget.bind(
        axis_label=_refresh_jog_axis_label,
        disabled=_refresh_jog_axis_label,
        state=_refresh_jog_axis_label,
    )
    watch_theme(lambda _theme: _refresh_jog_axis_label(widget))


class JogAxisButton(Button):
    """Jog key. ``axis_label`` is the caption. With custom jogging colors on, the letter, the sign and the key background are colored."""

    axis_label = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        _bind_jog_axis_label(self)


class JogAxisTipButton(ToolTipButton):
    """Jog key that can show an axis-motion tooltip."""

    axis_label = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        _bind_jog_axis_label(self)
