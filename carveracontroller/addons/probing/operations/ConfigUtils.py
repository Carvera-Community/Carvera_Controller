from __future__ import annotations

import json
import logging
import os
import shutil

logger = logging.getLogger(__name__)

# Old builds wrote the following files directly into the shared Kivy home.
LEGACY_CONFIG_DIR = os.path.expanduser("~/.kivy")
USER_DATA_DIR_ENV = "APP_USER_DATA_DIR"
LEGACY_BEDS_DIR = "beds"
LEGACY_MESH_DIR = os.path.join(LEGACY_BEDS_DIR, "meshes")
LEGACY_FILES = (
    "Angle-probe-settings.json",
    "Boss-probe-settings.json",
    "Calibration-probe-settings.json",
    "ProbeTip-probe-settings.json",
    "adv-calibrate-settings.json",
    "beds.json",
    "bore-probe-settings.json",
    "facing-wizard-presets.json",
    "fourth-axis-settings.json",
    "inside-corner-settings.json",
    "outside-corner-settings.json",
    "single-axis-probe-settings.json",
)


class ConfigUtils:
    # Allows tests to override the config directory during testing.
    # Production leaves this unset and uses app.user_data_dir.
    CONFIG_DIR: str | None = None
    # (legacy dir, user-data dir) pairs already scanned.
    _migrated_pairs: set[tuple[str, str]] = set()

    @staticmethod
    def config_dir() -> str:
        override = ConfigUtils.CONFIG_DIR or os.environ.get(USER_DATA_DIR_ENV)
        if override:
            os.makedirs(override, exist_ok=True)
            return override
        from kivy.app import App

        app = App.get_running_app()
        if app is None:
            raise RuntimeError("user data directory is unavailable")
        dest = app.user_data_dir
        pair = (os.path.normpath(LEGACY_CONFIG_DIR), os.path.normpath(dest))
        if pair not in ConfigUtils._migrated_pairs:
            migrate_legacy_user_files(dest, LEGACY_CONFIG_DIR)
            ConfigUtils._migrated_pairs.add(pair)
        return dest

    @staticmethod
    def save_config(config: dict, filename: str):
        try:
            directory = ConfigUtils.config_dir()
            os.makedirs(directory, exist_ok=True)
            file_path = os.path.join(directory, filename)
            with open(file_path, "w") as f:
                json.dump(config, f, indent=4)
            logger.info(f"Configuration saved to {file_path}")
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")

    @staticmethod
    def load_config(filename: str) -> dict:
        try:
            file_path = os.path.join(ConfigUtils.config_dir(), filename)
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            return {}
        if os.path.exists(file_path):
            try:
                with open(file_path) as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading configuration: {e}")
        return {}  # Return an empty dictionary if loading fails or file doesn't exist


def migrate_legacy_user_files(dest_dir: str, source_dir: str | None = None) -> None:
    """Move allowlisted app files from the old Kivy home into dest_dir"""
    source = LEGACY_CONFIG_DIR if source_dir is None else source_dir
    try:
        if os.path.realpath(source) == os.path.realpath(dest_dir):
            return
        if not os.path.isdir(source):
            return
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as exc:
        logger.error(f"Could not prepare user data migration from {source} to {dest_dir}: {exc}")
        return

    left_in_place: list[str] = []
    for name in LEGACY_FILES:
        _move_if_absent(os.path.join(source, name), os.path.join(dest_dir, name), left_in_place)

    mesh_source = os.path.join(source, LEGACY_MESH_DIR)
    mesh_dest = os.path.join(dest_dir, LEGACY_MESH_DIR)
    if os.path.isdir(mesh_source):
        try:
            names = os.listdir(mesh_source)
        except OSError as exc:
            logger.error(f"Could not list {mesh_source}: {exc}")
            names = []
        for name in names:
            src = os.path.join(mesh_source, name)
            if os.path.isfile(src):
                _move_if_absent(src, os.path.join(mesh_dest, name), left_in_place)
        _remove_dir_if_empty(mesh_source)
        _remove_dir_if_empty(os.path.join(source, LEGACY_BEDS_DIR))

    if left_in_place:
        label = "file" if len(left_in_place) == 1 else "files"
        logger.info(
            f"Left {len(left_in_place)} legacy {label} in place under {source}; "
            f"destinations in {dest_dir} already exist"
        )
        logger.debug(f"Legacy files left in place: {', '.join(left_in_place)}")


def _move_if_absent(src: str, dest: str, left_in_place: list[str]) -> None:
    try:
        if not os.path.isfile(src):
            return
        if os.path.exists(dest):
            left_in_place.append(src)
            return
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        logger.info(f"Moved {src} to {dest}")
    except OSError as exc:
        logger.error(f"Could not move {src}: {exc}")


def _remove_dir_if_empty(path: str) -> None:
    if not os.path.isdir(path):
        return
    try:
        if os.listdir(path):
            return
        os.rmdir(path)
    except OSError as exc:
        logger.error(f"Could not remove empty directory {path}: {exc}")


def _format_hint_value(val) -> str:
    try:
        f = float(val)
        if f == int(f):
            return str(int(f))
        return "%g" % f
    except (ValueError, TypeError):
        return str(val).strip()


def _get_setting_list() -> dict:
    from kivy.app import App

    return App.get_running_app().root.setting_list


def get_machine_config_hint(config_key: str) -> str | None:
    try:
        val = _get_setting_list().get(config_key)
        if val is not None and str(val).strip():
            return _format_hint_value(val)
    except Exception:
        pass
    return None
