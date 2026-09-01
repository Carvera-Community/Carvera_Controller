# -*- coding: ascii -*-
# $Id$
#
# Author:	Vasilis.Vlachoudis@cern.ch
# Date:	16-Apr-2015

__author__ = "Vasilis Vlachoudis"
__email__ = "vvlachoudis@gmail.com"

import calendar
import hashlib
import os
import sys
import time

try:
    import ConfigParser
except ImportError:
    import configparser as ConfigParser

import gettext

try:
    import __builtin__
except:
    import builtins as __builtin__
    # __builtin__.unicode = str		# dirty hack for python3

try:
    import serial
except:
    serial = None

from datetime import datetime

__prg__ = "bCNC"
__tool__ = "TOOL"
prgpath = os.path.abspath(os.path.dirname(sys.argv[0]))
iniSystem = os.path.join(prgpath, "%s.ini" % (__prg__))
iniUser = os.path.expanduser("~/.%s" % (__prg__))
hisFile = os.path.expanduser("~/.%s.history" % (__prg__))
iniTool = os.path.expanduser("~/.%s" % (__tool__))

# dirty way of substituting the "_" on the builtin namespace
# __builtin__.__dict__["_"] = gettext.translation('bCNC', 'locale', fallback=True).ugettext
__builtin__._ = gettext.translation("bCNC", os.path.join(prgpath, "locale"), fallback=True).gettext
__builtin__.N_ = lambda message: message


icons = {}
images = {}
config = ConfigParser.ConfigParser()
toolconfig = ConfigParser.ConfigParser()
language = ""

_errorReport = True
errors = []
_maxRecent = 10

_FONT_SECTION = "Font"


# New class to provide config for everyone
# FIXME: create single instance of this and pass it to all parts of application
class Config:
    def greet(self, who=__name__):
        print("Config class loaded in %s" % (who))


# ------------------------------------------------------------------------------
# Load configuration
# ------------------------------------------------------------------------------
def loadConfiguration(systemOnly=False):
    global config, _errorReport, language
    if systemOnly:
        config.read(iniSystem)
    else:
        config.read([iniSystem, iniUser])
        _errorReport = getInt("Connection", "errorreport", 1)

        language = getStr(__prg__, "language")
        if language:
            # replace language
            __builtin__._ = gettext.translation(
                "bCNC", os.path.join(prgpath, "locale"), fallback=True, languages=[language]
            ).gettext


# ------------------------------------------------------------------------------
# Save configuration file
# ------------------------------------------------------------------------------
def saveConfiguration():
    global config
    cleanConfiguration()
    f = open(iniUser, "w")
    config.write(f)
    f.close()


# ----------------------------------------------------------------------
# Remove items that are the same as in the default ini
# ----------------------------------------------------------------------
def cleanConfiguration():
    global config
    newconfig = config  # Remember config
    config = ConfigParser.ConfigParser()

    loadConfiguration(True)

    # Compare items
    for section in config.sections():
        for item, value in config.items(section):
            try:
                new = newconfig.get(section, item)
                if value == new:
                    newconfig.remove_option(section, item)
            except ConfigParser.NoOptionError:
                pass
    config = newconfig


# ------------------------------------------------------------------------------
# Load tool config
# ------------------------------------------------------------------------------
def loadToolConfig():
    global toolconfig
    toolconfig.read(iniTool)


# ------------------------------------------------------------------------------
# Save tool config
# ------------------------------------------------------------------------------
def saveToolConfig():
    global toolconfig
    f = open(iniTool, "w")
    toolconfig.write(f)
    f.close()


# ------------------------------------------------------------------------------
# add section if it doesn't exist
# ------------------------------------------------------------------------------
def addSection(section):
    global config
    if not config.has_section(section):
        config.add_section(section)


# ------------------------------------------------------------------------------
def getStr(section, name, default=""):
    global config
    try:
        return config.get(section, name)
    except:
        return default


# ------------------------------------------------------------------------------
def getUtf(section, name, default=""):
    global config
    try:
        return config.get(section, name).decode("utf8")
    except:
        return default


