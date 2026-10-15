"""Unit tests for file browser listing, grouping, and action state."""

import importlib
import logging
import os
import threading
from queue import Queue
from types import SimpleNamespace
from unittest.mock import MagicMock

from carveracontroller.Controller import LOAD_DIR
from carveracontroller.main import Makera, transfer_confirm_message
from carveracontroller.ui.file_browser.FileBrowserPopup import FileBrowserPopup
from carveracontroller.ui.file_browser.sources import (
    ICON_FILE,
    ICON_FIRMWARE,
    ICON_FOLDER,
    ICON_GCODE,
    KIND_FILE,
    KIND_FOLDER,
    LOCATION_DEVICE,
    LOCATION_MACHINE,
    compute_action_state,
    current_file_banner,
    current_row_badge,
    device_tab_path_display,
    download_dest_tooltip,
    editor_display_name,
    file_type_key,
    file_type_label,
    group_and_sort_entries,
    is_compact_width,
    is_editable_gcode_name,
    is_gcode_machine_dir,
    is_job_file,
    is_machine_root,
    is_machine_video_path,
    is_under_machine_root,
    is_videos_dir,
    list_device_directory,
    listing_has_directory,
    local_child_path,
    local_dir_has_file,
    local_sibling_path,
    machine_child_entry_path,
    machine_listing_callback_matches,
    machine_listing_has,
    machine_listing_is_current,
    machine_location_places,
    machine_ls_is_superseded,
    machine_parent_dir,
    machine_path_display,
    machine_tab_path_display,
    mkdir_local,
    remove_local_path,
    rename_local_path,
    row_icon,
    trim_breadcrumb_pairs,
    upload_dest_tooltip,
)
from carveracontroller.updater.backup import DEFAULT_BACKUP_PATHS

file_browser_popup = importlib.import_module("carveracontroller.ui.file_browser.FileBrowserPopup")

IDENTITY = lambda text: text  # noqa: E731


def _entry(name, *, is_dir=False, size=10, date=100, path=None):
    return {
        "name": name,
        "path": path or f"/sd/gcodes/{name}",
        "is_dir": is_dir,
        "size": 0 if is_dir else size,
        "date": date,
    }


def test_file_type_key_and_label():
    assert file_type_key("part.nc") == "gcode"
    assert file_type_key("job.gcode") == "gcode"
    assert file_type_key("fw.bin") == "firmware"
    assert file_type_key("job.lz") == "compressed"
    assert file_type_key("notes.txt") == "other"
    assert file_type_label("part.nc", translate=IDENTITY) == "G-code"
    assert file_type_label("fw.bin", translate=IDENTITY) == "Firmware"


def test_editable_gcode_name_and_display():
    assert is_editable_gcode_name("part.nc") is True
    assert is_editable_gcode_name("part.nc.lz") is True
    assert is_editable_gcode_name("fw.bin") is False
    assert is_editable_gcode_name("notes.txt") is False
    assert editor_display_name("/sd/gcodes/part.nc.lz") == "part.nc"
    assert editor_display_name("/sd/gcodes/part.nc") == "part.nc"


def test_row_icon_by_kind_and_type():
    assert row_icon(KIND_FOLDER, "tools") == ICON_FOLDER
    assert row_icon(KIND_FILE, "part.nc") == ICON_GCODE
    assert row_icon(KIND_FILE, "fw.bin") == ICON_FIRMWARE
    assert row_icon(KIND_FILE, "notes.txt") == ICON_FILE
    assert row_icon(KIND_FILE, "job.lz") == ICON_FILE


def test_group_and_sort_puts_folders_above_files():
    entries = [
        _entry("b.nc", date=20, size=200),
        _entry("alpha", is_dir=True, date=10),
        _entry("a.nc", date=30, size=50),
        _entry("zeta", is_dir=True, date=40),
    ]
    rows = group_and_sort_entries(entries, sort_key="name", reverse=False, translate=IDENTITY)
    kinds = [row["kind"] for row in rows]
    names = [row["filename"] for row in rows]
    assert kinds == [KIND_FOLDER, KIND_FOLDER, KIND_FILE, KIND_FILE]
    assert names == ["alpha", "zeta", "a.nc", "b.nc"]


def test_group_sort_by_date_and_size():
    entries = [
        _entry("old.nc", date=1, size=999),
        _entry("new.nc", date=50, size=1),
    ]
    by_date = group_and_sort_entries(entries, sort_key="date", reverse=True, translate=IDENTITY)
    file_names = [row["filename"] for row in by_date if row["kind"] == KIND_FILE]
    assert file_names == ["new.nc", "old.nc"]
    by_size = group_and_sort_entries(entries, sort_key="size", reverse=True, translate=IDENTITY)
    file_names = [row["filename"] for row in by_size if row["kind"] == KIND_FILE]
    assert file_names == ["old.nc", "new.nc"]


def test_firmware_mode_keeps_dirs_and_bin_only():
    entries = [
        _entry("keep", is_dir=True),
        _entry("fw.bin"),
        _entry("job.nc"),
    ]
    rows = group_and_sort_entries(entries, firmware_mode=True, translate=IDENTITY)
    names = [row["filename"] for row in rows]
    assert names == ["keep", "fw.bin"]


def test_search_filters_by_name():
    entries = [_entry("bracket.nc"), _entry("lid.nc"), _entry("tools", is_dir=True)]
    rows = group_and_sort_entries(entries, keyword="lid", translate=IDENTITY)
    names = [row["filename"] for row in rows]
    assert names == ["lid.nc"]


def test_current_job_badge_and_selection():
    entries = [_entry("job.nc", path="/sd/gcodes/job.nc")]
    rows = group_and_sort_entries(
        entries,
        current_job_path="/sd/gcodes/job.nc",
        highlight_path="/sd/gcodes/job.nc",
        translate=IDENTITY,
    )
    file_row = next(row for row in rows if row["kind"] == KIND_FILE)
    assert file_row["is_current_job"] is True
    assert file_row["current_badge"] == "Selected"
    assert file_row["selected"] is True
    assert "G-code" in file_row["subtitle"]
    assert file_row["thumbnail"] == ""


def test_current_preview_badge():
    entries = [_entry("part.cnc", path="/home/me/part.cnc")]
    rows = group_and_sort_entries(
        entries,
        current_job_path="/home/me/part.cnc",
        current_is_preview=True,
        translate=IDENTITY,
    )
    file_row = next(row for row in rows if row["kind"] == KIND_FILE)
    assert file_row["is_current_job"] is True
    assert file_row["current_badge"] == "Selected (Preview)"
    other = group_and_sort_entries(entries, translate=IDENTITY)
    assert next(row for row in other if row["kind"] == KIND_FILE)["current_badge"] == ""
    assert current_row_badge(is_current=True, is_preview=False, translate=IDENTITY) == "Selected"
    assert current_row_badge(is_current=True, is_preview=True, translate=IDENTITY) == "Selected (Preview)"
    assert current_row_badge(is_current=False, is_preview=True, translate=IDENTITY) == ""


def test_row_passes_through_thumbnail_for_files_only():
    entries = [
        _entry("tools", is_dir=True),
        _entry("job.nc", path="/sd/gcodes/job.nc"),
    ]
    entries[1]["thumbnail"] = "/tmp/job.png"
    entries[0]["thumbnail"] = "/tmp/should-ignore.png"
    rows = group_and_sort_entries(entries, translate=IDENTITY)
    folder = next(row for row in rows if row["kind"] == KIND_FOLDER)
    file_row = next(row for row in rows if row["kind"] == KIND_FILE)
    assert folder["thumbnail"] == ""
    assert file_row["thumbnail"] == "/tmp/job.png"


