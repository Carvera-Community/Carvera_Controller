"""Unit tests for file browser listing, grouping, and action state."""

import os
import threading
from queue import Queue
from types import SimpleNamespace
from unittest.mock import MagicMock

from carveracontroller.Controller import LOAD_DIR
from carveracontroller.main import CONFIG_FILES_TO_BACK_UP, Makera
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
    file_type_key,
    file_type_label,
    group_and_sort_entries,
    is_compact_width,
    is_machine_root,
    is_under_machine_root,
    list_device_directory,
    local_child_path,
    local_dir_has_file,
    local_sibling_path,
    machine_child_entry_path,
    machine_listing_callback_matches,
    machine_listing_has,
    machine_listing_is_current,
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
    assert file_row["current_badge"] == "Current"
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
    assert file_row["current_badge"] == "Current (Preview)"
    other = group_and_sort_entries(entries, translate=IDENTITY)
    assert next(row for row in other if row["kind"] == KIND_FILE)["current_badge"] == ""
    assert current_row_badge(is_current=True, is_preview=False, translate=IDENTITY) == "Current"
    assert current_row_badge(is_current=True, is_preview=True, translate=IDENTITY) == "Current (Preview)"
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
    assert machine_parent_dir("/sd/gcodes") is None
    assert machine_parent_dir("/sd/gcodes/jobs") == "/sd/gcodes"
    assert is_under_machine_root("/sd/gcodes")
    assert is_under_machine_root("/sd/gcodes/jobs/batch")
    assert is_under_machine_root("\\sd\\gcodes\\jobs")
    assert is_under_machine_root("/sd") is False
    assert is_under_machine_root("/tmp/gcodes") is False


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
    assert set(CONFIG_FILES_TO_BACK_UP) >= set(call["remote_path"] for call in calls)


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
    root._decompress_downloaded_file_in_place.assert_called_once_with(local_path)
    assert root.downloading_config is True
    with open(local_path, encoding="utf-8") as handle:
        assert handle.read() == "downloaded"


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
        selected_count=1,
        multi_select_mode=False,
    )
    assert file_state.show_use_as_job is True
    assert file_state.show_download is True
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
    )
    assert busy.show_use_as_job is True
    assert busy.show_download is False


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