# ------------------------------------------------------------------------------
def getInt(section, name, default=0):
    global config
    try:
        return int(config.get(section, name))
    except:
        return default


# ------------------------------------------------------------------------------
def getFloat(section, name, default=0.0):
    global config
    try:
        return float(config.get(section, name))
    except:
        return default


# ------------------------------------------------------------------------------
def getBool(section, name, default=False):
    global config
    try:
        return bool(int(config.get(section, name)))
    except:
        return default


# ------------------------------------------------------------------------------
def getToolInt(section, name, default=0):
    global toolconfig
    try:
        return int(toolconfig.get(section, name))
    except:
        return default


# ------------------------------------------------------------------------------
def getToolFloat(section, name, default=0.0):
    global toolconfig
    try:
        return float(toolconfig.get(section, name))
    except:
        return default


# ------------------------------------------------------------------------------
def setToolStr(section, name, value):
    global toolconfig
    if not toolconfig.has_section(section):
        toolconfig.add_section(section)
    toolconfig.set(section, name, str(value))


# -------------------------------------------------------------------------------
# Set font in configuration
# -------------------------------------------------------------------------------
def setFont(name, font):
    if font is None:
        return
    if isinstance(font, str):
        config.set(_FONT_SECTION, name, font)
    elif isinstance(font, tuple):
        config.set(_FONT_SECTION, name, ",".join(map(str, font)))
    else:
        config.set(_FONT_SECTION, name, "%s,%s,%s" % (font.cget("family"), font.cget("size"), font.cget("weight")))


# ------------------------------------------------------------------------------
def setBool(section, name, value):
    global config
    config.set(section, name, str(int(value)))


# ------------------------------------------------------------------------------
def setStr(section, name, value):
    global config
    config.set(section, name, str(value))


# ------------------------------------------------------------------------------
def setUtf(section, name, value):
    global config
    try:
        s = str(value.encode("utf8"))
    except:
        s = str(value)
    config.set(section, name, s)


setInt = setStr
setFloat = setStr


# -------------------------------------------------------------------------------
# Add Recent
# -------------------------------------------------------------------------------
def addRecent(filename):
    try:
        sfn = str(os.path.abspath(filename))
    except UnicodeEncodeError:
        sfn = filename.encode("utf8")

    last = _maxRecent - 1
    for i in range(_maxRecent):
        rfn = getRecent(i)
        if rfn is None:
            last = i - 1
            break
        if rfn == sfn:
            if i == 0:
                return
            last = i - 1
            break

    # Shift everything by one
    for i in range(last, -1, -1):
        config.set("File", "recent.%d" % (i + 1), getRecent(i))
    config.set("File", "recent.0", sfn)


# -------------------------------------------------------------------------------
def getRecent(recent):
    try:
        return config.get("File", "recent.%d" % (recent))
    except ConfigParser.NoOptionError:
        return None


# ------------------------------------------------------------------------------
# Return all comports when serial.tools.list_ports is not available!
# ------------------------------------------------------------------------------
def comports(include_links=True):
    locations = ["/dev/ttyACM", "/dev/ttyUSB", "/dev/ttyS", "com"]

    comports = []
    for prefix in locations:
        for i in range(32):
            device = "%s%d" % (prefix, i)
            try:
                os.stat(device)
                comports.append((device, None, None))
            except OSError:
                pass

            # Detects windows XP serial ports
            try:
                s = serial.Serial(device)
                s.close()
                comports.append((device, None, None))
            except:
                pass
    return comports


# ------------------------------------------------------------------------------
# USB serial identity helpers (VID:PID + optional serial), independent of COM path.
# ------------------------------------------------------------------------------
def usb_device_id_from_port(port):
    """
    Build a USB device type id from a pyserial ListPortInfo-like object.

    Format: ``VID:PID`` (hex). Returns None if the port is not a USB device
    (Bluetooth/debug ports without VID/PID, etc.).
    """
    vid = getattr(port, "vid", None)
    pid = getattr(port, "pid", None)
    if vid is None or pid is None:
        return None
    return f"{int(vid):04X}:{int(pid):04X}"