def test_current_file_banner_source_and_clear():
    assert current_file_banner("/sd/gcodes/job.nc", "", translate=IDENTITY) == (
        "job.nc",
        "Machine",
        True,
    )
    assert current_file_banner("", "/home/me/part.cnc", translate=IDENTITY) == (
        "part.cnc",
        "Local (Preview)",
        True,
    )
    assert current_file_banner("", "", translate=IDENTITY) == ("None", "", False)
    name, badge, can_clear = current_file_banner("/sd/gcodes/on-machine.nc", "/tmp/local.nc", translate=IDENTITY)
    assert (name, badge, can_clear) == ("on-machine.nc", "Machine", True)


def test_file_rows_include_type_size_date():
    rows = group_and_sort_entries([_entry("part.nc", size=2048, date=1_700_000_000)], translate=IDENTITY)
    file_row = next(row for row in rows if row["kind"] == KIND_FILE)
    assert file_row["file_type"] == "G-code"
    assert file_row["filesize"]
    assert file_row["filedate"]
    assert file_row["subtitle"].startswith("G-code")
    assert file_row["icon"] == ICON_GCODE


def test_machine_listing_has_ignores_directories():
    entries = [_entry("job.nc"), _entry("job.nc", is_dir=True, path="/sd/gcodes/job.nc/")]
    entries[1]["name"] = "tools"
    assert machine_listing_has(entries, "job.nc") is True
    assert machine_listing_has(entries, "missing.nc") is False
    assert machine_listing_has([_entry("tools", is_dir=True)], "tools") is False


def test_machine_root_and_parent():
    assert is_machine_root("/sd/gcodes")
    assert is_machine_root("/sd/gcodes/")
    assert is_machine_root("/sd/videos")
    assert is_machine_root("/sd/videos/")
    assert machine_parent_dir("/sd/gcodes") is None
    assert machine_parent_dir("/sd/videos") is None
    assert machine_parent_dir("/sd/gcodes/jobs") == "/sd/gcodes"
    assert machine_parent_dir("/sd/videos/job") == "/sd/videos"
    assert is_under_machine_root("/sd/gcodes")
    assert is_under_machine_root("/sd/gcodes/jobs/batch")
    assert is_under_machine_root("\\sd\\gcodes\\jobs")
    assert is_under_machine_root("/sd/videos")
    assert is_under_machine_root("/sd/videos/clip")
    assert is_under_machine_root("\\sd\\videos")
    assert is_under_machine_root("/sd") is False
    assert is_under_machine_root("/tmp/gcodes") is False
    assert is_gcode_machine_dir("/sd/gcodes")
    assert is_gcode_machine_dir("/sd/gcodes/jobs")
    assert is_gcode_machine_dir("\\sd\\gcodes\\jobs")
    assert is_gcode_machine_dir("/sd/videos") is False
    assert is_videos_dir("/sd/videos")
    assert is_videos_dir("/sd/videos/clip")
    assert is_videos_dir("\\sd\\videos")
    assert is_videos_dir("/sd/gcodes") is False
    assert is_machine_video_path("/sd/videos/clip.avi")
    assert is_machine_video_path("/sd/video/clip.avi")
    assert is_machine_video_path("\\sd\\videos\\job\\clip.avi")
    assert is_machine_video_path("/sd/gcodes/part.nc") is False
    assert is_machine_video_path("/sd/videocache/clip.avi") is False


def test_videos_visit_does_not_replace_the_gcodes_folder(monkeypatch):
    remembered = []
    makera = SimpleNamespace(
        recent_remote_dir_list=["/sd/videos", "/sd/gcodes/jobs"],
        update_recent_remote_dir_list=remembered.append,
        fetch_recent_remote_dir_list=lambda: None,
    )
    monkeypatch.setattr(file_browser_popup, "_makera", lambda: makera)
    popup = SimpleNamespace(firmware_mode=False, machine_dir="/sd/videos")

    FileBrowserPopup._remember_machine_dir(popup)
    popup.machine_dir = "/sd/videos/clip"
    FileBrowserPopup._remember_machine_dir(popup)
    assert remembered == []

    FileBrowserPopup._restore_machine_dir(popup)
    assert popup.machine_dir == "/sd/gcodes/jobs"

    popup.machine_dir = "/sd/gcodes/jobs"
    FileBrowserPopup._remember_machine_dir(popup)
    assert remembered == ["/sd/gcodes/jobs"]


def test_jobs_browser_falls_back_to_gcodes_when_only_videos_was_remembered(monkeypatch):
    makera = SimpleNamespace(
        recent_remote_dir_list=["/sd/videos/clip"],
        fetch_recent_remote_dir_list=lambda: None,
    )
    monkeypatch.setattr(file_browser_popup, "_makera", lambda: makera)
    popup = SimpleNamespace(machine_dir="/sd/videos")

    FileBrowserPopup._restore_machine_dir(popup)

    assert popup.machine_dir == "/sd/gcodes"


def test_videos_location_is_offered_only_when_the_directory_exists():
    assert machine_location_places(videos_available=False) == []
    assert machine_location_places(videos_available=True) == [
        ("/sd/gcodes", "G-code"),
        ("/sd/videos", "Videos"),
    ]
    entries = [
        _entry("gcodes", is_dir=True),
        _entry("videos", is_dir=True),
        _entry("videos-note.avi"),
    ]
    assert listing_has_directory(entries, "videos") is True
    assert listing_has_directory([_entry("videos")], "videos") is False
    assert listing_has_directory([], "videos") is False


def test_machine_listing_is_current_ignores_slash_style():
    assert machine_listing_is_current("/sd/gcodes/jobs", "/sd/gcodes/jobs") is True
    assert machine_listing_is_current("/sd/gcodes/jobs/", "/sd/gcodes/jobs") is True
    assert machine_listing_is_current("\\sd\\gcodes\\jobs", "/sd/gcodes/jobs") is True
    assert machine_listing_is_current("/sd/gcodes", "/sd/gcodes/jobs") is False
    assert machine_listing_is_current("/sd/gcodes/jobs", "/sd/gcodes") is False
    assert machine_listing_is_current("", "/sd/gcodes") is False
    assert machine_listing_is_current("/sd", "/sd") is True


def test_machine_ls_is_superseded_uses_wanted_path():
    assert machine_ls_is_superseded("/sd/gcodes", "/sd/gcodes") is False
    assert machine_ls_is_superseded("/sd/gcodes/", "/sd/gcodes") is False
    assert machine_ls_is_superseded("\\sd\\gcodes", "/sd/gcodes") is False
    assert machine_ls_is_superseded("/sd/gcodes", "/sd/gcodes/jobs") is True
    assert machine_ls_is_superseded("/sd/gcodes/jobs", "/sd/gcodes") is True
    assert machine_ls_is_superseded("/sd/gcodes", None) is False
    assert machine_ls_is_superseded("/sd/gcodes", "") is False
    assert machine_ls_is_superseded(None, "/sd/gcodes") is True


