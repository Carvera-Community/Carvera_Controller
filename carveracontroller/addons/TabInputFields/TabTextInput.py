# TabTextInput.py
from kivy.uix.textinput import TextInput
from kivy.clock import Clock
from kivy.uix.scrollview import ScrollView

class TabTextInput(TextInput):
    dropdown = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if hasattr(self, "_keyboard_suppress") and 9 in self._keyboard_suppress:
            self._keyboard_suppress.remove(9)

        self.bind(focus=self.on_focus_change)

    def on_focus_change(self, instance, value):
        if value: 
            Clock.schedule_once(lambda dt: self.select_all(), 0)
            Clock.schedule_once(lambda dt: self.scroll_to_self(), 0)

    def scroll_to_self(self):
        parent = self.parent
        while parent:
            if isinstance(parent, ScrollView):
                parent.scroll_to(self, padding=10)
                break
            parent = parent.parent

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self.focus = True
            if self.dropdown:
                self.dropdown.open(self)
                return True
        return super().on_touch_down(touch)

    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        key, key_str = keycode

        if key == 9 and "shift" in modifiers:
            prev_widget = self.get_focus_previous()
            if prev_widget:
                prev_widget.focus = True
                Clock.schedule_once(lambda dt: prev_widget.select_all(), 0)
            return True

        if key in (9, 13, 271):
            next_widget = self.get_focus_next()
            if next_widget:
                next_widget.focus = True
                Clock.schedule_once(lambda dt, w=next_widget: w.select_all(), 0)
            return True

        return super().keyboard_on_key_down(window, keycode, text, modifiers)