def usb_device_label_from_port(port):
    """Dropdown label: USB serial number when present, else a short product name."""
    serial_number = (getattr(port, "serial_number", None) or "").strip()
    if serial_number:
        return serial_number
    return (getattr(port, "product", None) or getattr(port, "description", None) or "USB serial").strip()


def usb_port_short_name(device_path):
    """Short OS path for disambiguation (COM3, ttyUSB0, cu.usbserial-...)."""
    if not device_path:
        return ""
    name = os.path.basename(device_path.replace("\\", "/"))
    return name or device_path


def same_usb_device_path(a, b):
    """Compare serial / USB bulk device paths; case-insensitive on Windows (COM3 vs com3)."""
    if not a or not b:
        return False
    from .USBBulkStream import is_usb_bulk_address

    if is_usb_bulk_address(a) or is_usb_bulk_address(b):
        return a.casefold() == b.casefold()
    if sys.platform.startswith("win"):
        return a.lower() == b.lower()
    return a == b


def same_usb_serial(a, b):
    """Compare USB serial strings case-insensitively (OS reporting varies)."""
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return False
    return a.casefold() == b.casefold()


def parse_usb_device_id(device_id):
    """
    Normalize a stored device id to ``(vid_pid, serial_or_empty)``.

    Accepts ``VID:PID`` or legacy ``VID:PID:SERIAL``.
    """
    if not device_id:
        return None, ""
    parts = device_id.strip().split(":")
    if len(parts) < 2:
        return None, ""
    vid_pid = f"{parts[0].upper()}:{parts[1].upper()}"
    serial = parts[2].strip() if len(parts) >= 3 else ""
    return vid_pid, serial


def list_identifiable_usb_serial_ports(port_iter=None):
    """
    List USB serial ports that have a VID/PID.

    Returns a list of dicts: device_path, device_id, label, vid, pid, serial.

    On macOS pyserial returns ``/dev/cu.*`` callout devices (correct for open).
    On Linux ``/dev/ttyUSB*`` / ``/dev/ttyACM*``. On Windows ``COMn``.
    Duplicate labels (common when serial is missing) get a short path suffix.
    """
    if port_iter is None:
        try:
            from serial.tools.list_ports import comports as list_ports_comports
        except ImportError:
            return []
        # include_links=False avoids duplicate /dev/serial/by-id entries on Linux.
        port_iter = list_ports_comports()

    devices = []
    for port in port_iter:
        device_id = usb_device_id_from_port(port)
        if not device_id:
            continue
        devices.append(
            {
                "device_path": port.device,
                "device_id": device_id,
                "label": usb_device_label_from_port(port),
                "vid": int(port.vid),
                "pid": int(port.pid),
                "serial": (getattr(port, "serial_number", None) or "").strip(),
                "transport": "serial",
            }
        )

    return _disambiguate_usb_device_labels(devices)


def _disambiguate_usb_device_labels(devices):
    """Disambiguate identical labels (empty/cloned serials) with the OS short name."""
    label_counts = {}
    for entry in devices:
        label_counts[entry["label"]] = label_counts.get(entry["label"], 0) + 1
    for entry in devices:
        if label_counts[entry["label"]] > 1:
            short = usb_port_short_name(entry["device_path"])
            if short and short != entry["label"]:
                entry["label"] = f"{entry['label']} ({short})"

    devices.sort(key=lambda d: (d["label"].lower(), d["device_path"].lower()))
    return devices


def list_identifiable_usb_devices(port_iter=None, bulk_devices=None):
    """
    List USB serial ports and vendor-class bulk devices (e.g. Makera Z1).

    Bulk devices already exposed as OS serial ports are omitted. When
    ``port_iter`` is provided (tests), live USB bulk scanning is skipped unless
    ``bulk_devices`` is passed explicitly.
    """
    from .USBBulkStream import list_usb_bulk_devices, merge_usb_device_lists

    serial_devices = list_identifiable_usb_serial_ports(port_iter=port_iter)
    if bulk_devices is None:
        bulk_devices = [] if port_iter is not None else list_usb_bulk_devices()
    return _disambiguate_usb_device_labels(merge_usb_device_lists(serial_devices, bulk_devices))


