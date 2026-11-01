"""App JSON lives in the user-data directory, with a one-time move out of ~/.kivy."""

from __future__ import annotations

import logging
import os

import pytest

from carveracontroller.addons.probing.operations.ConfigUtils import (
    LEGACY_FILES,
    LEGACY_MESH_DIR,
    USER_DATA_DIR_ENV,
    ConfigUtils,
    migrate_legacy_user_files,
)


def _legacy_tree(root):
    legacy = root / "kivy"
    legacy.mkdir()
    (legacy / "config.ini").write_text("[kivy]\n", encoding="utf-8")
    (legacy / "logs").mkdir()
    (legacy / "logs" / "kivy.txt").write_text("log", encoding="utf-8")
    (legacy / "icon").mkdir()
    (legacy / "icon" / "icon.png").write_bytes(b"png")
    (legacy / "mods").mkdir()
    (legacy / "mods" / "style.kv").write_text("", encoding="utf-8")
    (legacy / "other.json").write_text("{}", encoding="utf-8")
    (legacy / "beds.json").write_text('{"version": 1}', encoding="utf-8")
    (legacy / "facing-wizard-presets.json").write_text('{"presets": []}', encoding="utf-8")
    mesh = legacy / "beds" / "meshes"
    mesh.mkdir(parents=True)
    (mesh / "plate.obj").write_text("o plate\n", encoding="utf-8")
    return legacy


def test_migrate_moves_allowlisted_files_and_meshes(tmp_path):
    legacy = _legacy_tree(tmp_path)
    dest = tmp_path / "makera"

    migrate_legacy_user_files(str(dest), str(legacy))

    assert (dest / "beds.json").read_text(encoding="utf-8") == '{"version": 1}'
    assert (dest / "facing-wizard-presets.json").read_text(encoding="utf-8") == '{"presets": []}'
    assert (dest / "beds" / "meshes" / "plate.obj").read_text(encoding="utf-8") == "o plate\n"
    assert not (legacy / "beds.json").exists()
    assert not (legacy / "facing-wizard-presets.json").exists()
    assert not (legacy / "beds" / "meshes" / "plate.obj").exists()
    assert not (legacy / "beds").exists()
    assert (legacy / "config.ini").is_file()
    assert (legacy / "logs" / "kivy.txt").is_file()
    assert (legacy / "icon" / "icon.png").is_file()
    assert (legacy / "mods" / "style.kv").is_file()
    assert (legacy / "other.json").is_file()


def test_migrate_summarizes_files_left_in_place(tmp_path, caplog):
    legacy = _legacy_tree(tmp_path)
    dest = tmp_path / "makera"
    (dest / "beds" / "meshes").mkdir(parents=True)
    (dest / "beds.json").write_text('{"version": 2}', encoding="utf-8")
    (dest / "facing-wizard-presets.json").write_text("{}", encoding="utf-8")
    (dest / "beds" / "meshes" / "plate.obj").write_text("kept\n", encoding="utf-8")

    with caplog.at_level(logging.DEBUG, logger="carveracontroller.addons.probing.operations.ConfigUtils"):
        migrate_legacy_user_files(str(dest), str(legacy))

    info = [record.message for record in caplog.records if record.levelno == logging.INFO]
    assert info == [f"Left 3 legacy files in place under {legacy}; destinations in {dest} already exist"]
    debug = [record.message for record in caplog.records if record.levelno == logging.DEBUG]
    assert len(debug) == 1
    assert str(legacy / "beds.json") in debug[0]
    assert str(legacy / "facing-wizard-presets.json") in debug[0]
    assert str(legacy / "beds" / "meshes" / "plate.obj") in debug[0]


def test_migrate_left_in_place_summary_is_singular_for_one_file(tmp_path, caplog):
    legacy = tmp_path / "kivy"
    dest = tmp_path / "makera"
    legacy.mkdir()
    dest.mkdir()
    (legacy / "beds.json").write_text("{}", encoding="utf-8")
    (dest / "beds.json").write_text('{"version": 2}', encoding="utf-8")

    with caplog.at_level(logging.INFO, logger="carveracontroller.addons.probing.operations.ConfigUtils"):
        migrate_legacy_user_files(str(dest), str(legacy))

    info = [record.message for record in caplog.records if record.levelno == logging.INFO]
    assert info == [f"Left 1 legacy file in place under {legacy}; destinations in {dest} already exist"]


