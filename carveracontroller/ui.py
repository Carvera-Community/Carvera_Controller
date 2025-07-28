from kivy.uix.settings import SettingItem
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.textinput import TextInput
from kivy.metrics import dp
import json

from carveracontroller.translation import tr

class SettingGCodeSnippet(SettingItem):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.size_hint_y = None
        self.height = dp(80)

        # Wrapper: ensure the content is centered vertically
        wrapper = AnchorLayout(anchor_y='center', anchor_x='left')

        # And split it horizontally into two parts:
        # 1. Block with preview of the G-code snippet name
        # 2. Button to open the editor popup
        inner = BoxLayout(
            orientation='horizontal',
            spacing=dp(10),
            size_hint=(1, None),
            height=dp(40),
            padding=[dp(10), 0]
        )

        self.preview = Label(
            text=self._get_name(self.value),
            halign='left',
            valign='middle',
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
            obj = json.loads(self.value or '{}')
        except Exception:
            obj = {}

        name = obj.get("name", "")
        gcode = obj.get("gcode", "")

        content = BoxLayout(orientation='vertical', spacing=dp(10), padding=dp(10))

        self.name_input = TextInput(
            text=name,
            multiline=False,
            size_hint_y=None,
            height=dp(40)
        )
        content.add_widget(Label(text=tr._("Name:"), size_hint_y=None, height=dp(20)))
        content.add_widget(self.name_input)

        self.gcode_input = TextInput(
            text=gcode,
            size_hint=(1, 1)
        )
        content.add_widget(Label(text=tr._("G-code:"), size_hint_y=None, height=dp(20)))
        content.add_widget(self.gcode_input)

        btns = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10))
        popup = Popup(
            title=self.title or tr._("Edit command"),
            content=content,
            size_hint=(0.8, 0.8),
            auto_dismiss=False
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
        obj = {
            "name": self.name_input.text.strip(),
            "gcode": self.gcode_input.text.strip()
        }

        new_value = json.dumps(obj)

        self.panel.set_value(self.section, self.key, new_value)

        self.value = new_value
        self.on_value(self, new_value)

        popup.dismiss()

    def on_value(self, instance, value):
        if hasattr(self, 'preview'):
            self.preview.text = self._get_name(value)