def find_usb_device_path_by_id(device_id=None, serial=None, port_iter=None, bulk_devices=None):
    """
    Resolve a stored USB identity to the current OS path.

    Prefers VID/PID + serial when available. If only a serial is known, matches
    that serial across USB ports. Falls back to the first VID/PID match.
    """
    vid_pid, legacy_serial = parse_usb_device_id(device_id) if device_id else (None, "")
    prefer_serial = (serial or legacy_serial or "").strip()
    devices = list_identifiable_usb_devices(port_iter=port_iter, bulk_devices=bulk_devices)

    if prefer_serial:
        serial_matches = [entry for entry in devices if same_usb_serial(entry["serial"], prefer_serial)]
        if vid_pid:
            for entry in serial_matches:
                if entry["device_id"].upper() == vid_pid.upper():
                    return entry["device_path"]
        elif serial_matches:
            return serial_matches[0]["device_path"]

    if not vid_pid:
        return None
    matches = [entry for entry in devices if entry["device_id"].upper() == vid_pid.upper()]
    if not matches:
        return None
    return matches[0]["device_path"]


suffixes = ["B", "KB", "MB", "GB", "TB", "PB"]


# ------------------------------------------------------------------------------
# Return readable size string
# ------------------------------------------------------------------------------
def humansize(nbytes):
    nbytes = int(nbytes)
    i = 0
    while nbytes >= 1024 and i < len(suffixes) - 1:
        nbytes /= 1024.0
        i += 1
    f = ("%.2f" % nbytes).rstrip("0").rstrip(".")
    return "%s %s" % (f, suffixes[i])


# ------------------------------------------------------------------------------
# Return readable date string
# ------------------------------------------------------------------------------
def humandate(date):
    return datetime.fromtimestamp(date).strftime("%Y-%m-%d %H:%M")


# ------------------------------------------------------------------------------
# Unix timestamp of the current local wall-clock time, including DST.
#
# The machine stores SD card timestamps in local time with no timezone.
# time.timezone is the standard-time offset only, so int(time.time()) -
# time.timezone is one hour off while daylight saving is in effect.
# calendar.timegm(time.localtime()) encodes the current local clock
# (standard or DST) as a Unix timestamp.
# ------------------------------------------------------------------------------
def local_unix_time():
    return calendar.timegm(time.localtime())


# ------------------------------------------------------------------------------
# Return hours, minutes, seconds from seconds
# ------------------------------------------------------------------------------
def second2hour(seconds):
    total_seconds = int(seconds)
    hour = total_seconds // 3600
    total_seconds = total_seconds % 3600
    minute = total_seconds // 60
    total_seconds = total_seconds % 60
    second = total_seconds
    ret_value = str(second) + "s"
    if minute > 0:
        ret_value = str(minute) + "m" + ret_value
    if hour > 0:
        ret_value = str(hour) + "h" + ret_value
    return ret_value


# ------------------------------------------------------------------------------
# Return md5 of a file
# ------------------------------------------------------------------------------
def md5(filename):
    hash_md5 = hashlib.md5()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


# ------------------------------------------------------------------------------
# Return float array
# ------------------------------------------------------------------------------
def xfrange(start, stop, steps):
    if steps <= 1:
        return
    interval = (stop - start) / (steps - 1)
    i = 0
    if interval == 0:
        for i in range(steps):
            yield start
    else:
        while start + i * interval <= stop:
            yield start + i * interval
            i += 1


# ------------------------------------------------------------------------------
# Return float array
# ------------------------------------------------------------------------------
def translate(value, leftMin, leftMax, rightMin, rightMax):
    # Figure out how 'wide' each range is
    leftSpan = leftMax - leftMin
    rightSpan = rightMax - rightMin

    # Convert the left range into a 0-1 range (float)
    valueScaled = float(value - leftMin) / float(leftSpan)

    # Convert the 0-1 range into a value in the right range.
    return rightMin + (valueScaled * rightSpan)


