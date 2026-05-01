"""Visual regression tests for the Carvera Controller UI.

These tests capture screenshots of the app in various states and compare them
against reference baselines. Any pixel difference indicates the refactor
changed something visible.

Usage:
    # First run: capture reference baselines
    poetry run python -m pytest tests/integration/test_visual_regression.py --update-references

    # Subsequent runs: compare against baselines
    poetry run python -m pytest tests/integration/test_visual_regression.py
"""

import json
import os

from kivy.app import App

from tests.integration.conftest import (
    apply_machine_state,
    capture_screenshot,
    compare_screenshots,
    load_gcode_file,
    pump_frames,
    save_reference,
)

_TESTS_DIR = os.path.join(os.path.dirname(__file__), "..")
GCODE_FILE = os.path.join(_TESTS_DIR, "resources", "Face 4x4 stock.cnc")
CONFIG_C1_PATH = os.path.join(_TESTS_DIR, "..", "carveracontroller", "config_c1.json")


class TestDisconnectedState:
    """Screenshots of the app with no machine connected (default boot state)."""

    def test_control_page(self, kivy_app, update_references):
        name = "disconnected_control_page"
        kivy_app.root.content.current = "Control"
        pump_frames(10)
        capture_screenshot(kivy_app, name)
        if update_references:
            save_reference(name)
        else:
            compare_screenshots(name)

    def test_file_page(self, kivy_app, update_references):
        name = "disconnected_file_page"
        kivy_app.root.content.current = "File"
        pump_frames(10)
        capture_screenshot(kivy_app, name)
        if update_references:
            save_reference(name)
        else:
            compare_screenshots(name)

    def test_settings_popup(self, kivy_app, update_references):
        name = "disconnected_settings_popup"
        kivy_app.root.content.current = "Control"
        kivy_app.root.config_popup.open()
        pump_frames(20, sleep=0.05)
        capture_screenshot(kivy_app, name)
        kivy_app.root.config_popup.dismiss()
        pump_frames(10, sleep=0.05)
        if update_references:
            save_reference(name)
        else:
            compare_screenshots(name)


class TestConnectedIdleState:
    """Screenshots with a simulated connected, idle machine."""

    def test_control_page(self, kivy_app, connected_idle_state, update_references):
        name = "connected_idle_control_page"
        kivy_app.root.content.current = "Control"
        apply_machine_state(kivy_app)
        capture_screenshot(kivy_app, name)
        if update_references:
            save_reference(name)
        else:
            compare_screenshots(name)

    def test_file_page(self, kivy_app, connected_idle_state, update_references):
        name = "connected_idle_file_page"
        kivy_app.root.content.current = "File"
        apply_machine_state(kivy_app)
        capture_screenshot(kivy_app, name)
        if update_references:
            save_reference(name)
        else:
            compare_screenshots(name)

    def test_gcode_loaded(self, kivy_app, connected_idle_state, update_references):
        name = "connected_idle_gcode_loaded"
        apply_machine_state(kivy_app)
        load_gcode_file(kivy_app, GCODE_FILE)
        kivy_app.root.content.current = "File"
        kivy_app.root.cmd_manager.current = "gcode_cmd_page"
        pump_frames(10, sleep=0.05)
        capture_screenshot(kivy_app, name)
        if update_references:
            save_reference(name)
        else:
            compare_screenshots(name)

    def test_settings_popup(self, kivy_app, connected_idle_state, update_references):
        name = "connected_idle_settings_popup"
        kivy_app.root.content.current = "Control"
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
            save_reference(name)
        else:
            compare_screenshots(name)


class TestAlarmState:
    """Screenshots with the machine in alarm state."""

    def test_alarm_control_page(self, kivy_app, alarm_state, update_references):
        name = "alarm_control_page"
        kivy_app.root.content.current = "Control"
        apply_machine_state(kivy_app)
        capture_screenshot(kivy_app, name)
        if update_references:
            save_reference(name)
        else:
            compare_screenshots(name)
