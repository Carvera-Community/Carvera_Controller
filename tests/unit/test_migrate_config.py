import pytest
from kivy.config import Config

from carveracontroller.main import migrate_config, parse_schema_version, settings_bool_keys

SCHEMA_KEY = "config_schema_version"
RUNNING_KEY = "allow_jogging_while_machine_running"
SPINDLE_KEY = "allow_jogging_while_spindle_on"


@pytest.fixture
def carvera_section():
    """Give each test an empty carvera section and restore the original afterwards."""
    existed = Config.has_section("carvera")
    snapshot = dict(Config.items("carvera")) if existed else None
    if existed:
        Config.remove_section("carvera")
    Config.add_section("carvera")
    try:
        yield
    finally:
        Config.remove_section("carvera")
        if snapshot is not None:
            Config.add_section("carvera")
            for key, value in snapshot.items():
                Config.set("carvera", key, value)


def test_upgrade_without_jogging_while_running_key_disables_spindle_on(carvera_section):
    migrate_config(new_install=False)
    assert Config.get("carvera", SPINDLE_KEY) == "0"


def test_upgrade_with_jogging_while_running_enables_spindle_on(carvera_section):
    # Before the spindle-on setting existed, allowing jogging while running also
    # allowed it with the spindle on.
    Config.set("carvera", RUNNING_KEY, "1")
    migrate_config(new_install=False)
    assert Config.get("carvera", SPINDLE_KEY) == "1"


# A stored "true" for the running flag has always behaved as off (the code checks
# for "1"), so it must not enable jogging with the spindle on.
@pytest.mark.parametrize("running_value", ["0", "false", "true", "True"])
def test_upgrade_without_jogging_while_running_disables_spindle_on(carvera_section, running_value):
    Config.set("carvera", RUNNING_KEY, running_value)
    migrate_config(new_install=False)
    assert Config.get("carvera", SPINDLE_KEY) == "0"


@pytest.mark.parametrize("spindle_value", ["0", "1"])
def test_existing_spindle_on_value_is_not_overwritten(carvera_section, spindle_value):
    Config.set("carvera", RUNNING_KEY, "0" if spindle_value == "1" else "1")
    Config.set("carvera", SPINDLE_KEY, spindle_value)
    migrate_config(new_install=False)
    assert Config.get("carvera", SPINDLE_KEY) == spindle_value


def test_migration_does_not_write_jogging_while_running(carvera_section):
    # The running flag is a plain default now; only the spindle-on result is persisted.
    migrate_config(new_install=False)
    assert not Config.has_option("carvera", RUNNING_KEY)


def test_migration_runs_once(carvera_section):
    migrate_config(new_install=False)
    # The user enables jogging while running after the migration already ran.
    Config.set("carvera", RUNNING_KEY, "1")
    migrate_config(new_install=False)
    assert Config.get("carvera", SPINDLE_KEY) == "0"


def test_legacy_usb_device_id_is_split_into_vid_pid_and_serial(carvera_section):
    Config.set("carvera", "usb_device_id", "1a86:7523:ABC123")
    migrate_config(new_install=False)
    assert Config.get("carvera", "usb_device_id") == "1A86:7523"
    assert Config.get("carvera", "usb_serial") == "ABC123"


def test_legacy_usb_device_id_keeps_existing_serial(carvera_section):
    Config.set("carvera", "usb_device_id", "1a86:7523:OLDSERIAL")
    Config.set("carvera", "usb_serial", "PREFERRED")
    migrate_config(new_install=False)
    assert Config.get("carvera", "usb_device_id") == "1A86:7523"
    assert Config.get("carvera", "usb_serial") == "PREFERRED"


def test_vid_pid_usb_device_id_is_left_unchanged(carvera_section):
    Config.set("carvera", "usb_device_id", "1a86:7523")
    migrate_config(new_install=False)
    assert Config.get("carvera", "usb_device_id") == "1a86:7523"
    assert not Config.has_option("carvera", "usb_serial")


def test_missing_usb_device_id_writes_nothing(carvera_section):
    migrate_config(new_install=False)
    assert not Config.has_option("carvera", "usb_device_id")
    assert not Config.has_option("carvera", "usb_serial")


OLD_TIME_ESTIMATE_KEY = "high_precision_reamining_time_estimate"
NEW_TIME_ESTIMATE_KEY = "high_precision_remaining_time_estimate"


@pytest.mark.parametrize("value", ["0", "1"])
def test_misspelled_time_estimate_key_is_renamed(carvera_section, value):
    Config.set("carvera", OLD_TIME_ESTIMATE_KEY, value)
    migrate_config(new_install=False)
    assert Config.get("carvera", NEW_TIME_ESTIMATE_KEY) == value
    assert not Config.has_option("carvera", OLD_TIME_ESTIMATE_KEY)