# ------------------------------------------------------------------------------
# convert from config string to panel value
# ------------------------------------------------------------------------------
def from_config(type, value_string):
    if type == "bool":
        if value_string.lower() == "true":
            return 1
        return 0
    if type == "numeric":
        return float(value_string)
    return value_string


# ------------------------------------------------------------------------------
# convert from config string
# ------------------------------------------------------------------------------
def to_config(type, value_string):
    if type == "bool":
        if value_string.lower() == "1":
            return "true"
        return "false"
    return value_string


def directory_breadcrumb_paths(
    directory,
    *,
    root_label_markers=("",),
    root_label="root",
    max_ancestors=5,
):
    """Build (full_paths, labels) for a clickable directory breadcrumb bar."""
    import string

    directory = os.path.normpath(directory) if directory else ""
    if not directory:
        return [], []

    win_drivers = ["%s:" % d for d in string.ascii_uppercase]
    win_drivers_slash = ["%s:\\" % d for d in string.ascii_uppercase]
    markers = tuple(root_label_markers)

    def segment_label(path):
        if path in win_drivers or path in win_drivers_slash:
            return path
        name = os.path.basename(path) if path else ""
        if name in markers:
            return root_label
        return name

    full_paths = [directory]
    path_labels = [segment_label(directory)]
    last_parent_dir = directory

    for _ in range(max_ancestors):
        parent_dir = os.path.dirname(last_parent_dir)
        if not last_parent_dir or last_parent_dir == parent_dir:
            break
        full_paths.insert(0, parent_dir)
        if parent_dir in win_drivers or parent_dir in win_drivers_slash:
            path_labels.insert(0, parent_dir)
        else:
            path_labels.insert(0, segment_label(parent_dir))
        last_parent_dir = parent_dir

    if path_labels and path_labels[0] in markers:
        path_labels[0] = root_label

    return full_paths, path_labels


RECENT_LOCAL_DIR_SLOTS = 5


def has_all_files_access():
    """Return whether Android all-files access is granted (always True elsewhere)."""
    import logging

    from kivy.utils import platform as kivy_platform

    if kivy_platform != "android":
        return True
    try:
        from jnius import autoclass

        Environment = autoclass("android.os.Environment")
        return Environment.isExternalStorageManager()
    except Exception as e:
        logging.getLogger(__name__).error("Error checking storage manager status: %s", e)
        return False


def request_android_permissions():
    """On Android, open system UI to grant all-files access if missing."""
    import logging

    from kivy.utils import platform as kivy_platform

    if kivy_platform != "android":
        return
    logger = logging.getLogger(__name__)
    try:
        if has_all_files_access():
            logger.info("Already have all files access permission")
            return
        from android import mActivity
        from jnius import autoclass

        Intent = autoclass("android.content.Intent")
        Settings = autoclass("android.provider.Settings")
        intent = Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
        mActivity.startActivity(intent)
    except Exception as e:
        logger.error("Error requesting permissions: %s", e)


def common_local_directories():
    """Return standard local folder shortcuts (home, Documents, drives, ...)."""
    import logging
    import string
    from pathlib import Path

    from kivy.utils import platform as kivy_platform

    from carveracontroller.translation import tr

    logger = logging.getLogger(__name__)
    entries = []
    home_path = Path.home()
    if home_path.exists():
        entries.append(
            {
                "name": os.path.basename(home_path),
                "path": str(home_path),
                "icon": "data/folder-home.png",
            }
        )
    for sub, icon in (
        ("Documents", "data/folder-documents.png"),
        ("Downloads", "data/folder-downloads.png"),
        ("Desktop", "data/folder-desktop.png"),
    ):
        folder = home_path.joinpath(sub)
        if folder.exists():
            entries.append({"name": tr._(sub), "path": str(folder), "icon": icon})

    if kivy_platform == "android":
        logger.info("Android storage permission check")
        try:
            from android.storage import primary_external_storage_path

            request_android_permissions()
            android_storage_path = primary_external_storage_path()
            if android_storage_path and os.path.exists(android_storage_path):
                entries.append(
                    {
                        "name": tr._("Storage"),
                        "path": str(android_storage_path),
                        "icon": "data/folder-home.png",
                    }
                )
        except Exception as e:
            logger.error("Get Android Storage Error: %s", e)

    for drive in ["%s:" % d for d in string.ascii_uppercase if os.path.exists("%s:" % d)]:
        entries.append({"name": drive, "path": drive, "icon": ""})

    return entries