def test_machine_listing_callback_matches_requires_scoped_path():
    assert machine_listing_callback_matches("/sd", "/sd") is True
    assert machine_listing_callback_matches("/sd/", "/sd") is True
    assert machine_listing_callback_matches("\\sd", "/sd") is True
    assert machine_listing_callback_matches("/sd/gcodes", "/sd") is False
    assert machine_listing_callback_matches("/sd", None) is False
    assert machine_listing_callback_matches(None, "/sd") is False


def _machine_ls_host():
    root = Makera.__new__(Makera)
    root._machine_ls_lock = threading.Lock()
    root._machine_ls_wanted_path = None
    root._machine_ls_sent_path = None
    root.short_load_time = 0
    root.fill_remote_dir_callback = None
    root.fill_remote_dir_callback_path = None
    root.controller = SimpleNamespace(
        loadNUM=0,
        loadEOF=False,
        loadERR=False,
        sendNUM=0,
        load_buffer=Queue(),
        lsCommand=MagicMock(),
    )
    root.file_popup = SimpleNamespace(
        machine_dir="/sd/gcodes",
        apply_machine_listing=MagicMock(),
    )
    return root


class _ImmediateThread:
    def __init__(self, target=None, args=(), **kwargs):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


def test_request_machine_ls_coalesces_while_listing(monkeypatch):
    root = _machine_ls_host()
    monkeypatch.setattr("carveracontroller.main.threading.Thread", _ImmediateThread)
    Makera.request_machine_ls(root, "/sd/gcodes")
    Makera.request_machine_ls(root, "/sd/gcodes/jobs")
    assert root.controller.lsCommand.call_count == 1
    assert root._machine_ls_sent_path == "/sd/gcodes"
    assert root._machine_ls_wanted_path == "/sd/gcodes/jobs"
    assert root.controller.loadNUM == LOAD_DIR


def test_finish_machine_ls_chains_superseded_listing_without_error(monkeypatch):
    root = _machine_ls_host()
    scheduled = []
    processed = []
    monkeypatch.setattr("carveracontroller.main.SHORT_LOAD_TIMEOUT", 3, raising=False)
    monkeypatch.setattr("carveracontroller.main.Clock.schedule_once", lambda cb, t: scheduled.append(cb))
    monkeypatch.setattr("carveracontroller.main.threading.Thread", _ImmediateThread)
    root.process_loaded_dir = lambda path=None: processed.append(path)
    Makera.request_machine_ls(root, "/sd/gcodes")
    Makera.request_machine_ls(root, "/sd/gcodes/jobs")
    root.controller.loadEOF = True
    Makera._finish_machine_ls(root, root.short_load_time + 0.1)
    assert processed == ["/sd/gcodes"]
    assert scheduled == []
    assert root.controller.lsCommand.call_count == 2
    root.controller.lsCommand.assert_called_with("/sd/gcodes/jobs")
    assert root.controller.loadNUM == LOAD_DIR
    assert root._machine_ls_sent_path == "/sd/gcodes/jobs"


def test_finish_machine_ls_clears_state_when_listing_is_current(monkeypatch):
    root = _machine_ls_host()
    processed = []
    monkeypatch.setattr("carveracontroller.main.SHORT_LOAD_TIMEOUT", 3, raising=False)
    monkeypatch.setattr("carveracontroller.main.threading.Thread", _ImmediateThread)
    root.process_loaded_dir = lambda path=None: processed.append(path)
    Makera.request_machine_ls(root, "/sd/gcodes")
    root.controller.loadEOF = True
    Makera._finish_machine_ls(root, root.short_load_time + 0.1)
    assert processed == ["/sd/gcodes"]
    assert root.controller.loadNUM == 0
    assert root._machine_ls_sent_path is None
    assert root.controller.lsCommand.call_count == 1


def _videos_probe_host():
    root = _machine_ls_host()
    root.sd_videos_available = False
    root._sd_videos_probe_inflight = False
    root._sd_videos_probe_keep = None
    return root


def test_videos_probe_keeps_the_folder_the_browser_is_waiting_on(monkeypatch):
    root = _videos_probe_host()
    monkeypatch.setattr("carveracontroller.main.SHORT_LOAD_TIMEOUT", 3, raising=False)
    monkeypatch.setattr("carveracontroller.main.App.get_running_app", lambda: None)
    root._machine_ls_wanted_path = "/sd/gcodes"
    root.process_loaded_dir = lambda path=None: Makera._note_sd_videos_listing(
        root,
        path,
        [{"name": "videos", "is_dir": True}, {"name": "gcodes", "is_dir": True}],
    )

    Makera._run_sd_videos_probe(root)

    assert root._machine_ls_wanted_path == "/sd/gcodes"
    assert root._machine_ls_sent_path == "/sd"
    assert root._sd_videos_probe_keep == "/sd/gcodes"
    root.controller.lsCommand.assert_called_once_with("/sd")
    root.controller.loadEOF = True
    Makera._finish_machine_ls(root, root.short_load_time + 0.1)
    assert root.controller.lsCommand.call_count == 1
    assert root._machine_ls_wanted_path == "/sd/gcodes"
    assert root.controller.loadNUM == 0
    assert root.sd_videos_available is True
    assert root._sd_videos_probe_inflight is False


def test_videos_probe_does_not_replace_an_in_flight_listing(monkeypatch):
    root = _videos_probe_host()
    monkeypatch.setattr("carveracontroller.main.threading.Thread", _ImmediateThread)
    Makera.request_machine_ls(root, "/sd/gcodes")
    Makera.request_machine_ls(root, "/sd/gcodes/jobs")

    Makera._run_sd_videos_probe(root)

    assert root._machine_ls_wanted_path == "/sd/gcodes/jobs"
    assert root._machine_ls_sent_path == "/sd/gcodes"
    assert root.controller.lsCommand.call_count == 1
    assert root._sd_videos_probe_inflight is False


def test_videos_probe_yields_when_the_browser_asks_for_another_folder(monkeypatch):
    root = _videos_probe_host()
    monkeypatch.setattr("carveracontroller.main.SHORT_LOAD_TIMEOUT", 3, raising=False)
    monkeypatch.setattr("carveracontroller.main.threading.Thread", _ImmediateThread)
    root._machine_ls_wanted_path = "/sd/gcodes"
    root.process_loaded_dir = lambda path=None: None

    Makera._run_sd_videos_probe(root)
    Makera.request_machine_ls(root, "/sd/gcodes/jobs")
    root.controller.loadEOF = True
    Makera._finish_machine_ls(root, root.short_load_time + 0.1)

    assert root.controller.lsCommand.call_count == 2
    root.controller.lsCommand.assert_called_with("/sd/gcodes/jobs")
    assert root._machine_ls_sent_path == "/sd/gcodes/jobs"
    assert root.controller.loadNUM == LOAD_DIR


def test_videos_probe_failure_does_not_popup_over_the_current_folder(monkeypatch):
    root = _videos_probe_host()
    scheduled = []
    monkeypatch.setattr("carveracontroller.main.SHORT_LOAD_TIMEOUT", 3, raising=False)
    monkeypatch.setattr("carveracontroller.main.Clock.schedule_once", lambda cb, t: scheduled.append(cb))
    root._machine_ls_wanted_path = "/sd/gcodes"
    root.process_loaded_dir = lambda path=None: None

    Makera._run_sd_videos_probe(root)
    root.controller.loadERR = True
    Makera._finish_machine_ls(root, root.short_load_time + 0.1)

    assert scheduled == []
    assert root.controller.loadNUM == 0
    assert root._machine_ls_wanted_path == "/sd/gcodes"


