from types import SimpleNamespace
from unittest.mock import Mock, patch

from carveracontroller.main import Makera, MDITextInput

UP_ARROW_KEY = 273


def _root(widget):
    return SimpleNamespace(
        manual_cmd=widget,
        manual_rv=SimpleNamespace(scroll_y=1, data=[]),
        controller=SimpleNamespace(executeCommand=Mock()),
        refocus_cmd=Mock(),
        mdi_auto_correct_case=True,
    )


def test_send_cmd_records_history_for_the_button_and_the_shortcut():
    widget = MDITextInput()
    root = _root(widget)

    def send():
        Makera.send_cmd(root)

    app = SimpleNamespace(root=SimpleNamespace(send_cmd=send))

    with (
        patch("carveracontroller.main.hide_mdi_intellisense"),
        patch("carveracontroller.main.Clock.schedule_once"),
        patch("carveracontroller.main.update_mdi_intellisense"),
    ):
        widget.text = "G0 X1"
        Makera.send_cmd(root)
        widget.text = "G0 Y2"
        with patch("carveracontroller.main.App.get_running_app", return_value=app):
            widget.send_mdi_command()

        assert widget.past_mdi_commands == ["G0 X1", "G0 Y2"]
        assert widget.active_past_mdi_index == 2
        assert widget.text == ""

        widget.focus = True
        assert widget._handle_navigation_key(UP_ARROW_KEY, []) is True
        assert widget.text == "G0 Y2"
        assert widget._handle_navigation_key(UP_ARROW_KEY, []) is True
        assert widget.text == "G0 X1"


def test_empty_send_does_not_record_history():
    widget = MDITextInput()
    root = _root(widget)
    widget.text = "   "

    with (
        patch("carveracontroller.main.hide_mdi_intellisense"),
        patch("carveracontroller.main.Clock.schedule_once"),
    ):
        Makera.send_cmd(root)

    assert widget.past_mdi_commands == []
    root.controller.executeCommand.assert_not_called()