def test_misspelled_time_estimate_key_does_not_overwrite_new_key(carvera_section):
    Config.set("carvera", OLD_TIME_ESTIMATE_KEY, "1")
    Config.set("carvera", NEW_TIME_ESTIMATE_KEY, "0")
    migrate_config(new_install=False)
    assert Config.get("carvera", NEW_TIME_ESTIMATE_KEY) == "0"
    assert not Config.has_option("carvera", OLD_TIME_ESTIMATE_KEY)


def test_missing_time_estimate_key_writes_nothing(carvera_section):
    migrate_config(new_install=False)
    assert not Config.has_option("carvera", NEW_TIME_ESTIMATE_KEY)


def test_new_install_marks_tutorial_incomplete(carvera_section):
    migrate_config(new_install=True)
    assert Config.get("carvera", "tutorial_completed") == "0"


def test_upgrade_marks_tutorial_complete(carvera_section):
    # Existing users already know the workflow, so they skip the tour.
    migrate_config(new_install=False)
    assert Config.get("carvera", "tutorial_completed") == "1"


@pytest.mark.parametrize("value", ["0", "1"])
def test_existing_tutorial_completed_is_not_overwritten(carvera_section, value):
    Config.set("carvera", "tutorial_completed", value)
    migrate_config(new_install=False)
    assert Config.get("carvera", "tutorial_completed") == value


@pytest.mark.parametrize(
    ("key", "stored", "expected"),
    [
        ("pendant_jogging_default", "true", "1"),
        ("pendant_jogging_default", "True", "1"),
        ("show_update", "true", "1"),
        ("gamepad_invert_x", "false", "0"),
        ("gamepad_invert_x", "False", "0"),
        ("mdi_auto_correct_case", "true", "1"),
    ],
)
def test_true_false_bool_settings_become_1_0(carvera_section, key, stored, expected):
    Config.set("carvera", key, stored)
    migrate_config(new_install=False)
    assert Config.get("carvera", key) == expected


def test_true_for_jogging_while_running_keeps_its_off_behaviour(carvera_section):
    Config.set("carvera", RUNNING_KEY, "true")
    migrate_config(new_install=False)
    assert Config.get("carvera", RUNNING_KEY) == "0"


@pytest.mark.parametrize("stored", ["0", "1"])
def test_1_0_bool_settings_are_left_unchanged(carvera_section, stored):
    Config.set("carvera", "pendant_jogging_default", stored)
    migrate_config(new_install=False)
    assert Config.get("carvera", "pendant_jogging_default") == stored


def test_non_bool_settings_are_left_unchanged(carvera_section):
    # usb_serial is a string setting; only bool settings are normalized.
    Config.set("carvera", "usb_serial", "true")
    migrate_config(new_install=False)
    assert Config.get("carvera", "usb_serial") == "true"


def test_bool_normalization_does_not_add_missing_keys(carvera_section):
    migrate_config(new_install=False)
    assert not Config.has_option("carvera", "pendant_jogging_default")


def test_settings_bool_keys_reads_every_definition_file():
    keys = set(settings_bool_keys())
    # One bool from each definition file that has bool settings.
    assert ("carvera", "pendant_jogging_default") in keys  # pendant_config.json
    assert ("carvera", "gcode_highlight_enabled") in keys  # gcode_viewer_config.json
    assert ("carvera", "file_browser_thumbnails") in keys  # ui/file_browser/config.json
    assert ("carvera", "mdi_auto_correct_case") in keys  # controller_config.json
    assert ("carvera", "usb_serial") not in keys


def test_migrations_save_only_the_keys_they_change(carvera_section, tmp_path, monkeypatch):
    import configparser

    path = tmp_path / "config.ini"
    path.write_text(
        "[carvera]\nusb_device_id = 1a86:7523:ABC123\nhigh_precision_reamining_time_estimate = 0\n", encoding="utf-8"
    )
    monkeypatch.setattr(Config, "filename", str(path))
    Config.set("carvera", "usb_device_id", "1a86:7523:ABC123")
    Config.set("carvera", OLD_TIME_ESTIMATE_KEY, "0")
    Config.setdefault("carvera", "show_update", "1")  # an in-memory JSON default

    migrate_config(new_install=False)

    disk = configparser.RawConfigParser()
    disk.read(path, encoding="utf-8")
    assert dict(disk.items("carvera")) == {
        "usb_device_id": "1A86:7523",
        "usb_serial": "ABC123",
        NEW_TIME_ESTIMATE_KEY: "0",
        SPINDLE_KEY: "0",
        "tutorial_completed": "1",
        SCHEMA_KEY: "2.0",
    }


def test_new_install_saves_schema_version_and_skips_migrations(carvera_section):
    migrate_config(new_install=True)
    assert Config.get("carvera", SCHEMA_KEY) == "2.0"
    assert Config.get("carvera", "tutorial_completed") == "0"
    # The spindle setting follows its JSON default instead of being saved.
    assert not Config.has_option("carvera", SPINDLE_KEY)