def test_extra_worker_does_not_override_ui_wanted_path(monkeypatch):
    root = _machine_ls_host()
    monkeypatch.setattr("carveracontroller.main.SHORT_LOAD_TIMEOUT", 3, raising=False)
    monkeypatch.setattr("carveracontroller.main.threading.Thread", _ImmediateThread)
    root.process_loaded_dir = lambda path=None: None
    Makera.request_machine_ls(root, "/sd/gcodes")
    Makera.request_machine_ls(root, "/sd/gcodes/jobs")
    Makera._run_machine_ls(root)
    assert root._machine_ls_wanted_path == "/sd/gcodes/jobs"
    assert root._machine_ls_sent_path == "/sd/gcodes"
    root.controller.loadEOF = True
    Makera._finish_machine_ls(root, root.short_load_time + 0.1)
    root.controller.lsCommand.assert_called_with("/sd/gcodes/jobs")
    assert root._machine_ls_sent_path == "/sd/gcodes/jobs"


def test_fill_remote_dir_callback_only_runs_for_scoped_path(monkeypatch):
    root = _machine_ls_host()
    called = []
    root.fill_remote_dir_callback = lambda files: called.append(list(files))
    root.fill_remote_dir_callback_path = "/sd"
    monkeypatch.setattr("carveracontroller.main.threading.Thread", _ImmediateThread)
    Makera.fill_remote_dir(root, [{"name": "jobs"}], "/sd/gcodes")
    assert called == []
    assert root.fill_remote_dir_callback is not None
    Makera.fill_remote_dir(root, [{"name": "config.txt"}], "/sd")
    assert called == [[{"name": "config.txt"}]]
    assert root.fill_remote_dir_callback is None
    assert root.fill_remote_dir_callback_path is None


def test_download_config_files_downloads_silently(monkeypatch, tmp_path):
    root = Makera.__new__(Makera)
    root.temp_dir = str(tmp_path)
    root.backing_up_config = True
    calls = []

    def capture_download(remote_path, local_path, show_progress=True, open_after=True):
        calls.append(
            {
                "remote_path": remote_path,
                "local_path": local_path,
                "show_progress": show_progress,
                "open_after": open_after,
            }
        )
        return 1

    root.doDownload = capture_download
    monkeypatch.setattr("carveracontroller.main.Clock.schedule_once", lambda *args, **kwargs: None)
    monkeypatch.setattr("carveracontroller.main.time.sleep", lambda *_args, **_kwargs: None)

    Makera.download_config_files(
        root,
        [
            {"path": "/sd/config.txt"},
            {"path": "/sd/gcodes/job.nc"},
            {"path": "/sd/config.default"},
            {"path": "/sd/cartesian_nm.grid"},
        ],
    )

    assert [call["remote_path"] for call in calls] == [
        "/sd/config.txt",
        "/sd/config.default",
        "/sd/cartesian_nm.grid",
    ]
    for call in calls:
        assert call["show_progress"] is False
        assert call["open_after"] is False
        assert call["local_path"] == str(tmp_path / call["remote_path"].rsplit("/", 1)[-1])
    assert set(DEFAULT_BACKUP_PATHS) >= {call["remote_path"] for call in calls}


def _download_host(tmp_path, *, downloading_config=False):
    root = Makera.__new__(Makera)
    root.temp_dir = str(tmp_path)
    root.downloading_config = downloading_config
    root.downloading = False
    root.fw_version = "1.0"
    root.heartbeat_time = 0
    root.filetype = "nc"
    root.controller = SimpleNamespace(
        comms=SimpleNamespace(uses_framed_transfer=False),
        downloadCommand=MagicMock(),
        pauseStream=MagicMock(),
        resumeStream=MagicMock(),
        stream=SimpleNamespace(download=MagicMock(), modem=None),
        log=SimpleNamespace(put=MagicMock()),
        queryTime=MagicMock(),
        queryModel=MagicMock(),
        queryVersion=MagicMock(),
        queryFtype=MagicMock(),
        viewDiagnoseReport=MagicMock(),
    )
    root.load_gcode_file = MagicMock()
    root.finishLoadConfig = MagicMock()
    root._decompress_downloaded_file_in_place = MagicMock(return_value=True)
    root._ingest_machine_gcode_thumbnail = MagicMock()
    root.update_recent_remote_dir_list = MagicMock()
    root.attempt_usb_baud_upgrade_if_eligible = MagicMock()
    root.show_message_popup = MagicMock()
    return root


def _complete_download(tmp_filename, _md5, _progress_cb):
    with open(tmp_filename, "w", encoding="utf-8") as handle:
        handle.write("downloaded")
    return 1


def test_config_backup_download_does_not_open_gcode_or_apply_settings(monkeypatch, tmp_path):
    root = _download_host(tmp_path, downloading_config=True)
    root.controller.stream.download.side_effect = _complete_download
    monkeypatch.setattr("carveracontroller.main.App.get_running_app", lambda: None)
    monkeypatch.setattr("carveracontroller.main.Clock.schedule_once", lambda *args, **kwargs: None)

    local_path = str(tmp_path / "config.txt")
    Makera.doDownload(root, "/sd/config.txt", local_path, show_progress=False, open_after=False)

    root.load_gcode_file.assert_not_called()
    root.finishLoadConfig.assert_not_called()
    root.controller.queryTime.assert_not_called()
    root.update_recent_remote_dir_list.assert_not_called()
    root._decompress_downloaded_file_in_place.assert_called_once_with(local_path, integrity_label=None)
    assert root.downloading_config is True
    with open(local_path, encoding="utf-8") as handle:
        assert handle.read() == "downloaded"


def _download_bytes_then_fail(tmp_filename, _md5, _progress_cb):
    with open(tmp_filename, "w", encoding="utf-8") as handle:
        handle.write("factory-config")
    return


def _collect_messages(root):
    messages = []
    root.show_message_popup = lambda message, _btn_disabled, *args: messages.append(message)
    return messages


def test_config_backup_md5_mismatch_keeps_file(monkeypatch, tmp_path):
    root = _download_host(tmp_path)
    root.backing_up_config = True
    root.controller.stream.modem = SimpleNamespace(download_md5_failed=True)
    root.controller.stream.download.side_effect = _download_bytes_then_fail
    messages = _collect_messages(root)
    scheduled = []
    monkeypatch.setattr("carveracontroller.main.App.get_running_app", lambda: None)
    monkeypatch.setattr("carveracontroller.main.Clock.schedule_once", lambda cb, t=0: scheduled.append(cb))

    local_path = str(tmp_path / "config.txt")
    result = Makera.doDownload(root, "/sd/config.txt", local_path, show_progress=False, open_after=False)
    for callback in scheduled:
        callback(0)

    assert result > 0
    with open(local_path, encoding="utf-8") as handle:
        assert handle.read() == "factory-config"
    assert root._backup_md5_mismatches == ["/sd/config.txt"]
    assert messages == []


