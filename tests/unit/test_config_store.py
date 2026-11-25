import configparser
import pathlib
import re

import pytest
from kivy.config import ConfigParser

from carveracontroller.config_store import config_remove_one, config_write_many, config_write_one

PACKAGE_DIR = pathlib.Path(__file__).resolve().parents[2] / "carveracontroller"


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.ini"
    path.write_text("[carvera]\nexisting = kept\n\n[graphics]\nwidth = 900\n", encoding="utf-8")
    parser = ConfigParser()
    parser.read(str(path))
    return parser


def saved(config):
    disk = configparser.RawConfigParser()
    disk.read(config.filename, encoding="utf-8")
    return {section: dict(disk.items(section)) for section in disk.sections()}


def test_write_one_saves_only_that_key(config):
    config.setdefault("carvera", "json_default", "1")
    config_write_one("carvera", "address", "192.168.1.5", config=config)
    assert saved(config) == {"carvera": {"existing": "kept", "address": "192.168.1.5"}, "graphics": {"width": "900"}}
    assert config.get("carvera", "address") == "192.168.1.5"


def test_defaults_set_in_memory_are_never_saved(config):
    config.setdefault("carvera", "json_default", "1")
    config_write_one("carvera", "address", "x", config=config)
    assert "json_default" not in saved(config)["carvera"]
    assert config.get("carvera", "json_default") == "1"


def test_write_many_creates_missing_sections(config):
    config_write_many({"kivy": {"exit_on_escape": "0"}, "carvera": {"version": "1.0"}}, config=config)
    data = saved(config)
    assert data["kivy"] == {"exit_on_escape": "0"}
    assert data["carvera"]["version"] == "1.0"
    assert config.get("kivy", "exit_on_escape") == "0"


def test_non_string_values_are_saved_as_strings(config):
    config_write_one("graphics", "height", 1440, config=config)
    assert saved(config)["graphics"]["height"] == "1440"


def test_write_keeps_changes_made_to_the_file_since_it_was_read(config):
    # Another key saved directly to the file must survive a later single-key write.
    pathlib.Path(config.filename).write_text("[carvera]\nexisting = kept\nother = 1\n", encoding="utf-8")
    config_write_one("carvera", "address", "x", config=config)
    assert saved(config)["carvera"] == {"existing": "kept", "other": "1", "address": "x"}


def test_remove_one_deletes_from_memory_and_file(config):
    config_remove_one("carvera", "existing", config=config)
    assert not config.has_option("carvera", "existing")
    assert "existing" not in saved(config)["carvera"]


def test_remove_missing_key_is_harmless(config):
    config_remove_one("carvera", "missing", config=config)
    config_remove_one("nosection", "missing", config=config)
    assert saved(config)["carvera"] == {"existing": "kept"}


def test_without_a_file_only_memory_changes():
    parser = ConfigParser()
    assert config_write_one("carvera", "address", "x", config=parser) is False
    assert parser.get("carvera", "address") == "x"


def test_write_runs_config_callbacks(config):
    seen = []
    config.add_callback(lambda section, key, value: seen.append((section, key, value)), "carvera", "address")
    config_write_one("carvera", "address", "x", config=config)
    assert seen == [("carvera", "address", "x")]


def test_package_never_saves_the_whole_config():
    # Config.write() would freeze every in-memory default into config.ini.
    pattern = re.compile(r"\bConfig\.write\(")
    offenders = [
        f"{path.relative_to(PACKAGE_DIR)}:{number}"
        for path in PACKAGE_DIR.rglob("*.py")
        if path.name != "config_store.py"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line) and not line.lstrip().startswith("#")
    ]
    assert offenders == [], "Use config_store helpers instead of Config.write(): " + ", ".join(offenders)
