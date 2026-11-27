"""Auto Z Probe origin and offsets persist in Config, with safe fallbacks (issue #736)."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from kivy.config import ConfigParser

from carveracontroller.main import ZProbePopup
from carveracontroller.ui.config_run.CoordPopup import ZPROBE_DEFAULTS, load_zprobe_settings, save_zprobe_settings


def _config(**options):
    config = ConfigParser()
    config.add_section("carvera")
    for key, value in options.items():
        config.set("carvera", key, value)
    return config


def test_defaults_to_work_origin_when_nothing_saved():
    assert load_zprobe_settings(_config()) == {"origin": 1, "x_offset": 5.0, "y_offset": 5.0}
    assert load_zprobe_settings(ConfigParser()) == ZPROBE_DEFAULTS


def test_save_then_load_round_trip(tmp_path):
    path = tmp_path / "config.ini"
    config = _config()
    config.filename = str(path)
    assert save_zprobe_settings(2, 12.5, -3.0, config)
    restored = ConfigParser()
    restored.read(str(path))
    assert load_zprobe_settings(restored) == {"origin": 2, "x_offset": 12.5, "y_offset": -3.0}


def test_save_reports_failure(tmp_path):
    assert not save_zprobe_settings(1, 5.0, 5.0, ConfigParser())
    config = _config()
    config.filename = str(tmp_path / "missing" / "config.ini")
    assert not save_zprobe_settings(1, 5.0, 5.0, config)


def test_failed_save_keeps_popup_open_and_reports_error():
    popup = SimpleNamespace(
        validate_inputs=lambda: (True, ""),
        ids=SimpleNamespace(
            cbx_origin1=SimpleNamespace(active=True),
            txt_x_offset=SimpleNamespace(text="5"),
            txt_y_offset=SimpleNamespace(text="5"),
        ),
        coord_popup=Mock(),
        dismiss=Mock(),
    )
    app = Mock()
    with (
        patch("carveracontroller.main.save_zprobe_settings", return_value=False),
        patch("carveracontroller.main.App.get_running_app", return_value=app),
    ):
        ZProbePopup.on_ok_pressed(popup)
    app.root.show_message_popup.assert_called_once()
    popup.dismiss.assert_not_called()
    popup.coord_popup.set_config.assert_not_called()


def test_invalid_values_fall_back_per_key():
    config = _config(zprobe_origin="3", zprobe_x_offset="abc", zprobe_y_offset="7")
    assert load_zprobe_settings(config) == {"origin": 1, "x_offset": 5.0, "y_offset": 7.0}
    config = _config(zprobe_origin="x", zprobe_x_offset="nan", zprobe_y_offset="inf")
    assert load_zprobe_settings(config) == ZPROBE_DEFAULTS