def test_video_download_md5_mismatch_keeps_the_file_and_warns(monkeypatch, tmp_path, caplog):
    root = _download_host(tmp_path)
    root.backing_up_config = False
    root.controller.stream.modem = SimpleNamespace(download_md5_failed=True)
    root.controller.stream.download.side_effect = _download_bytes_then_fail
    messages = _collect_messages(root)
    scheduled = []
    monkeypatch.setattr("carveracontroller.main.App.get_running_app", lambda: None)
    monkeypatch.setattr("carveracontroller.main.Clock.schedule_once", lambda cb, t=0: scheduled.append(cb))

    local_path = str(tmp_path / "clip.avi")
    with caplog.at_level(logging.WARNING, logger="carveracontroller.main"):
        result = Makera.doDownload(root, "/sd/videos/clip.avi", local_path, show_progress=False, open_after=False)
    for callback in scheduled:
        callback(0)

    assert result > 0
    with open(local_path, encoding="utf-8") as handle:
        assert handle.read() == "factory-config"
    assert messages == []
    warnings = [record.message for record in caplog.records if record.levelno == logging.WARNING]
    assert any("known issue with video file downloads from the Makera ESP32" in message for message in warnings)
    assert any("/sd/videos/clip.avi" in message for message in warnings)
    root._decompress_downloaded_file_in_place.assert_called_once_with(local_path, integrity_label="/sd/videos/clip.avi")


def test_singular_video_dir_md5_mismatch_is_the_same_known_issue(monkeypatch, tmp_path, caplog):
    root = _download_host(tmp_path)
    root.controller.stream.modem = SimpleNamespace(download_md5_failed=True)
    root.controller.stream.download.side_effect = _download_bytes_then_fail
    messages = _collect_messages(root)
    monkeypatch.setattr("carveracontroller.main.App.get_running_app", lambda: None)
    monkeypatch.setattr("carveracontroller.main.Clock.schedule_once", lambda *args, **kwargs: None)

    local_path = str(tmp_path / "clip.avi")
    with caplog.at_level(logging.WARNING, logger="carveracontroller.main"):
        result = Makera.doDownload(root, "/sd/video/clip.avi", local_path, show_progress=False, open_after=False)

    assert result > 0
    assert os.path.exists(local_path)
    assert messages == []
    assert any("Makera ESP32" in record.message for record in caplog.records)


def test_download_md5_mismatch_still_fails_outside_backup(monkeypatch, tmp_path):
    root = _download_host(tmp_path)
    root.backing_up_config = False
    root.controller.stream.modem = SimpleNamespace(download_md5_failed=True)
    root.controller.stream.download.side_effect = _download_bytes_then_fail
    messages = _collect_messages(root)
    scheduled = []
    monkeypatch.setattr("carveracontroller.main.App.get_running_app", lambda: None)
    monkeypatch.setattr("carveracontroller.main.Clock.schedule_once", lambda cb, t=0: scheduled.append(cb))

    local_path = str(tmp_path / "job.nc")
    result = Makera.doDownload(root, "/sd/gcodes/job.nc", local_path, show_progress=False, open_after=False)
    for callback in scheduled:
        callback(0)

    assert result is None
    assert not os.path.exists(local_path)
    assert not os.path.exists(local_path + ".tmp")
    assert messages
    assert "MD5" in messages[0]
    assert "factory" not in messages[0].lower()


def test_backup_deferred_md5_mismatch_keeps_decompressed_file(monkeypatch, tmp_path):
    root = Makera.__new__(Makera)
    root.backing_up_config = True
    path = tmp_path / "config.txt"
    path.write_text("hello", encoding="utf-8")
    root.controller = SimpleNamespace(stream=SimpleNamespace(modem=SimpleNamespace(deferred_download_md5="0" * 32)))
    scheduled = []
    monkeypatch.setattr("carveracontroller.main.Clock.schedule_once", lambda cb, t=0: scheduled.append(cb))

    assert Makera._verify_deferred_download_md5(root, str(path), label="/sd/config.txt") is True
    assert path.read_text(encoding="utf-8") == "hello"
    assert root._backup_md5_mismatches == ["/sd/config.txt"]
    assert scheduled == []


def test_deferred_video_md5_mismatch_keeps_the_file(monkeypatch, tmp_path, caplog):
    root = Makera.__new__(Makera)
    root.backing_up_config = False
    path = tmp_path / "clip.avi"
    path.write_text("frames", encoding="utf-8")
    root.controller = SimpleNamespace(stream=SimpleNamespace(modem=SimpleNamespace(deferred_download_md5="0" * 32)))
    root.show_message_popup = MagicMock()
    scheduled = []
    monkeypatch.setattr("carveracontroller.main.Clock.schedule_once", lambda cb, t=0: scheduled.append(cb))

    with caplog.at_level(logging.WARNING, logger="carveracontroller.main"):
        assert Makera._verify_deferred_download_md5(root, str(path), label="/sd/video/clip.avi") is True
    assert path.read_text(encoding="utf-8") == "frames"
    assert scheduled == []
    assert any("Makera ESP32" in record.message for record in caplog.records)


def test_deferred_md5_mismatch_still_rejects_outside_backup(monkeypatch, tmp_path):
    root = Makera.__new__(Makera)
    root.backing_up_config = False
    path = tmp_path / "config.txt"
    path.write_text("hello", encoding="utf-8")
    root.controller = SimpleNamespace(stream=SimpleNamespace(modem=SimpleNamespace(deferred_download_md5="0" * 32)))
    root.show_message_popup = MagicMock()
    scheduled = []
    monkeypatch.setattr("carveracontroller.main.Clock.schedule_once", lambda cb, t=0: scheduled.append(cb))

    assert Makera._verify_deferred_download_md5(root, str(path)) is False
    assert not path.exists()
    assert scheduled


def test_finish_config_backup_warns_about_factory_md5_mismatch(monkeypatch, tmp_path):
    root = Makera.__new__(Makera)
    root.pick_file_popup = None
    root.backing_up_config = True
    root.downloading_config = False
    root.file_popup = SimpleNamespace(restore_machine_root=MagicMock())
    root._backup_md5_mismatches = ["/sd/config.txt", "/sd/config.default"]
    messages = _collect_messages(root)
    scheduled = []
    monkeypatch.setattr("carveracontroller.main.Clock.schedule_once", lambda cb, t=0: scheduled.append(cb))

    source = tmp_path / "config.txt"
    source.write_text("config", encoding="utf-8")
    other = tmp_path / "config.default"
    other.write_text("default", encoding="utf-8")
    dest_dir = tmp_path / "backup"
    dest_dir.mkdir()

    Makera.finish_backing_up_config(root, [str(source), str(other)], str(dest_dir), None)

    assert (dest_dir / "config.txt").read_text(encoding="utf-8") == "config"
    assert (dest_dir / "config.default").read_text(encoding="utf-8") == "default"
    assert root.backing_up_config is False
    assert root._backup_md5_mismatches == []
    for callback in scheduled:
        callback(0)
    assert len(messages) == 1
    assert "/sd/config.txt" in messages[0]
    assert "/sd/config.default" in messages[0]
    assert "factory" in messages[0].lower()
    assert "backed up successfully" in messages[0].lower()


def test_job_download_still_opens_gcode_viewer(monkeypatch, tmp_path):
    root = _download_host(tmp_path, downloading_config=False)
    root.controller.stream.download.side_effect = _complete_download
    monkeypatch.setattr("carveracontroller.main.App.get_running_app", lambda: None)
    monkeypatch.setattr("carveracontroller.main.Clock.schedule_once", lambda *args, **kwargs: None)

    local_path = str(tmp_path / "job.nc")
    Makera.doDownload(root, "/sd/gcodes/job.nc", local_path)

    root.load_gcode_file.assert_called_once_with(local_path)
    root.finishLoadConfig.assert_not_called()
    root.update_recent_remote_dir_list.assert_called_once_with("/sd/gcodes")


