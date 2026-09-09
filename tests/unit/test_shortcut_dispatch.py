from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from kivy.uix.modalview import ModalView

from carveracontroller.addons.cmm_workbench.ui.CMMWorkbenchPopup import JogCMMWorkbenchPopup
from carveracontroller.addons.keyboard_shortcuts.bindings import KeyChord, ShortcutBindings
from carveracontroller.addons.keyboard_shortcuts.manager import ShortcutManager
from carveracontroller.main import Makera


def _root():
    root = SimpleNamespace()
    root.controller = SimpleNamespace(stopContinuousJog=Mock())
    root.keyboard_jog_control = True
    root.is_jogging_enabled = Mock(return_value=True)
    root.perform_keyboard_jog = Mock()
    root.open_online_docs = Mock()
    root.open_start_job_popup = Mock()
    root.open_file_browser = Mock(return_value=True)
    root.open_mdi = Mock()
    root.toggle_keyboard_jog_control = Mock(return_value=True)
    root._is_popup_open = Mock(return_value=False)
    root.manual_cmd = SimpleNamespace(focus=False, hint_text="")
    root.config_popup = SimpleNamespace(open=Mock())
    root.can_send_mdi_command = Mock(return_value=True)
    return root


def _manager(root=None):
    manager = ShortcutManager(root or _root())
    manager.bindings = ShortcutBindings()
    manager._text_input_has_focus = Mock(return_value=False)
    return manager


def test_global_documentation_shortcut_is_dispatched_and_consumed():
    manager = _manager()
    assert manager.on_key_down(None, 282, 0, "", []) is True
    manager.root.open_online_docs.assert_called_once_with()


def test_held_global_shortcut_only_dispatches_once_until_key_up():
    manager = _manager()

    assert manager.on_key_down(None, 282, 0, "", []) is True
    assert manager.on_key_down(None, 282, 0, "", []) is True
    manager.root.open_online_docs.assert_called_once_with()

    assert manager.on_key_up(None, 282) is True
    assert manager.on_key_down(None, 282, 0, "", []) is True
    assert manager.root.open_online_docs.call_count == 2


def test_global_action_stops_active_keyboard_jog():
    manager = _manager()
    manager.on_key_down(None, 275, 0, "", [])

    assert manager.on_key_down(None, 282, 0, "", []) is True

    manager.root.controller.stopContinuousJog.assert_called_once_with()
    manager.root.open_online_docs.assert_called_once_with()


def test_global_settings_and_mdi_shortcuts_dispatch_when_available():
    manager = _manager()

    assert manager.on_key_down(None, 44, 54, ",", ["ctrl"]) is True
    manager.root.config_popup.open.assert_called_once_with()
    assert manager.on_key_up(None, 44) is True

    assert manager.on_key_down(None, ord("m"), 16, "m", ["ctrl"]) is True
    manager.root.open_mdi.assert_called_once_with()


def test_file_browser_and_keyboard_jog_toggle_shortcuts_dispatch():
    manager = _manager()

    assert manager.on_key_down(None, ord("o"), 18, "o", ["ctrl"]) is True
    manager.root.open_file_browser.assert_called_once_with()
    assert manager.on_key_up(None, ord("o")) is True

    assert manager.on_key_down(None, ord("j"), 13, "j", ["ctrl"]) is True
    manager.root.toggle_keyboard_jog_control.assert_called_once_with()


def test_file_browser_shortcut_propagates_when_browser_is_unavailable():
    manager = _manager()
    manager.root.open_file_browser.return_value = False

    assert manager.on_key_down(None, ord("o"), 18, "o", ["ctrl"]) is False


def test_keyboard_jog_toggle_shortcut_propagates_when_control_is_unavailable():
    manager = _manager()
    manager.root.toggle_keyboard_jog_control.return_value = False

    assert manager.on_key_down(None, ord("j"), 13, "j", ["ctrl"]) is False


def test_unmodified_printable_global_shortcut_is_suppressed_while_typing():
    manager = _manager()
    manager.bindings.assign("open_start_job", KeyChord("s"))
    manager._text_input_has_focus.return_value = True

    assert manager.on_key_down(None, ord("s"), 0, "s", []) is False
    manager.root.open_start_job_popup.assert_not_called()


@pytest.mark.parametrize(
    ("chord", "key", "codepoint", "modifiers"),
    [
        (KeyChord("s", ("shift",)), ord("s"), "S", ["shift"]),
        (KeyChord("spacebar"), 32, " ", []),
    ],
)
def test_text_producing_global_shortcut_is_suppressed_while_typing(chord, key, codepoint, modifiers):
    manager = _manager()
    manager.bindings.assign("open_start_job", chord)
    manager._text_input_has_focus.return_value = True

    assert manager.on_key_down(None, key, 0, codepoint, modifiers) is False
    manager.root.open_start_job_popup.assert_not_called()