def test_upgrade_without_schema_version_migrates_and_stamps_it(carvera_section):
    Config.set("carvera", "pendant_jogging_default", "true")
    migrate_config(new_install=False)
    assert Config.get("carvera", "pendant_jogging_default") == "1"
    assert Config.get("carvera", SCHEMA_KEY) == "2.0"


@pytest.mark.parametrize("stored", ["", "abc", "1.0"])
def test_missing_invalid_or_old_schema_version_is_migrated(carvera_section, stored):
    Config.set("carvera", SCHEMA_KEY, stored)
    Config.set("carvera", "pendant_jogging_default", "true")
    migrate_config(new_install=False)
    assert Config.get("carvera", "pendant_jogging_default") == "1"
    assert Config.get("carvera", SCHEMA_KEY) == "2.0"


def test_current_schema_version_skips_migrations(carvera_section):
    Config.set("carvera", SCHEMA_KEY, "2.0")
    Config.set("carvera", "pendant_jogging_default", "true")
    migrate_config(new_install=False)
    assert Config.get("carvera", "pendant_jogging_default") == "true"
    assert not Config.has_option("carvera", SPINDLE_KEY)
    assert not Config.has_option("carvera", "tutorial_completed")


def test_newer_schema_version_is_not_migrated_or_overwritten(carvera_section):
    # A config from a newer release, opened after a downgrade.
    Config.set("carvera", SCHEMA_KEY, "9.0")
    Config.set("carvera", "pendant_jogging_default", "true")
    migrate_config(new_install=False)
    assert Config.get("carvera", SCHEMA_KEY) == "9.0"
    assert Config.get("carvera", "pendant_jogging_default") == "true"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2.0", (2, 0)), ("2.10", (2, 10)), (" 3 ", (3,)), ("", None), ("abc", None), ("2.-1", None)],
)
def test_parse_schema_version(text, expected):
    assert parse_schema_version(text) == expected


def test_schema_versions_compare_numerically():
    assert parse_schema_version("2.10") > parse_schema_version("2.9")


@pytest.fixture
def fake_migrations(monkeypatch):
    """Replace the real steps with recording steps for 2.0, 2.1 and 3.0."""
    import carveracontroller.main as main_module

    ran = []

    def step(name):
        def run():
            # Each step sees the version saved by the step before it.
            ran.append((name, Config.get("carvera", SCHEMA_KEY, fallback="")))

        return run

    steps = (((2, 0), step("2.0")), ((2, 1), step("2.1")), ((3, 0), step("3.0")))
    monkeypatch.setattr(main_module, "CONFIG_MIGRATIONS", steps)
    monkeypatch.setattr(main_module, "CONFIG_SCHEMA_VERSION", (3, 0))
    return ran


def test_old_config_runs_every_step_in_order(carvera_section, fake_migrations):
    migrate_config(new_install=False)
    assert fake_migrations == [("2.0", ""), ("2.1", "2.0"), ("3.0", "2.1")]
    assert Config.get("carvera", SCHEMA_KEY) == "3.0"


def test_only_steps_newer_than_the_stored_version_run(carvera_section, fake_migrations):
    Config.set("carvera", SCHEMA_KEY, "2.0")
    migrate_config(new_install=False)
    assert [name for name, _ in fake_migrations] == ["2.1", "3.0"]


def test_new_install_runs_no_steps_and_gets_latest_version(carvera_section, fake_migrations):
    migrate_config(new_install=True)
    assert fake_migrations == []
    assert Config.get("carvera", SCHEMA_KEY) == "3.0"


def test_failed_step_resumes_from_last_finished_step(carvera_section, monkeypatch):
    import carveracontroller.main as main_module

    ran = []

    def failing():
        raise RuntimeError("step failed")

    steps = [((2, 0), lambda: ran.append("2.0")), ((2, 1), failing), ((3, 0), lambda: ran.append("3.0"))]
    monkeypatch.setattr(main_module, "CONFIG_MIGRATIONS", steps)
    monkeypatch.setattr(main_module, "CONFIG_SCHEMA_VERSION", (3, 0))
    with pytest.raises(RuntimeError):
        migrate_config(new_install=False)
    assert Config.get("carvera", SCHEMA_KEY) == "2.0"

    steps[1] = ((2, 1), lambda: ran.append("2.1"))
    migrate_config(new_install=False)
    assert ran == ["2.0", "2.1", "3.0"]
    assert Config.get("carvera", SCHEMA_KEY) == "3.0"


def test_schema_version_is_the_last_migration():
    import carveracontroller.main as main_module

    versions = [version for version, _ in main_module.CONFIG_MIGRATIONS]
    assert versions == sorted(versions), "CONFIG_MIGRATIONS must be in version order"
    assert versions[-1] == main_module.CONFIG_SCHEMA_VERSION
