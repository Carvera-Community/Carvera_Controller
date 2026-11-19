"""PopupActionButton must not outlive the container it was removed from.

The file browser rebuilds its footer on every machine state change. If removed
buttons stay referenced (e.g. via ``app.theme`` bindings) they pile up, each
one still reacting to theme changes and adding to GC work.
"""

import gc
import weakref
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from kivy.app import App
from kivy.lang import Builder
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from carveracontroller.ui.common.action_button import PopupActionButton
from carveracontroller.ui.file_browser.FileBrowserPopup import FileBrowserPopup
from carveracontroller.ui.theme import Theme

KV_PATH = Path(__file__).resolve().parents[2] / "carveracontroller" / "addons" / "tooltips" / "Tooltips.kv"


class _ThemeApp(App):
    theme = ObjectProperty(None, allownone=True)
    show_tooltips = BooleanProperty(False)
    tooltip_delay = NumericProperty(0)

    def load_kv(self, filename=None):
        return False

    def build(self):
        return Widget()


@pytest.fixture
def themed_app():
    app = App.get_running_app() or _ThemeApp()
    path = str(KV_PATH)
    if path not in Builder.files:
        Builder.load_file(path)
    original_theme = getattr(app, "theme", None)
    app.theme = Theme()
    yield app
    app.theme = original_theme


def _make_button():
    return PopupActionButton(btn_text="x", flat=True)


def test_removed_buttons_are_collected(themed_app):
    bar = BoxLayout()
    refs = []
    for _ in range(5):
        btn = _make_button()
        refs.append(weakref.ref(btn))
        bar.add_widget(btn)
    del btn
    bar.clear_widgets()
    gc.collect()
    assert [r() for r in refs] == [None] * 5


def test_removed_button_stops_watching_theme(themed_app):
    bar = BoxLayout()
    btn = _make_button()
    bar.add_widget(btn)
    assert btn._watched_theme is themed_app.theme
    bar.remove_widget(btn)
    assert btn._watched_theme is None
    themed_app.theme.revision += 1  # must not touch the detached button


def test_readded_button_follows_theme_again(themed_app):
    bar = BoxLayout()
    btn = _make_button()
    bar.add_widget(btn)
    bar.remove_widget(btn)
    bar.add_widget(btn)
    assert btn._watched_theme is themed_app.theme


def test_file_browser_unbinds_app_state_when_dismissed():
    """A closed file browser must not rebuild its footer on every jog state flip."""
    calls = []
    fake_app = SimpleNamespace(unbind=lambda **kw: calls.append(sorted(kw)))
    stub = SimpleNamespace(
        _bound_app=True,
        _on_job_changed=lambda *a: None,
        _on_app_state=lambda *a: None,
    )
    with patch("carveracontroller.ui.file_browser.FileBrowserPopup.App.get_running_app", return_value=fake_app):
        FileBrowserPopup._unbind_app(stub)
        FileBrowserPopup._unbind_app(stub)  # idempotent
    assert stub._bound_app is False
    assert calls == [["selected_local_filename", "selected_remote_filename", "state"]]