def test_mdi_send_and_newline_are_exact_and_context_scoped():
    manager = _manager()
    widget = SimpleNamespace(focus=True, send_mdi_command=Mock(), insert_text=Mock())

    assert manager.handle_mdi_keydown(widget, 13, ["ctrl"], "\r") is True
    widget.send_mdi_command.assert_called_once_with()
    assert manager.handle_mdi_keydown(widget, 13, [], "\r") is True
    widget.insert_text.assert_called_once_with("\n")
    assert manager.handle_mdi_keydown(widget, 13, ["ctrl", "shift"], "\r") is True
    widget.insert_text.assert_called_once_with("\n")


def test_remapped_mdi_newline_suppresses_text_inputs_builtin_enter_behavior():
    manager = _manager()
    manager.bindings.assign("mdi_newline", KeyChord("enter", ("shift",)))
    widget = SimpleNamespace(focus=True, send_mdi_command=Mock(), insert_text=Mock())

    assert manager.handle_mdi_keydown(widget, 13, [], "\r") is True
    widget.insert_text.assert_not_called()
    assert manager.handle_mdi_keydown(widget, 13, ["shift"], "\r") is True
    widget.insert_text.assert_called_once_with("\n")


def test_unbound_mdi_newline_restores_text_inputs_builtin_enter_behavior():
    manager = _manager()
    manager.bindings.assign("mdi_newline", None)
    widget = SimpleNamespace(focus=True, send_mdi_command=Mock(), insert_text=Mock())

    assert manager.handle_mdi_keydown(widget, 13, [], "\r") is False
    widget.insert_text.assert_not_called()


def test_mdi_send_is_consumed_but_not_sent_when_machine_state_blocks_it():
    manager = _manager()
    manager.root.can_send_mdi_command.return_value = False
    widget = SimpleNamespace(focus=True, send_mdi_command=Mock(), insert_text=Mock())

    assert manager.handle_mdi_keydown(widget, 13, ["ctrl"], "\r") is True
    widget.send_mdi_command.assert_not_called()


def test_reloading_bindings_updates_the_mdi_hint():
    manager = _manager()
    raw = '{"version":1,"bindings":{"mdi_send":{"key":"f2","modifiers":[]}}}'

    with patch("carveracontroller.addons.keyboard_shortcuts.manager.Config.get", return_value=raw):
        manager.reload_from_config()

    assert manager.root.manual_cmd.hint_text == "Enter command... <F2 to send>"


def test_jog_press_repeat_release_and_disable_are_safe():
    manager = _manager()

    assert manager.on_key_down(None, 275, 0, "", []) is True
    assert manager.on_key_down(None, 275, 0, "", []) is True
    manager.root.perform_keyboard_jog.assert_called_once_with("jog_x_positive")

    assert manager.on_key_up(None, 275) is True
    manager.root.controller.stopContinuousJog.assert_called_once_with()

    manager.on_key_down(None, 275, 0, "", [])
    manager.release_all_jogs()
    assert manager.root.controller.stopContinuousJog.call_count == 2


def test_jog_propagates_without_motion_when_context_blocks_it():
    manager = _manager()
    manager.root.is_jogging_enabled.return_value = False
    assert manager.on_key_down(None, 275, 0, "", []) is False
    manager.root.perform_keyboard_jog.assert_not_called()

    manager._text_input_has_focus.return_value = True
    assert manager.on_key_down(None, 275, 0, "", []) is False
    manager._text_input_has_focus.return_value = False
    manager.root.keyboard_jog_control = False
    assert manager.on_key_down(None, 275, 0, "", []) is False


def test_jog_release_does_not_depend_on_current_modifiers():
    manager = _manager()
    manager.bindings.assign("jog_x_positive", KeyChord("right", ("ctrl",)))
    manager.on_key_down(None, 275, 0, "", ["ctrl"])
    assert manager.on_key_up(None, 275, 0, "", []) is True
    manager.root.controller.stopContinuousJog.assert_called_once_with()


def test_blocking_modal_stops_jog_and_held_repeat_cannot_restart_it():
    manager = _manager()
    modal = ModalView()
    modal._is_open = True

    assert manager.on_key_down(None, 275, 0, "", []) is True
    manager.on_window_children(None, [modal])
    manager.root.controller.stopContinuousJog.assert_called_once_with()

    # Repeats from the physical key that was held while the modal opened must
    # remain suppressed until its matching key-up arrives.
    assert manager.on_key_down(None, 275, 0, "", []) is True
    manager.root.perform_keyboard_jog.assert_called_once_with("jog_x_positive")
    assert manager.on_key_up(None, 275) is True

    assert manager.on_key_down(None, 275, 0, "", []) is True
    assert manager.root.perform_keyboard_jog.call_count == 2


