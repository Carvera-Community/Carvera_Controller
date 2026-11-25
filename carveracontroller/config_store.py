"""Save individual settings to the Kivy config file.

Kivy's ``Config.write()`` saves the whole in-memory Config, including every
default the settings loaders add with ``Config.setdefault()``. Those defaults
would then be frozen in config.ini and a later release could not change them.

The rule is to never call ``Config.write()``. Use these helpers instead: they
update the in-memory Config as usual and save only the keys that changed.
"""

import configparser
import logging
import os

from kivy.config import Config

logger = logging.getLogger(__name__)


def config_write_one(section, key, value, config=Config):
    """Set one value in memory and save only that key to the config file."""
    return config_write_many({section: {key: value}}, config=config)


def config_write_many(values, config=Config):
    """Set several values, given as ``{section: {key: value}}``, and save only those keys."""
    for section, items in values.items():
        if not config.has_section(section):
            config.add_section(section)
        for key, value in items.items():
            config.set(section, key, value)
    return _update_file(config, set_values=values)


def config_remove_one(section, key, config=Config):
    """Remove one key from memory and from the config file."""
    if config.has_option(section, key):
        config.remove_option(section, key)
    return _update_file(config, remove_keys=[(section, key)])


def _update_file(config, set_values=None, remove_keys=()):
    path = getattr(config, "filename", None)
    if not path:
        return False
    disk = configparser.RawConfigParser()
    try:
        if os.path.exists(path):
            disk.read(path, encoding="utf-8-sig")
        for section, items in (set_values or {}).items():
            if not disk.has_section(section):
                disk.add_section(section)
            for key, value in items.items():
                disk.set(section, key, value if isinstance(value, str) else str(value))
        for section, key in remove_keys:
            if disk.has_section(section):
                disk.remove_option(section, key)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fd:
            disk.write(fd)
        os.replace(tmp_path, path)
    except (OSError, configparser.Error):
        logger.exception(f"Unable to save settings to {path}")
        return False
    return True