def load_recent_local_directories(*, seed_if_empty=True):
    """Load recent local directories from Kivy Config (optionally seed defaults)."""
    from kivy.config import Config
    from kivy.utils import platform as kivy_platform

    dirs = []
    if Config.has_section("carvera"):
        for index in range(RECENT_LOCAL_DIR_SLOTS):
            key = "local_folder_" + str(index + 1)
            if Config.has_option("carvera", key):
                folder = Config.get("carvera", key)
                if folder:
                    dirs.append(folder)

    if seed_if_empty and not dirs:
        if kivy_platform == "android":
            default = str(os.path.abspath("carveracontroller/gcodes"))
        else:
            default = str(os.path.abspath("./gcodes"))
        dirs = update_recent_local_directory_list(dirs, default)
        persist_recent_local_directories(dirs)

    return dirs


def update_recent_local_directory_list(dirs, new_dir):
    """Return dirs with new_dir moved to the front (max RECENT_LOCAL_DIR_SLOTS)."""
    dirs = list(dirs)
    if new_dir in dirs:
        if dirs[0] == new_dir:
            return dirs
        dirs.remove(new_dir)
    dirs.insert(0, new_dir)
    del dirs[RECENT_LOCAL_DIR_SLOTS:]
    return dirs


def persist_recent_local_directories(dirs):
    """Write recent local directories to Kivy Config."""
    from kivy.config import Config

    for index in range(RECENT_LOCAL_DIR_SLOTS):
        key = "local_folder_" + str(index + 1)
        if index < len(dirs):
            Config.set("carvera", key, dirs[index])
        else:
            Config.set("carvera", key, "")
    Config.write()


def record_recent_local_directory(new_dir):
    """Promote a directory to the top of the shared recent-local list."""
    dirs = load_recent_local_directories(seed_if_empty=True)
    dirs = update_recent_local_directory_list(dirs, new_dir)
    persist_recent_local_directories(dirs)
    return dirs


def fill_local_dir_dropdown(dropdown, common_dirs, recent_dirs):
    """Populate a DropDown with common and recent local directories."""
    from carveracontroller.translation import tr
    from carveracontroller.ui.DirectoryView import DirectoryView
    from carveracontroller.ui.DropDownSplitter import DropDownSplitter

    dropdown.clear_widgets()

    for common_dir in common_dirs:
        btn = DirectoryView(
            full_path=common_dir["path"],
            data_text=common_dir["name"],
            data_icon=common_dir["icon"],
            size_hint_y=None,
            height="30dp",
        )
        path = common_dir["path"]
        btn.bind(on_release=lambda _btn, p=path: dropdown.select(p))
        dropdown.add_widget(btn)

    dropdown.add_widget(DropDownSplitter(text="       " + tr._("Recent Places")))

    for recent_dir in recent_dirs:
        btn = DirectoryView(
            full_path=recent_dir,
            data_text=os.path.basename(recent_dir),
            data_icon="",
            size_hint_y=None,
            height="30dp",
        )
        btn.bind(on_release=lambda _btn, p=recent_dir: dropdown.select(p))
        dropdown.add_widget(btn)


def digitize_v(version):
    if not version:
        return 0
    # Strip pre-release suffixes (-RC1, etc.) before parsing numeric components.
    base_version = version.split("-", 1)[0]
    v_list = base_version.split(".")
    cleaned_parts = []
    for part in v_list:
        # Extract only the numeric portion at the beginning
        numeric_part = ""
        for char in part:
            if char.isdigit():
                numeric_part += char
            else:
                break
        cleaned_parts.append(int(numeric_part if numeric_part else "0"))

    # Ensure we have at least 3 parts (major.minor.patch)
    while len(cleaned_parts) < 3:
        cleaned_parts.append(0)

    return cleaned_parts[0] * 1000 * 1000 + cleaned_parts[1] * 1000 + cleaned_parts[2]