def test_modal_that_explicitly_allows_external_jog_does_not_stop_it():
    class JogModal(ModalView):
        def allows_external_jog(self):
            return True

    manager = _manager()
    modal = JogModal()
    modal._is_open = True

    manager.on_key_down(None, 275, 0, "", [])
    manager.on_window_children(None, [modal])

    manager.root.controller.stopContinuousJog.assert_not_called()


def test_cmm_jog_overlay_remains_an_external_jog_context():
    overlay = SimpleNamespace(_is_open=True)
    overlay.allows_external_jog = lambda: JogCMMWorkbenchPopup.allows_external_jog(overlay)
    parent = SimpleNamespace(allows_external_jog=lambda: True)
    root = SimpleNamespace(_open_popups=lambda: [parent, overlay])

    assert Makera._popup_prevents_jogging(root) is False


def test_blocking_modal_wins_when_another_modal_allows_external_jog():
    allowed = SimpleNamespace(allows_external_jog=lambda: True)
    blocked = SimpleNamespace()
    root = SimpleNamespace(_open_popups=lambda: [allowed, blocked])

    assert Makera._popup_prevents_jogging(root) is True


def test_second_jog_key_does_not_interrupt_the_active_direction():
    manager = _manager()

    manager.on_key_down(None, 275, 0, "", [])
    manager.on_key_down(None, 273, 0, "", [])
    manager.root.perform_keyboard_jog.assert_called_once_with("jog_x_positive")

    assert manager.on_key_up(None, 273) is True
    manager.root.controller.stopContinuousJog.assert_not_called()
    assert manager.on_key_up(None, 275) is True
    manager.root.controller.stopContinuousJog.assert_called_once_with()


def test_window_focus_loss_stops_jog_and_clears_stale_key_state():
    manager = _manager()

    manager.on_key_down(None, 275, 0, "", [])
    manager.on_window_focus(None, False)

    manager.root.controller.stopContinuousJog.assert_called_once_with()
    assert manager._held_jog_keys == set()
    assert manager.on_key_down(None, 275, 0, "", []) is True
    assert manager.root.perform_keyboard_jog.call_count == 2


def test_blocked_global_shortcut_is_not_consumed():
    manager = _manager()
    manager.root._is_popup_open.return_value = True

    assert manager.on_key_down(None, 44, 0, ",", ["ctrl"]) is False
    manager.root.config_popup.open.assert_not_called()


def test_open_file_browser_matches_the_existing_file_button_behavior():
    popup = SimpleNamespace(open_for_jobs=Mock())
    root = SimpleNamespace(file_popup=popup, _is_popup_open=Mock(return_value=False))

    with patch("carveracontroller.main.App.get_running_app", return_value=SimpleNamespace(state="Idle", playing=False)):
        assert Makera.open_file_browser(root) is True

    popup.open_for_jobs.assert_called_once_with()


def test_open_file_browser_is_blocked_when_the_file_button_would_be_unavailable():
    popup = SimpleNamespace(open_for_jobs=Mock())
    root = SimpleNamespace(file_popup=popup, _is_popup_open=Mock(return_value=False))

    with patch(
        "carveracontroller.main.App.get_running_app", return_value=SimpleNamespace(state="Pause", playing=False)
    ):
        assert Makera.open_file_browser(root) is False

    popup.open_for_jobs.assert_not_called()


def test_start_job_applicability_and_opening():
    app = SimpleNamespace(state="Idle", selected_remote_filename="job.nc", playing=False)
    popup = SimpleNamespace(mode="", load_config=Mock(), open=Mock())
    root = SimpleNamespace(_is_popup_open=Mock(return_value=False), coord_popup=popup)
    root.can_open_start_job_popup = lambda: Makera.can_open_start_job_popup(root)

    with patch("carveracontroller.main.App.get_running_app", return_value=app):
        assert Makera.can_open_start_job_popup(root) is True
        assert Makera.open_start_job_popup(root) is True

    assert popup.mode == "Run"
    popup.load_config.assert_called_once_with()
    popup.open.assert_called_once_with()


def test_start_job_is_blocked_without_idle_selected_file():
    popup = SimpleNamespace(mode="", load_config=Mock(), open=Mock())
    root = SimpleNamespace(_is_popup_open=Mock(return_value=False), coord_popup=popup)
    root.can_open_start_job_popup = lambda: Makera.can_open_start_job_popup(root)

    for app in (
        SimpleNamespace(state="Run", selected_remote_filename="job.nc", playing=True),
        SimpleNamespace(state="Idle", selected_remote_filename="", playing=False),
    ):
        with patch("carveracontroller.main.App.get_running_app", return_value=app):
            assert Makera.open_start_job_popup(root) is False
    popup.open.assert_not_called()


