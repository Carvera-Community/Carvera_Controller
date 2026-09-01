"""Bed settings popup: viewer sync after edit/delete of the shown bed."""

from carveracontroller.addons.beds.ui.BedSettingsPopup import BedSettingsPopup


def _popup(**kwargs) -> BedSettingsPopup:
    popup = BedSettingsPopup.__new__(BedSettingsPopup)
    popup._store = {}
    popup._applied_selected_id = None
    popup._pending_selected_id = None
    popup._refresh_spinner = lambda: None
    for key, value in kwargs.items():
        setattr(popup, key, value)
    return popup


def test_sync_viewer_if_applied_only_for_shown_bed():
    pushed = []
    popup = _popup(_applied_selected_id="shown")
    popup._push_bed_to_viewer = lambda: pushed.append("push") or True

    popup._sync_viewer_if_applied("other")
    popup._sync_viewer_if_applied(None)
    assert pushed == []

    popup._sync_viewer_if_applied("shown")
    assert pushed == ["push"]


def test_commit_delete_of_applied_bed_clears_selection_and_viewer(monkeypatch):
    pushed = []
    deleted = []
    popup = _popup(_applied_selected_id="shown", _pending_selected_id="shown")
    popup._push_bed_to_viewer = lambda: pushed.append("push") or True
    monkeypatch.setattr(
        "carveracontroller.addons.beds.ui.BedSettingsPopup.delete_bed",
        lambda store, model, bed_id: deleted.append((model, bed_id)),
    )
    monkeypatch.setattr(
        "carveracontroller.addons.beds.ui.BedSettingsPopup.save_store",
        lambda store: None,
    )

    popup._commit_delete("C1", "shown")

    assert deleted == [("C1", "shown")]
    assert popup._applied_selected_id is None
    assert popup._pending_selected_id is None
    assert pushed == ["push"]


def test_commit_delete_of_other_bed_leaves_viewer(monkeypatch):
    pushed = []
    popup = _popup(_applied_selected_id="shown", _pending_selected_id="other")
    popup._push_bed_to_viewer = lambda: pushed.append("push") or True
    monkeypatch.setattr(
        "carveracontroller.addons.beds.ui.BedSettingsPopup.delete_bed",
        lambda store, model, bed_id: None,
    )
    monkeypatch.setattr(
        "carveracontroller.addons.beds.ui.BedSettingsPopup.save_store",
        lambda store: None,
    )

    popup._commit_delete("C1", "other")

    assert popup._applied_selected_id == "shown"
    assert popup._pending_selected_id is None
    assert pushed == []


def test_apply_failure_does_not_dismiss_or_add_generic_popup(monkeypatch):
    dismissed = []
    popup = _popup()
    popup._machine = lambda: "C1"
    popup._id_from_spinner = lambda: "shown"
    popup.dismiss = lambda: dismissed.append(True)
    popup._push_bed_to_viewer = lambda: False
    monkeypatch.setattr(
        "carveracontroller.addons.beds.ui.BedSettingsPopup.set_selected_id",
        lambda store, model, bed_id: None,
    )
    monkeypatch.setattr(
        "carveracontroller.addons.beds.ui.BedSettingsPopup.save_store",
        lambda store: None,
    )
    monkeypatch.setattr(
        "carveracontroller.addons.beds.ui.BedSettingsPopup.selected_id",
        lambda store, model: "shown",
    )

    popup.on_apply_and_close()

    assert dismissed == []
    assert popup._applied_selected_id == "shown"
