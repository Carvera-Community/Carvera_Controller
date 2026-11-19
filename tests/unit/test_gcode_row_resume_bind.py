"""Recycled GCode rows must drop resume-line observers by uid."""

from types import SimpleNamespace

import pytest
from kivy.app import App
from kivy.properties import BooleanProperty, ObjectProperty, StringProperty
from kivy.uix.widget import Widget

from carveracontroller.main import GCodeRow


class _HostApp(App):
    theme = ObjectProperty(None, allownone=True)

    def load_kv(self, filename=None):
        return False

    def build(self):
        return Widget()


class _StartLine(Widget):
    text = StringProperty("")


class _StartCheck(Widget):
    active = BooleanProperty(False)


@pytest.fixture
def coord_app():
    app = App.get_running_app() or _HostApp()
    previous_root = app.root
    txt = _StartLine()
    cbx = _StartCheck()
    app.root = SimpleNamespace(coord_popup=SimpleNamespace(txt_startline=txt, cbx_startline=cbx))
    yield app
    app.root = previous_root


def test_refresh_twice_leaves_one_resume_observer(coord_app):
    row = GCodeRow()
    calls = []
    original = row._update_is_resume_line

    def wrapped(*args):
        calls.append(args)
        return original(*args)

    row._update_is_resume_line = wrapped
    # A false uid must not be passed to unbind_uid (it raises ValueError).
    row._resume_bind_uids = [0, None]
    row.refresh_view_attrs(None, 0, {"line_no": 4, "text": "G1 X"})
    assert row._resume_bind_uids[0]
    assert row._resume_bind_uids[1]

    row.refresh_view_attrs(None, 0, {"line_no": 4, "text": "G1 X"})
    row.refresh_view_attrs(None, 1, {"line_no": 4, "text": "G1 Y"})

    calls.clear()
    coord_app.root.coord_popup.txt_startline.text = "4"
    assert len(calls) == 1
    calls.clear()
    coord_app.root.coord_popup.cbx_startline.active = True
    assert len(calls) == 1

    row.refresh_view_attrs(None, 2, {"line_no": 5, "text": "G0"})
    calls.clear()
    coord_app.root.coord_popup.txt_startline.text = "5"
    assert len(calls) == 1