def test_machine_config_download_still_applies_settings(monkeypatch, tmp_path):
    root = _download_host(tmp_path, downloading_config=True)
    root.controller.stream.download.side_effect = _complete_download
    scheduled = []
    monkeypatch.setattr("carveracontroller.main.App.get_running_app", lambda: None)
    monkeypatch.setattr("carveracontroller.main.Clock.schedule_once", lambda cb, t=0: scheduled.append(cb))

    local_path = str(tmp_path / "config_usb.txt")
    Makera.doDownload(root, "/sd/config.txt", local_path)

    root.load_gcode_file.assert_not_called()
    assert any(getattr(cb, "func", None) is root.finishLoadConfig for cb in scheduled)
    assert root.controller.queryTime in scheduled


def test_machine_child_entry_path_uses_listed_dir():
    assert machine_child_entry_path("/sd/gcodes/jobs", "part.nc") == "/sd/gcodes/jobs/part.nc"
    assert machine_child_entry_path("/sd/gcodes/jobs/", "tools") == "/sd/gcodes/jobs/tools"
    assert machine_child_entry_path("\\sd\\gcodes\\jobs", "part.nc") == "/sd/gcodes/jobs/part.nc"
    assert machine_child_entry_path("/sd", "config.txt") == "/sd/config.txt"


def test_machine_path_display_keeps_sd_root():
    assert machine_path_display("/sd/gcodes") == "/sd/gcodes"
    assert machine_path_display("/sd/gcodes/") == "/sd/gcodes"
    assert machine_path_display("/sd/gcodes/jobs") == "/sd/gcodes/jobs"
    assert machine_path_display("/sd/gcodes/jobs/batch") == "/sd/gcodes/jobs/batch"
    assert machine_path_display("\\sd\\gcodes\\jobs") == "/sd/gcodes/jobs"
    assert machine_path_display("") == "/sd/gcodes"
    assert upload_dest_tooltip("/sd/gcodes/jobs", translate=IDENTITY) == "Upload to: /sd/gcodes/jobs"
    assert download_dest_tooltip("/home/user/gcodes", translate=IDENTITY) == "Download to: /home/user/gcodes"


def test_device_tab_path_display_native_separators():
    assert device_tab_path_display("") == ""
    assert device_tab_path_display("/home/user/gcodes") == "/home/user/gcodes"
    assert device_tab_path_display("/home/user/gcodes/") == "/home/user/gcodes"


def test_device_tab_path_display_windows_format(monkeypatch):
    import ntpath

    monkeypatch.setattr(
        "carveracontroller.ui.file_browser.sources.os.path.normpath",
        ntpath.normpath,
    )
    assert device_tab_path_display("C:\\Users\\me\\gcodes\\jobs") == "C:\\Users\\me\\gcodes\\jobs"
    assert device_tab_path_display("C:\\Users\\me\\gcodes\\jobs\\") == "C:\\Users\\me\\gcodes\\jobs"


def test_machine_tab_path_display_connected_and_not():
    assert machine_tab_path_display("/sd/gcodes/jobs", connected=True, translate=IDENTITY) == "/sd/gcodes/jobs"
    assert machine_tab_path_display("/sd/gcodes/jobs", connected=False, translate=IDENTITY) == "Not connected"


def test_trim_machine_breadcrumbs_drops_sd_and_empty_root():
    paths, labels = trim_breadcrumb_pairs(
        ["/", "/sd", "/sd/gcodes", "/sd/gcodes/jobs"],
        ["", "sd", "gcodes", "jobs"],
        machine=True,
    )
    assert paths == ["/sd/gcodes", "/sd/gcodes/jobs"]
    assert labels == ["gcodes", "jobs"]
    video_paths, video_labels = trim_breadcrumb_pairs(
        ["/", "/sd", "/sd/videos", "/sd/videos/job"],
        ["", "sd", "videos", "job"],
        machine=True,
    )
    assert video_paths == ["/sd/videos", "/sd/videos/job"]
    assert video_labels == ["videos", "job"]


def test_list_device_directory_skips_dotfiles(tmp_path):
    (tmp_path / "visible.nc").write_text("g")
    (tmp_path / ".hidden.nc").write_text("g")
    (tmp_path / "sub").mkdir()
    (tmp_path / ".skipdir").mkdir()
    entries = list_device_directory(str(tmp_path))
    names = {item["name"] for item in entries}
    assert names == {"visible.nc", "sub"}
    folders = [item for item in entries if item["is_dir"]]
    files = [item for item in entries if not item["is_dir"]]
    assert folders[0]["name"] == "sub"
    assert files[0]["size"] > 0


def test_local_dir_has_file(tmp_path):
    (tmp_path / "job.nc").write_text("g")
    (tmp_path / "tools").mkdir()
    assert local_dir_has_file(str(tmp_path), "job.nc") is True
    assert local_dir_has_file(str(tmp_path), "/sd/gcodes/job.nc") is True
    assert local_dir_has_file(str(tmp_path), "missing.nc") is False
    assert local_dir_has_file(str(tmp_path), "tools") is False
    assert local_dir_has_file("", "job.nc") is False
    assert local_dir_has_file(str(tmp_path), "") is False


def test_local_child_and_sibling_paths(tmp_path):
    src = str(tmp_path / "job.nc")
    assert local_child_path(str(tmp_path), "folder") == str(tmp_path / "folder")
    assert local_sibling_path(src, "renamed.nc") == str(tmp_path / "renamed.nc")
    assert local_child_path(str(tmp_path), "") == ""
    assert local_child_path(str(tmp_path), "../escape") == ""
    assert local_child_path(str(tmp_path), "a/b") == ""
    assert local_sibling_path(src, "..") == ""


def test_local_mkdir_rename_and_remove(tmp_path):
    folder = mkdir_local(str(tmp_path), "tools")
    assert os.path.isdir(folder)
    src = tmp_path / "job.nc"
    src.write_text("g")
    dest = str(tmp_path / "part.nc")
    rename_local_path(str(src), dest)
    assert os.path.isfile(dest)
    assert not src.exists()
    remove_local_path(dest)
    assert not os.path.exists(dest)
    nested = tmp_path / "tools" / "inner.nc"
    nested.write_text("g")
    remove_local_path(folder)
    assert not os.path.exists(folder)


def test_compact_width_helper():
    assert is_compact_width(400, threshold=720) is True
    assert is_compact_width(800, threshold=720) is False


def test_action_state_device_file_selected():
    state = compute_action_state(
        location=LOCATION_DEVICE,
        firmware_mode=False,
        ios=False,
        machine_connected=True,
        machine_idle=True,
        selected_is_file=True,
        selected_count=1,
        multi_select_mode=False,
        selected_name="part.nc",
    )
    assert state.show_preview is True
    assert state.show_upload is True
    assert state.show_upload_and_use is True
    assert state.show_download is False
    assert state.show_rename is True
    assert state.show_delete is True
    assert state.show_new_folder is True
    assert state.show_multi_toggle is True
    assert state.primary == "upload_and_use"


def test_action_state_device_requires_idle_for_upload():
    state = compute_action_state(
        location=LOCATION_DEVICE,
        firmware_mode=False,
        ios=False,
        machine_connected=True,
        machine_idle=False,
        selected_is_file=True,
        selected_count=1,
        multi_select_mode=False,
        selected_name="part.nc",
    )
    assert state.show_preview is True
    assert state.show_upload is False
    assert state.show_upload_and_use is False
    assert state.show_rename is True
    assert state.show_delete is True
    assert state.show_new_folder is True
    assert state.primary == ""