def test_migrate_does_not_overwrite_existing_destination(tmp_path):
    legacy = _legacy_tree(tmp_path)
    dest = tmp_path / "makera"
    (dest / "beds" / "meshes").mkdir(parents=True)
    (dest / "beds.json").write_text('{"version": 2}', encoding="utf-8")
    (dest / "beds" / "meshes" / "plate.obj").write_text("kept\n", encoding="utf-8")

    migrate_legacy_user_files(str(dest), str(legacy))

    assert (dest / "beds.json").read_text(encoding="utf-8") == '{"version": 2}'
    assert (dest / "beds" / "meshes" / "plate.obj").read_text(encoding="utf-8") == "kept\n"
    assert (legacy / "beds.json").is_file()
    assert (legacy / "beds" / "meshes" / "plate.obj").is_file()
    assert (dest / "facing-wizard-presets.json").is_file()
    assert not (legacy / "facing-wizard-presets.json").exists()


def test_migrate_second_call_is_a_noop(tmp_path):
    legacy = _legacy_tree(tmp_path)
    dest = tmp_path / "makera"

    migrate_legacy_user_files(str(dest), str(legacy))
    migrate_legacy_user_files(str(dest), str(legacy))

    assert (dest / "beds.json").read_text(encoding="utf-8") == '{"version": 1}'
    assert (dest / "beds" / "meshes" / "plate.obj").is_file()
    assert (legacy / "config.ini").is_file()


def test_migrate_missing_source_is_a_noop(tmp_path):
    dest = tmp_path / "makera"

    migrate_legacy_user_files(str(dest), str(tmp_path / "missing"))

    assert not dest.exists()


def test_migrate_same_directory_is_a_noop(tmp_path):
    legacy = _legacy_tree(tmp_path)

    migrate_legacy_user_files(str(legacy), str(legacy))

    assert (legacy / "beds.json").is_file()
    assert (legacy / "config.ini").is_file()
    assert (legacy / "beds" / "meshes" / "plate.obj").is_file()


def test_save_and_load_honor_config_dir(monkeypatch, tmp_path):
    override = tmp_path / "override"
    monkeypatch.setenv(USER_DATA_DIR_ENV, str(tmp_path / "env"))
    monkeypatch.setattr(ConfigUtils, "CONFIG_DIR", str(override))

    ConfigUtils.save_config({"repeat": "2"}, "adv-calibrate-settings.json")

    assert ConfigUtils.load_config("adv-calibrate-settings.json") == {"repeat": "2"}
    assert (override / "adv-calibrate-settings.json").is_file()
    assert not (tmp_path / "env").exists()


def test_env_override_skips_migration(monkeypatch, tmp_path):
    legacy = _legacy_tree(tmp_path)
    env_dir = tmp_path / "env"
    monkeypatch.setattr(ConfigUtils, "CONFIG_DIR", None)
    monkeypatch.setenv(USER_DATA_DIR_ENV, str(env_dir))
    monkeypatch.setattr(
        "carveracontroller.addons.probing.operations.ConfigUtils.LEGACY_CONFIG_DIR",
        str(legacy),
    )

    assert ConfigUtils.load_config("beds.json") == {}
    assert (legacy / "beds.json").is_file()
    assert ConfigUtils.config_dir() == str(env_dir)