def test_mdi_machine_state_guard():
    root = SimpleNamespace(allow_mdi_while_machine_running="0")
    with patch(
        "carveracontroller.main.App.get_running_app",
        return_value=SimpleNamespace(state="Run"),
    ):
        assert Makera.can_send_mdi_command(root) is False
        root.allow_mdi_while_machine_running = None
        assert Makera.can_send_mdi_command(root) is False
        root.allow_mdi_while_machine_running = "1"
        assert Makera.can_send_mdi_command(root) is True


def test_applying_shortcuts_does_not_change_unrelated_mdi_permission():
    shortcut_manager = SimpleNamespace(reload_from_config=Mock())
    root = SimpleNamespace(
        controller_setting_change_list={"keyboard_shortcuts": "{}"},
        allow_mdi_while_machine_running="0",
        shortcut_manager=shortcut_manager,
        _update_macro_button_text=Mock(),
        config_popup=SimpleNamespace(btn_apply=SimpleNamespace(disabled=False)),
    )

    Makera.apply_controller_setting_changes(root)

    assert root.allow_mdi_while_machine_running == "0"
    shortcut_manager.reload_from_config.assert_called_once_with()
    assert root.controller_setting_change_list == {}


def test_applying_y_inversion_does_not_reload_current_shortcuts():
    shortcut_manager = SimpleNamespace(reload_from_config=Mock())
    root = SimpleNamespace(
        controller_setting_change_list={"invert_y_axis_jogging": "0"},
        shortcut_manager=shortcut_manager,
        _update_macro_button_text=Mock(),
        config_popup=SimpleNamespace(btn_apply=SimpleNamespace(disabled=False)),
    )
    app = SimpleNamespace(invert_y_axis_jogging=True)

    with patch("carveracontroller.main.App.get_running_app", return_value=app):
        Makera.apply_controller_setting_changes(root)

    assert app.invert_y_axis_jogging is False
    shortcut_manager.reload_from_config.assert_not_called()


def test_keyboard_jog_commands_follow_action_sign_and_add_a_axis():
    controller = SimpleNamespace(jog=Mock())
    root = SimpleNamespace(
        controller=controller,
        step_xy=SimpleNamespace(text="10"),
        step_z=SimpleNamespace(text="1"),
        step_a=SimpleNamespace(text="90"),
    )

    Makera.perform_keyboard_jog(root, "jog_y_positive")
    Makera.perform_keyboard_jog(root, "jog_a_negative")
    assert controller.jog.call_args_list[0].args == ("Y10",)
    assert controller.jog.call_args_list[1].args == ("A-90",)

    controller.jog.reset_mock()
    Makera.perform_keyboard_jog(root, "jog_y_negative")
    Makera.perform_keyboard_jog(root, "jog_a_positive")

    assert [call.args for call in controller.jog.call_args_list] == [("Y-10",), ("A90",)]


def test_machine_state_change_stops_active_keyboard_jog():
    shortcut_manager = SimpleNamespace(release_all_jogs=Mock())
    root = SimpleNamespace(
        _machine_allows_jogging=Mock(return_value=False),
        shortcut_manager=shortcut_manager,
    )
    app = SimpleNamespace(jog_controls_enabled=True)

    with patch("carveracontroller.main.App.get_running_app", return_value=app):
        Makera.update_jog_controls_enabled(root)

    assert app.jog_controls_enabled is False
    shortcut_manager.release_all_jogs.assert_called_once_with()


def test_keyboard_jog_toggle_matches_button_availability_but_forced_disable_still_works():
    shortcut_manager = SimpleNamespace(release_all_jogs=Mock())
    root = SimpleNamespace(
        keyboard_jog_control=False,
        shortcut_manager=shortcut_manager,
    )
    app = SimpleNamespace(
        root=root,
        jog_controls_enabled=False,
        jog_keyboard_enable="normal",
    )

    with patch("carveracontroller.main.App.get_running_app", return_value=app):
        assert Makera.toggle_keyboard_jog_control(root) is False
        assert root.keyboard_jog_control is False

        app.jog_controls_enabled = True
        assert Makera.toggle_keyboard_jog_control(root) is True
        assert root.keyboard_jog_control is True
        assert app.jog_keyboard_enable == "down"

        app.jog_controls_enabled = False
        assert Makera.toggle_keyboard_jog_control(root, True) is True

    assert root.keyboard_jog_control is False
    assert app.jog_keyboard_enable == "normal"
    shortcut_manager.release_all_jogs.assert_called_once_with()