def test_action_state_device_folder_and_multi():
    folder = compute_action_state(
        location=LOCATION_DEVICE,
        firmware_mode=False,
        ios=False,
        machine_connected=True,
        machine_idle=True,
        selected_is_file=False,
        selected_count=1,
        multi_select_mode=False,
    )
    assert folder.show_preview is False
    assert folder.show_upload is False
    assert folder.show_rename is True
    assert folder.show_delete is True
    assert folder.show_new_folder is True
    assert folder.primary == ""
    multi = compute_action_state(
        location=LOCATION_DEVICE,
        firmware_mode=False,
        ios=False,
        machine_connected=True,
        machine_idle=True,
        selected_is_file=False,
        selected_count=2,
        multi_select_mode=True,
    )
    assert multi.show_delete is True
    assert multi.show_cancel_multi is True
    assert multi.show_preview is False
    assert multi.show_upload is False
    assert multi.show_rename is False
    assert multi.show_new_folder is False
    assert multi.primary == "delete"
    uploading = compute_action_state(
        location=LOCATION_DEVICE,
        firmware_mode=False,
        ios=False,
        machine_connected=True,
        machine_idle=True,
        selected_is_file=False,
        selected_count=3,
        multi_select_mode=True,
        selected_file_count=2,
    )
    assert uploading.show_upload is True
    assert uploading.show_download is False
    assert uploading.show_delete is True
    assert uploading.primary == "delete"


def test_action_state_firmware_upload_only():
    state = compute_action_state(
        location=LOCATION_DEVICE,
        firmware_mode=True,
        ios=False,
        machine_connected=True,
        machine_idle=True,
        selected_is_file=True,
        selected_count=1,
        multi_select_mode=False,
    )
    assert state.show_preview is False
    assert state.show_upload is True
    assert state.show_upload_and_use is False
    assert state.search_enabled is False
    assert state.show_download is False
    assert state.show_rename is False
    assert state.show_multi_toggle is False
    assert state.primary == "upload"


def test_action_state_machine_file_and_folder():
    file_state = compute_action_state(
        location=LOCATION_MACHINE,
        firmware_mode=False,
        ios=False,
        machine_connected=True,
        machine_idle=True,
        selected_is_file=True,
        selected_is_editable_gcode=True,
        selected_count=1,
        multi_select_mode=False,
        selected_name="part.nc",
    )
    assert file_state.show_use_as_job is True
    assert file_state.show_download is True
    assert file_state.show_edit is True
    assert file_state.show_rename is True
    assert file_state.show_delete is True
    assert file_state.show_new_folder is True
    assert file_state.primary == "use_as_job"
    folder_state = compute_action_state(
        location=LOCATION_MACHINE,
        firmware_mode=False,
        ios=False,
        machine_connected=True,
        machine_idle=True,
        selected_is_file=False,
        selected_count=1,
        multi_select_mode=False,
    )
    assert folder_state.show_use_as_job is False
    assert folder_state.show_download is False
    assert folder_state.show_rename is True
    assert folder_state.show_delete is True
    busy = compute_action_state(
        location=LOCATION_MACHINE,
        firmware_mode=False,
        ios=False,
        machine_connected=True,
        machine_idle=False,
        selected_is_file=True,
        selected_count=1,
        multi_select_mode=False,
        selected_name="part.nc",
    )
    assert busy.show_use_as_job is True
    assert busy.show_download is False
    assert busy.show_edit is False


def test_action_state_machine_disconnected_and_multi():
    disconnected = compute_action_state(
        location=LOCATION_MACHINE,
        firmware_mode=False,
        ios=False,
        machine_connected=False,
        machine_idle=False,
        selected_is_file=False,
        selected_count=0,
        multi_select_mode=False,
    )
    assert disconnected.show_use_as_job is False
    assert disconnected.show_download is False
    assert disconnected.search_enabled is False
    multi = compute_action_state(
        location=LOCATION_MACHINE,
        firmware_mode=False,
        ios=False,
        machine_connected=True,
        machine_idle=True,
        selected_is_file=False,
        selected_count=3,
        multi_select_mode=True,
    )
    assert multi.show_delete is True
    assert multi.show_cancel_multi is True
    assert multi.show_use_as_job is False
    assert multi.show_download is False
    assert multi.primary == "delete"
    downloading = compute_action_state(
        location=LOCATION_MACHINE,
        firmware_mode=False,
        ios=False,
        machine_connected=True,
        machine_idle=True,
        selected_is_file=False,
        selected_count=2,
        multi_select_mode=True,
        selected_file_count=2,
    )
    assert downloading.show_download is True
    assert downloading.show_upload is False
    assert downloading.show_delete is True
    busy_files = compute_action_state(
        location=LOCATION_MACHINE,
        firmware_mode=False,
        ios=False,
        machine_connected=True,
        machine_idle=False,
        selected_is_file=False,
        selected_count=2,
        multi_select_mode=True,
        selected_file_count=2,
    )
    assert busy_files.show_download is False


def _selection_popup(*, entries, selected):
    popup = SimpleNamespace(
        location=LOCATION_MACHINE,
        multi_select_mode=True,
        selected_device_paths=["/tmp/local.nc"],
        selected_device_file="/tmp/local.nc",
        selected_machine_paths=list(selected),
        selected_machine_file=selected[-1] if selected else "",
        selected_machine_filesize=1,
        _highlight_path=selected[-1] if selected else "",
        _machine_entries=list(entries),
        _device_entries=[],
        ids={},
    )
    for name in (
        "_selected_paths",
        "_apply_selected_paths",
        "_current_entries",
        "_path_is_dir",
        "_size_for_path",
        "forget_selected_paths",
        "_prune_missing_selection",
    ):
        setattr(popup, name, getattr(FileBrowserPopup, name).__get__(popup))
    popup._rebuild_list = lambda *args, **kwargs: None
    popup._sync_chrome = lambda: None
    return popup


def test_deleted_multi_selection_is_dropped_before_the_listing_updates():
    entries = [
        {"path": "/sd/a.nc", "is_dir": False, "size": 10},
        {"path": "/sd/b.nc", "is_dir": False, "size": 10},
        {"path": "/sd/keep.nc", "is_dir": False, "size": 4},
    ]
    popup = _selection_popup(entries=entries, selected=["/sd/a.nc", "/sd/b.nc", "/sd/keep.nc"])
    popup._highlight_path = "/sd/a.nc"
    popup.forget_selected_paths(["/sd/a.nc", "/sd/b.nc"])
    assert popup.selected_machine_paths == ["/sd/keep.nc"]
    assert popup.selected_machine_file == "/sd/keep.nc"
    assert popup._highlight_path == "/sd/keep.nc"
    assert popup.multi_select_mode is True
    assert popup.selected_device_paths == ["/tmp/local.nc"]

    popup.forget_selected_paths(["/sd/keep.nc"])
    assert popup.selected_machine_paths == []
    assert popup.selected_machine_file == ""
    assert popup._highlight_path == ""
    assert popup.multi_select_mode is False


