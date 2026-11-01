"""Step-size spinner for the jog pads of the probing modal and CMM workbench."""

from kivy.core.text import Label as CoreLabel
from kivy.metrics import dp
from kivy.uix.spinner import Spinner, SpinnerOption

_MAX_HEIGHT = dp(40)
_FIELD_FONT = dp(14)
_MENU_INSET = dp(36)


def _text_size(text: str, font_size: float) -> tuple[float, float]:
    core = CoreLabel(text=text, font_size=font_size)
    core.refresh()
    texture = core.texture
    if texture is None:
        return 0.0, 0.0
    return float(texture.width), float(texture.height)


class JogStepOption(SpinnerOption):
    """One step size in the opened list, at a readable size."""

    def __init__(self, **kwargs):
        kwargs.setdefault("font_size", _FIELD_FONT)
        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        super().__init__(**kwargs)


class JogStepSpinner(Spinner):
    """Step size that stays within its jog key and opens a readable list."""

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", _MAX_HEIGHT)
        kwargs.setdefault("font_size", _FIELD_FONT)
        kwargs.setdefault("option_cls", JogStepOption)
        super().__init__(**kwargs)
        self._height_parent = None
        self.bind(parent=self._watch_parent, size=self._fit)
        if self.parent is not None:
            self._watch_parent(self, self.parent)
        else:
            self._fit()

    def _watch_parent(self, _instance, parent):
        previous = self._height_parent
        if previous is not None:
            previous.unbind(height=self._fit)
        self._height_parent = parent
        if parent is None:
            return
        parent.bind(height=self._fit)
        self._fit()

    def _fit(self, *_args):
        parent = self.parent
        if parent is not None and parent.height > 1:
            fitted = min(_MAX_HEIGHT, float(parent.height))
            if abs(float(self.height) - fitted) > 0.5:
                self.height = fitted

    def on_is_open(self, instance, value):
        if value:
            self._size_menu()
        super().on_is_open(instance, value)

    def _size_menu(self):
        dropdown = self._dropdown
        if dropdown is None:
            return
        # auto_width copies the key, which is too narrow for 0.005.
        dropdown.auto_width = False
        dropdown.width = max(float(self.width), self._menu_width())

    def _menu_width(self) -> float:
        widest = 0.0
        for value in self.values:
            text_w, _text_h = _text_size(str(value), _FIELD_FONT)
            widest = max(widest, text_w)
        return widest + _MENU_INSET
