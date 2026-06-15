"""Visual regression tests for the Carvera Controller UI.

These tests capture screenshots of the app in various states and compare them
against reference baselines. Any pixel difference indicates the refactor
changed something visible.

Usage:
    # Local developer baselines.
    poetry run -- python3 scripts/visual_tests.py local-update

    # Local comparisons use local baselines and skip tests with missing local references.
    poetry run -- python3 scripts/visual_tests.py local-compare
"""

import json
import os

import pytest
from kivy.app import App

from tests.integration.conftest import (
    apply_machine_state,
    capture_screenshot,
    compare_screenshots,
    load_gcode_file,
    pump_frames,
    save_reference,
    show_content_page,
    stabilize_gcode_viewer,
)

_TESTS_DIR = os.path.join(os.path.dirname(__file__), "..")
GCODE_FILE = os.path.join(_TESTS_DIR, "resources", "Face 4x4 stock.cnc")
CONFIG_C1_PATH = os.path.join(_TESTS_DIR, "..", "carveracontroller", "config_c1.json")
REFERENCE_GROUP = os.path.splitext(os.path.basename(__file__))[0]


def reference_name(name):
    return f"{REFERENCE_GROUP}/{name}"


class TestDisconnectedState:
    """Screenshots of the app with no machine connected (default boot state)."""

    @pytest.mark.visual_reference(reference_name("disconnected_control_page"))
    def test_control_page(self, kivy_app, update_references, visual_reference_config):
        name = reference_name("disconnected_control_page")
        show_content_page(kivy_app, "Control")
        capture_screenshot(kivy_app, name)
        if update_references:
            save_reference(name, visual_reference_config)
        else:
            compare_screenshots(name, visual_reference_config)

    @pytest.mark.visual_reference(reference_name("disconnected_file_page"))
    def test_file_page(self, kivy_app, update_references, visual_reference_config):
        name = reference_name("disconnected_file_page")
        show_content_page(kivy_app, "File")
        capture_screenshot(kivy_app, name)
        if update_references:
            save_reference(name, visual_reference_config)
        else:
            compare_screenshots(name, visual_reference_config)

    @pytest.mark.visual_reference(reference_name("disconnected_settings_popup"))
    def test_settings_popup(self, kivy_app, update_references, visual_reference_config):
        name = reference_name("disconnected_settings_popup")
        show_content_page(kivy_app, "Control")
        kivy_app.root.config_popup.open()
        pump_frames(20, sleep=0.05)
        capture_screenshot(kivy_app, name)
        kivy_app.root.config_popup.dismiss()
        pump_frames(10, sleep=0.05)
        if update_references:
            save_reference(name, visual_reference_config)
        else:
            compare_screenshots(name, visual_reference_config)


class TestConnectedIdleState:
    """Screenshots with a simulated connected, idle machine."""

    @pytest.mark.visual_reference(reference_name("connected_idle_control_page"))
    def test_control_page(self, kivy_app, connected_idle_state, update_references, visual_reference_config):
        name = reference_name("connected_idle_control_page")
        show_content_page(kivy_app, "Control")
        apply_machine_state(kivy_app)
        capture_screenshot(kivy_app, name)
        if update_references:
            save_reference(name, visual_reference_config)
        else:
            compare_screenshots(name, visual_reference_config)

    @pytest.mark.visual_reference(reference_name("connected_idle_file_page"))
    def test_file_page(self, kivy_app, connected_idle_state, update_references, visual_reference_config):
        name = reference_name("connected_idle_file_page")
        show_content_page(kivy_app, "File")
        apply_machine_state(kivy_app)
        capture_screenshot(kivy_app, name)
        if update_references:
            save_reference(name, visual_reference_config)
        else:
            compare_screenshots(name, visual_reference_config)

    @pytest.mark.visual_reference(reference_name("connected_idle_gcode_loaded"))
    def test_gcode_loaded(self, kivy_app, connected_idle_state, update_references, visual_reference_config):
        name = reference_name("connected_idle_gcode_loaded")
        apply_machine_state(kivy_app)
        load_gcode_file(kivy_app, GCODE_FILE)
        show_content_page(kivy_app, "File")
        kivy_app.root.cmd_manager.current = "gcode_cmd_page"
        stabilize_gcode_viewer(kivy_app)
        capture_screenshot(kivy_app, name)
        if update_references:
            save_reference(name, visual_reference_config)
        else:
            compare_screenshots(name, visual_reference_config)

    @pytest.mark.visual_reference(reference_name("connected_idle_settings_popup"))
    def test_settings_popup(self, kivy_app, connected_idle_state, update_references, visual_reference_config):
        name = reference_name("connected_idle_settings_popup")
        show_content_page(kivy_app, "Control")
        App.get_running_app().model = "C1"
        kivy_app.root.config_loaded = True
        # Pre-populate setting_list with defaults from config JSON so
        # load_machine_config doesn't fail on missing keys
        with open(CONFIG_C1_PATH) as f:
            config_data = json.load(f)
        for entry in config_data:
            if "key" in entry and entry.get("type") != "title":
                kivy_app.root.setting_list[entry["key"]] = entry.get("default", "0")
        kivy_app.root.load_machine_config()
        apply_machine_state(kivy_app)
        kivy_app.root.config_popup.open()
        pump_frames(20, sleep=0.05)
        capture_screenshot(kivy_app, name)
        kivy_app.root.config_popup.dismiss()
        pump_frames(10, sleep=0.05)
        if update_references:
            save_reference(name, visual_reference_config)
        else:
            compare_screenshots(name, visual_reference_config)


