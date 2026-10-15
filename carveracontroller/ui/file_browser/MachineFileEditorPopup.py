"""Simple editor for G-code files stored on the machine."""

from __future__ import annotations

from kivy.app import App
from kivy.clock import Clock
from kivy.factory import Factory
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.modalview import ModalView


class MachineFileEditorPopup(ModalView):
    filename = StringProperty("")
    content_text = StringProperty("")

    def open_editor(self, filename: str, content: str) -> None:
        self.filename = filename
        self.content_text = content
        self.open()

    def on_open(self) -> None:
        super().on_open()
        if "ti_filename" in self.ids:
            self.ids.ti_filename.text = self.filename
        ti = self.ids.get("ti_content")
        scroll = self.ids.get("content_scroll")
        if ti is not None:
            ti.unbind(text=self._sync_content_height)
            ti.text = self.content_text
            ti.bind(text=self._sync_content_height)
        if scroll is not None:
            scroll.unbind(size=self._sync_content_height)
            scroll.bind(size=self._sync_content_height)
        Clock.schedule_once(lambda _dt: self._sync_content_height(), 0)

    def _sync_content_height(self, *_args) -> None:
        ti = self.ids.get("ti_content")
        scroll = self.ids.get("content_scroll")
        if ti is None or scroll is None:
            return
        min_height = max(ti.minimum_height, scroll.height, dp(200))
        if ti.height != min_height:
            ti.height = min_height

    def _current_content(self) -> str:
        if "ti_content" in self.ids:
            return self.ids.ti_content.text
        return self.content_text

    def dismiss(self, *args, **kwargs):
        ti = self.ids.get("ti_content")
        scroll = self.ids.get("content_scroll")
        if ti is not None:
            ti.unbind(text=self._sync_content_height)
        if scroll is not None:
            scroll.unbind(size=self._sync_content_height)
        return super().dismiss(*args, **kwargs)

    def cancel(self) -> None:
        self.dismiss()

    def save(self) -> None:
        app = App.get_running_app()
        root = getattr(app, "root", None)
        if root is None:
            return
        filename = self.ids.ti_filename.text if "ti_filename" in self.ids else self.filename
        content = self._current_content()
        root.save_machine_file_editor(filename, content)


if "MachineFileEditorPopup" not in Factory.classes:
    Factory.register("MachineFileEditorPopup", cls=MachineFileEditorPopup)
