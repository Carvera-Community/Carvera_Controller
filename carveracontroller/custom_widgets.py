import json

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.factory import Factory
from kivy.metrics import dp
from kivy.properties import ListProperty, StringProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.settings import SettingItem
from kivy.uix.textinput import TextInput

from carveracontroller.translation import tr
from carveracontroller.ui.fonts import ARIALUNI


class ScrollingLabel(ScrollView):
    """
    A horizontal ScrollView with a single Label that scrolls right-to-left
    (marquee style) when the text overflows. If text would fit at 80% font size,
    uses that instead of scrolling. Based on https://stackoverflow.com/a/43051460
    """

    text = StringProperty("")
    # Forwarded to the inner label in the kv rule. Kv sets it, so the default is only a fallback.
    font_name = StringProperty(ARIALUNI)
    font_size = StringProperty("18sp")
    color = ListProperty([1, 1, 1, 1])
    effective_font_size = StringProperty("18sp")

    def __init__(self, **kwargs):
        self._marquee_anim = None
        self._marquee_only = False  # skip fit evaluation, go straight to scroll (avoids font flash each cycle)
        super().__init__(**kwargs)

    def _parse_font_size(self, value):
        try:
            if isinstance(value, str):
                return float(value.replace("sp", "").replace("dp", "").strip())
            return float(value)
        except (TypeError, ValueError):
            return 18.0

    def _start_marquee(self, dt=None):
        if not self.ids:
            return
        if self._marquee_only:
            # Already decided we need to scroll; skip fit/shrink to avoid font flash each cycle
            self.effective_font_size = self.font_size
            Clock.schedule_once(self._start_marquee_anim, 0.05)
            return
        # Reset to full font size and re-evaluate after label updates
        self.effective_font_size = self.font_size
        Clock.schedule_once(self._evaluate_fit, 0.1)

    def _evaluate_fit(self, dt=None):
        if not self.ids:
            return
        label = self.ids.scroll_label
        if not label.texture:
            Clock.schedule_once(self._evaluate_fit, 0.05)
            return
        label_width = label.texture_size[0]
        view_width = max(1, self.width)
        if label_width <= view_width:
            self._marquee_only = False
            self._stop_marquee()
            self.scroll_x = 0
            return
        # Try 80% font size to avoid scrolling
        base = self._parse_font_size(self.font_size)
        reduced = base * 0.8
        self.effective_font_size = f"{reduced}sp"
        Clock.schedule_once(self._check_after_shrink, 0.1)

    def _check_after_shrink(self, dt=None):
        if not self.ids:
            return
        label = self.ids.scroll_label
        if not label.texture:
            Clock.schedule_once(self._check_after_shrink, 0.05)
            return
        label_width = label.texture_size[0]
        view_width = max(1, self.width)
        if label_width <= view_width:
            self._marquee_only = False
            self._stop_marquee()
            self.scroll_x = 0
            return
        # Still doesn't fit: restore full size and run marquee; next cycle skip fit eval
        self._marquee_only = True
        self.effective_font_size = self.font_size
        Clock.schedule_once(self._start_marquee_anim, 0.1)

    def _start_marquee_anim(self, dt=None):
        if not self.ids:
            return
        label = self.ids.scroll_label
        if not label.texture:
            Clock.schedule_once(self._start_marquee_anim, 0.05)
            return
        label_width = label.texture_size[0]
        self._stop_marquee()
        self.scroll_x = 0
        duration = 2.0 + (label_width - self.width) * 0.02
        self._marquee_anim = Animation(scroll_x=1, duration=duration)
        self._marquee_anim.bind(on_complete=self._marquee_loop)
        self._marquee_anim.start(self)

    def _marquee_loop(self, anim, widget):
        self.scroll_x = 0
        Clock.schedule_once(self._start_marquee, 0.2)

    def _stop_marquee(self):
        if self._marquee_anim:
            self._marquee_anim.cancel(self)
            self._marquee_anim = None

    def on_font_size(self, instance, value):
        self.effective_font_size = value

    def on_font_name(self, instance, value):
        # A new face changes the text width, so the fit check runs again.
        self._marquee_only = False
        Clock.schedule_once(self._start_marquee, 0.1)

    def on_text(self, instance, value):
        self._marquee_only = False
        Clock.schedule_once(self._start_marquee, 0.1)

    def on_size(self, instance, value):
        self._marquee_only = False
        Clock.schedule_once(self._start_marquee, 0.1)

    def on_touch_down(self, touch):
        return False

    def on_touch_move(self, touch):
        return False

    def on_touch_up(self, touch):
        return False


Factory.register("ScrollingLabel", cls=ScrollingLabel)


class SettingGCodeSnippet(SettingItem):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.size_hint_y = None
        self.height = dp(80)

        # Wrapper: ensure the content is centered vertically
        wrapper = AnchorLayout(anchor_y="center", anchor_x="left")

        # And split it horizontally into two parts:
        # 1. Block with preview of the G-code snippet name
        # 2. Button to open the editor popup
        inner = BoxLayout(
            orientation="horizontal", spacing=dp(10), size_hint=(1, None), height=dp(40), padding=[dp(10), 0]
        )

        self.preview = Label(
            text=self._get_name(self.value),
            halign="left",
            valign="middle",
            size_hint=(1, 1),
            text_size=(None, None),
        )

        btn = Button(text=tr._("Open editor…"), size_hint=(None, 1), width=dp(130))
        btn.bind(on_release=self.open_popup)

        inner.add_widget(self.preview)
        inner.add_widget(btn)
        wrapper.add_widget(inner)
        self.add_widget(wrapper)

    def _get_name(self, value):
        try:
            obj = json.loads(value)
            return obj.get("name", tr._("<unnamed>"))
        except Exception:
            return tr._("<invalid>")

    def _update_text_size(self, instance, width):
        instance.text_size = (width - dp(20), None)

    def _update_height(self, instance, size):
        instance.height = size[1]

    def open_popup(self, *args):
        try:
            obj = json.loads(self.value or "{}")
        except Exception:
            obj = {}

        name = obj.get("name", "")
        gcode = obj.get("gcode", "")

        content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))

        self.name_input = TextInput(text=name, multiline=False, size_hint_y=None, height=dp(40))
        content.add_widget(Label(text=tr._("Name:"), size_hint_y=None, height=dp(20)))
        content.add_widget(self.name_input)

        self.gcode_input = TextInput(text=gcode, size_hint=(1, 1))
        content.add_widget(Label(text=tr._("G-code:"), size_hint_y=None, height=dp(20)))
        content.add_widget(self.gcode_input)

        btns = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10))
        popup = Popup(
            title=self.title or tr._("Edit command"), content=content, size_hint=(0.8, 0.8), auto_dismiss=False
        )

        save_btn = Button(text=tr._("Save"))
        save_btn.bind(on_release=lambda *a: self._save_and_close(popup))

        cancel_btn = Button(text=tr._("Cancel"))
        cancel_btn.bind(on_release=lambda *a: popup.dismiss())

        btns.add_widget(cancel_btn)
        btns.add_widget(save_btn)
        content.add_widget(btns)

        popup.open()
        self._popup = popup

    def _save_and_close(self, popup):
        obj = {"name": self.name_input.text.strip(), "gcode": self.gcode_input.text.strip()}

        new_value = json.dumps(obj)

        self.panel.set_value(self.section, self.key, new_value)

        self.value = new_value
        self.on_value(self, new_value)

        popup.dismiss()

    def on_value(self, instance, value):
        if hasattr(self, "preview"):
            self.preview.text = self._get_name(value)