class TestAlarmState:
    """Screenshots with the machine in alarm state."""

    @pytest.mark.visual_reference(reference_name("alarm_control_page"))
    def test_alarm_control_page(self, kivy_app, alarm_state, update_references, visual_reference_config):
        name = reference_name("alarm_control_page")
        show_content_page(kivy_app, "Control")
        apply_machine_state(kivy_app)
        capture_screenshot(kivy_app, name)
        if update_references:
            save_reference(name, visual_reference_config)
        else:
            compare_screenshots(name, visual_reference_config)


class TestSetPositionPopups:
    """Screenshots of the SetX/Y/Z/A, SetTool, ChangeTool, and MoveA popups."""

    def _capture_popup(self, kivy_app, popup, name, update_references, visual_reference_config):
        show_content_page(kivy_app, "Control")
        popup.open()
        pump_frames(5)
        capture_screenshot(kivy_app, name)
        popup.dismiss()
        pump_frames(2)
        if update_references:
            save_reference(name, visual_reference_config)
        else:
            compare_screenshots(name, visual_reference_config)

    @pytest.mark.visual_reference(reference_name("set_x_popup"))
    def test_set_x_popup(self, kivy_app, update_references, visual_reference_config):
        self._capture_popup(
            kivy_app,
            kivy_app.root.coord_popup.setx_popup,
            reference_name("set_x_popup"),
            update_references,
            visual_reference_config,
        )

    @pytest.mark.visual_reference(reference_name("set_y_popup"))
    def test_set_y_popup(self, kivy_app, update_references, visual_reference_config):
        self._capture_popup(
            kivy_app,
            kivy_app.root.coord_popup.sety_popup,
            reference_name("set_y_popup"),
            update_references,
            visual_reference_config,
        )

    @pytest.mark.visual_reference(reference_name("set_z_popup"))
    def test_set_z_popup(self, kivy_app, update_references, visual_reference_config):
        self._capture_popup(
            kivy_app,
            kivy_app.root.coord_popup.setz_popup,
            reference_name("set_z_popup"),
            update_references,
            visual_reference_config,
        )

    @pytest.mark.visual_reference(reference_name("set_a_popup"))
    def test_set_a_popup(self, kivy_app, update_references, visual_reference_config):
        self._capture_popup(
            kivy_app,
            kivy_app.root.coord_popup.seta_popup,
            reference_name("set_a_popup"),
            update_references,
            visual_reference_config,
        )

    @pytest.mark.visual_reference(reference_name("set_tool_popup"))
    def test_set_tool_popup(self, kivy_app, update_references, visual_reference_config):
        self._capture_popup(
            kivy_app,
            kivy_app.root.coord_popup.settool_popup,
            reference_name("set_tool_popup"),
            update_references,
            visual_reference_config,
        )

    @pytest.mark.visual_reference(reference_name("change_tool_popup"))
    def test_change_tool_popup(self, kivy_app, update_references, visual_reference_config):
        self._capture_popup(
            kivy_app,
            kivy_app.root.coord_popup.change_tool_popup,
            reference_name("change_tool_popup"),
            update_references,
            visual_reference_config,
        )

    @pytest.mark.visual_reference(reference_name("move_a_popup"))
    def test_move_a_popup(self, kivy_app, update_references, visual_reference_config):
        self._capture_popup(
            kivy_app,
            kivy_app.root.coord_popup.MoveA_popup,
            reference_name("move_a_popup"),
            update_references,
            visual_reference_config,
        )