def test_reopen_drops_selection_missing_from_the_listing():
    popup = _selection_popup(
        entries=[{"path": "/sd/keep.nc", "is_dir": False, "size": 4}],
        selected=["/sd/a.nc", "/sd/keep.nc"],
    )
    popup.multi_select_mode = False
    popup._highlight_path = "/sd/a.nc"
    popup._prune_missing_selection()
    assert popup.selected_machine_paths == ["/sd/keep.nc"]
    assert popup.selected_machine_file == "/sd/keep.nc"
    assert popup._highlight_path == "/sd/keep.nc"
    assert popup.selected_device_paths == ["/tmp/local.nc"]

    popup._machine_entries = []
    popup._prune_missing_selection()
    assert popup.selected_machine_paths == []
    assert popup.multi_select_mode is False


def test_single_select_prune_keeps_only_the_highlighted_file():
    popup = _selection_popup(
        entries=[
            {"path": "/sd/a.nc", "is_dir": False, "size": 10},
            {"path": "/sd/keep.nc", "is_dir": False, "size": 4},
        ],
        selected=["/sd/a.nc", "/sd/keep.nc"],
    )
    popup.multi_select_mode = False
    popup._highlight_path = "/sd/a.nc"
    popup._prune_missing_selection()
    assert popup.selected_machine_paths == ["/sd/a.nc"]
    assert popup.selected_machine_file == "/sd/a.nc"
    assert popup._highlight_path == "/sd/a.nc"
    assert popup.multi_select_mode is False


def test_multi_select_prune_keeps_every_file_still_listed():
    popup = _selection_popup(
        entries=[
            {"path": "/sd/a.nc", "is_dir": False, "size": 10},
            {"path": "/sd/keep.nc", "is_dir": False, "size": 4},
        ],
        selected=["/sd/a.nc", "/sd/keep.nc", "/sd/missing.nc"],
    )
    popup._highlight_path = "/sd/missing.nc"
    popup._prune_missing_selection()
    assert popup.selected_machine_paths == ["/sd/a.nc", "/sd/keep.nc"]
    assert popup.multi_select_mode is True
    assert popup._highlight_path == "/sd/keep.nc"


def _shift_popup(*, selected, highlight, data, multi=False, anchor=-1, firmware=False):
    popup = _selection_popup(
        entries=[{"path": row["path"], "is_dir": False, "size": 1} for row in data if row.get("path")],
        selected=list(selected),
    )
    popup.multi_select_mode = multi
    popup._highlight_path = highlight
    popup._last_range_index = anchor
    popup.firmware_mode = firmware
    popup.ids = {"file_list": SimpleNamespace(data=list(data))}
    for name in (
        "_on_modifier_select",
        "_shift_select",
        "_shift_anchor_index",
        "_index_for_path",
        "_add_index_range",
        "_on_toggle_checked",
        "_multi_select_allowed",
    ):
        setattr(popup, name, getattr(FileBrowserPopup, name).__get__(popup))
    return popup


def _range_rows():
    return [
        {"path": "/sd/a.nc", "selectable": True},
        {"path": "/sd/b.nc", "selectable": True},
        {"path": "/sd/skip", "selectable": False},
        {"path": "/sd/c.nc", "selectable": True},
    ]


def test_shift_click_outside_multi_select_selects_the_range_and_turns_it_on():
    popup = _shift_popup(selected=["/sd/a.nc"], highlight="/sd/a.nc", data=_range_rows())
    popup._on_modifier_select("/sd/c.nc", 3, "shift")
    assert popup.multi_select_mode is True
    assert popup.selected_machine_paths == ["/sd/a.nc", "/sd/b.nc", "/sd/c.nc"]
    assert popup.selected_machine_file == "/sd/c.nc"
    assert "/sd/skip" not in popup.selected_machine_paths
    assert popup._last_range_index == 0

    popup._on_modifier_select("/sd/b.nc", 1, "shift")
    assert popup.selected_machine_paths == ["/sd/a.nc", "/sd/b.nc"]
    assert popup._last_range_index == 0


def test_shift_click_with_nothing_selected_starts_multi_select_on_that_file():
    popup = _shift_popup(selected=[], highlight="", data=_range_rows())
    popup._on_modifier_select("/sd/b.nc", 1, "shift")
    assert popup.multi_select_mode is True
    assert popup.selected_machine_paths == ["/sd/b.nc"]
    assert popup._last_range_index == 1


def test_ctrl_shift_adds_a_range_without_clearing_other_files():
    popup = _shift_popup(
        selected=["/sd/c.nc"],
        highlight="/sd/a.nc",
        data=_range_rows(),
        multi=True,
        anchor=0,
    )
    popup._on_modifier_select("/sd/b.nc", 1, "ctrl-shift")
    assert popup.selected_machine_paths == ["/sd/c.nc", "/sd/a.nc", "/sd/b.nc"]
    assert popup._last_range_index == 0


def test_shift_click_does_nothing_when_multi_select_is_not_allowed():
    popup = _shift_popup(selected=["/sd/a.nc"], highlight="/sd/a.nc", data=_range_rows(), firmware=True)
    popup._on_modifier_select("/sd/c.nc", 3, "shift")
    assert popup.multi_select_mode is False
    assert popup.selected_machine_paths == ["/sd/a.nc"]


def test_transfer_confirm_mentions_overwrite_and_skipped_folders():
    assert transfer_confirm_message(["/tmp/a.nc"], ["a.nc"], [], "upload") == (
        "File Already Exists",
        "Confirm to overwrite file: \n 'a.nc'?",
    )
    assert transfer_confirm_message(["/tmp/a.nc"], [], [], "download") is None
    title, body = transfer_confirm_message(
        ["/tmp/a.nc", "/tmp/b.nc", "/tmp/c.nc"],
        ["a.nc"],
        ["jobs"],
        "upload",
    )
    assert title == "File Already Exists"
    assert "overwrite 1 files that already exist on the machine" in body
    assert "2 other selected files will also be uploaded" in body
    assert "1 selected folder will not be uploaded." in body
    assert "jobs" in body
    title, body = transfer_confirm_message(["/sd/a.nc"], [], ["clips"], "download")
    assert title == "Folders are not transferred"
    assert "1 selected folder will not be downloaded." in body
    assert "Continue downloading 1 file?" in body


def test_video_files_are_not_jobs():
    assert is_job_file("part.nc") is True
    assert is_job_file("part.gcode.lz") is True
    assert is_job_file("clip.avi") is False
    assert is_job_file("clip.AVI") is False
    assert is_job_file("clip.mp4") is False
    video = compute_action_state(
        location=LOCATION_MACHINE,
        firmware_mode=False,
        ios=False,
        machine_connected=True,
        machine_idle=True,
        selected_is_file=True,
        selected_count=1,
        multi_select_mode=False,
        selected_name="job-20260926.avi",
    )
    assert video.show_use_as_job is False
    assert video.primary == ""
    assert video.show_download is True
    assert video.show_delete is True
    local_video = compute_action_state(
        location=LOCATION_DEVICE,
        firmware_mode=False,
        ios=False,
        machine_connected=True,
        machine_idle=True,
        selected_is_file=True,
        selected_count=1,
        multi_select_mode=False,
        selected_name="clip.avi",
    )
    assert local_video.show_preview is False
    assert local_video.show_upload_and_use is False
    assert local_video.primary == ""


def test_action_state_ios_device_uses_browse():
    state = compute_action_state(
        location=LOCATION_DEVICE,
        firmware_mode=False,
        ios=True,
        machine_connected=True,
        machine_idle=True,
        selected_is_file=False,
        selected_count=0,
        multi_select_mode=False,
    )
    assert state.show_ios_browse is True
    assert state.show_places is False
    assert state.show_multi_toggle is False
    assert state.show_rename is False
