"""Bed visibility while switching machines, before config load finishes."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from carveracontroller.main import NOT_CONNECTED, Makera


def _makera(**kwargs) -> Makera:
    root = Makera.__new__(Makera)
    root.gcode_viewer = MagicMock()
    root.gcode_viewer.set_bed = MagicMock(return_value=True)
    root._selected_file_machine_key = None
    root.show_message_popup = MagicMock()
    for key, value in kwargs.items():
        setattr(root, key, value)
    return root


def _app(model="C1", state="Idle", local="", remote="job.nc"):
    return SimpleNamespace(
        model=model,
        state=state,
        selected_local_filename=local,
        selected_remote_filename=remote,
    )


def _patch_bed_store(monkeypatch, path="/tmp/bed.obj"):
    bed = {"mcs_x": 1.0, "mcs_y": 2.0, "mcs_z": 3.0, "material": "mdf"}
    monkeypatch.setattr("carveracontroller.main.load_store", lambda: {"store": True})
    monkeypatch.setattr("carveracontroller.main.selected_id", lambda store, model: "bed-1")
    monkeypatch.setattr("carveracontroller.main.get_bed", lambda store, model, bed_id: bed)
    monkeypatch.setattr("carveracontroller.main.resolve_mesh_path", lambda _bed: path)
    return bed


def test_hides_bed_when_file_belongs_to_other_machine(monkeypatch):
    root = _makera(_selected_file_machine_key="wifi:10.0.0.1")
    root._get_current_machine_connection_key = lambda: "wifi:10.0.0.2"
    monkeypatch.setattr("carveracontroller.main.App.get_running_app", lambda: _app())
    load_store = MagicMock()
    monkeypatch.setattr("carveracontroller.main.load_store", load_store)

    assert root.apply_bed_settings() is True
    root.gcode_viewer.set_bed.assert_called_once_with(None, visible=False)
    load_store.assert_not_called()


def test_shows_bed_when_file_belongs_to_this_machine(monkeypatch):
    root = _makera(_selected_file_machine_key="wifi:10.0.0.1")
    root._get_current_machine_connection_key = lambda: "wifi:10.0.0.1"
    monkeypatch.setattr("carveracontroller.main.App.get_running_app", lambda: _app())
    _patch_bed_store(monkeypatch)

    assert root.apply_bed_settings() is True
    root.gcode_viewer.set_bed.assert_called_once_with(
        "/tmp/bed.obj",
        mcs_xyz=(1.0, 2.0, 3.0),
        material="mdf",
        visible=True,
    )


def test_shows_bed_when_machine_key_not_yet_recorded(monkeypatch):
    root = _makera(_selected_file_machine_key=None)
    root._get_current_machine_connection_key = lambda: "wifi:10.0.0.1"
    monkeypatch.setattr("carveracontroller.main.App.get_running_app", lambda: _app())
    _patch_bed_store(monkeypatch)

    assert root.apply_bed_settings() is True
    assert root.gcode_viewer.set_bed.call_args.kwargs["visible"] is True


def test_hides_bed_when_disconnected(monkeypatch):
    root = _makera(_selected_file_machine_key="wifi:10.0.0.1")
    root._get_current_machine_connection_key = lambda: None
    monkeypatch.setattr(
        "carveracontroller.main.App.get_running_app",
        lambda: _app(model="", state=NOT_CONNECTED),
    )
    load_store = MagicMock()
    monkeypatch.setattr("carveracontroller.main.load_store", load_store)

    assert root.apply_bed_settings() is True
    root.gcode_viewer.set_bed.assert_called_once_with(None, visible=False)
    load_store.assert_not_called()