def test_config_dir_migrates_from_user_data_dir(monkeypatch, tmp_path):
    legacy = _legacy_tree(tmp_path)
    dest = tmp_path / "makera"

    class _App:
        user_data_dir = str(dest)

    monkeypatch.setattr(ConfigUtils, "CONFIG_DIR", None)
    monkeypatch.setattr(ConfigUtils, "_migrated_pairs", set())
    monkeypatch.delenv(USER_DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(
        "carveracontroller.addons.probing.operations.ConfigUtils.LEGACY_CONFIG_DIR",
        str(legacy),
    )
    monkeypatch.setattr("kivy.app.App.get_running_app", lambda: _App())

    assert ConfigUtils.config_dir() == str(dest)
    assert (dest / "beds.json").is_file()
    assert not (legacy / "beds.json").exists()
    assert (legacy / "config.ini").is_file()
    assert ConfigUtils.load_config("beds.json") == {"version": 1}


def test_config_dir_scans_legacy_files_once_per_directory(monkeypatch, tmp_path):
    legacy = _legacy_tree(tmp_path)
    dest = tmp_path / "makera"

    class _App:
        user_data_dir = str(dest)

    monkeypatch.setattr(ConfigUtils, "CONFIG_DIR", None)
    monkeypatch.setattr(ConfigUtils, "_migrated_pairs", set())
    monkeypatch.delenv(USER_DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(
        "carveracontroller.addons.probing.operations.ConfigUtils.LEGACY_CONFIG_DIR",
        str(legacy),
    )
    monkeypatch.setattr("kivy.app.App.get_running_app", lambda: _App())

    assert ConfigUtils.config_dir() == str(dest)
    assert not (legacy / "beds.json").exists()

    (dest / "facing-wizard-presets.json").unlink()
    (legacy / "facing-wizard-presets.json").write_text('{"presets": ["later"]}', encoding="utf-8")

    assert ConfigUtils.config_dir() == str(dest)
    assert (legacy / "facing-wizard-presets.json").is_file()
    assert not (dest / "facing-wizard-presets.json").exists()

    second_root = tmp_path / "second"
    second_root.mkdir()
    second_legacy = _legacy_tree(second_root)
    second_dest = tmp_path / "other"
    monkeypatch.setattr(
        "carveracontroller.addons.probing.operations.ConfigUtils.LEGACY_CONFIG_DIR",
        str(second_legacy),
    )
    _App.user_data_dir = str(second_dest)

    assert ConfigUtils.config_dir() == str(second_dest)
    assert (second_dest / "beds.json").is_file()
    assert not (second_legacy / "beds.json").exists()


def test_config_dir_without_app_raises(monkeypatch):
    monkeypatch.setattr(ConfigUtils, "CONFIG_DIR", None)
    monkeypatch.delenv(USER_DATA_DIR_ENV, raising=False)
    monkeypatch.setattr("kivy.app.App.get_running_app", lambda: None)

    with pytest.raises(RuntimeError, match="user data directory"):
        ConfigUtils.config_dir()


def test_load_config_without_app_returns_empty(monkeypatch):
    monkeypatch.setattr(ConfigUtils, "CONFIG_DIR", None)
    monkeypatch.delenv(USER_DATA_DIR_ENV, raising=False)
    monkeypatch.setattr("kivy.app.App.get_running_app", lambda: None)

    assert ConfigUtils.load_config("beds.json") == {}


def test_legacy_files_match_persisted_names():
    from carveracontroller.addons.beds.store import MESHES_SUBDIR, STORE_FILENAME
    from carveracontroller.addons.facing.facing_presets import PRESET_FILENAME
    from carveracontroller.addons.probing.operations.Angle.AngleSettings import AngleSettings
    from carveracontroller.addons.probing.operations.Bore.BoreSettings import BoreSettings
    from carveracontroller.addons.probing.operations.Boss.BossSettings import BossSettings
    from carveracontroller.addons.probing.operations.Calibration.CalibrationSettings import CalibrationSettings
    from carveracontroller.addons.probing.operations.FourthAxis.FourthAxisSettings import FourthAxisSettings
    from carveracontroller.addons.probing.operations.InsideCorner.InsideCornerSettings import InsideCornerSettings
    from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerSettings import OutsideCornerSettings
    from carveracontroller.addons.probing.operations.ProbeTip.ProbeTipSettings import ProbeTipSettings
    from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeSettings import (
        SingleAxisProbeSettings,
    )
    from carveracontroller.ui.popups.adv_calibrate.adv_calibrate import SETTINGS_FILENAME

    expected = {
        AngleSettings.config_filename,
        BoreSettings.config_filename,
        BossSettings.config_filename,
        CalibrationSettings.config_filename,
        FourthAxisSettings.config_filename,
        InsideCornerSettings.config_filename,
        OutsideCornerSettings.config_filename,
        ProbeTipSettings.config_filename,
        SingleAxisProbeSettings.config_filename,
        PRESET_FILENAME,
        STORE_FILENAME,
        SETTINGS_FILENAME,
    }
    assert set(LEGACY_FILES) == expected
    assert LEGACY_MESH_DIR == MESHES_SUBDIR
    assert USER_DATA_DIR_ENV == "APP_USER_DATA_DIR"


def test_conftest_points_user_data_at_temp_dir():
    user_data = os.path.realpath(os.environ[USER_DATA_DIR_ENV])
    assert os.path.basename(user_data) == "user_data"
    assert "kivy_unit_test_" in user_data
    home = os.path.realpath(os.path.expanduser("~"))
    assert not user_data.startswith(os.path.join(home, ".kivy"))
    assert not user_data.startswith(os.path.join(home, ".config"))
