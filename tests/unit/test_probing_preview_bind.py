"""Probe preview must not stack app.mdi_data observers across opens."""

from types import SimpleNamespace
from unittest.mock import patch

from kivy.clock import Clock
from kivy.event import EventDispatcher
from kivy.properties import ListProperty

from carveracontroller.addons.probing.ProbingPopup import ProbingPopup


class _MdiHost(EventDispatcher):
    mdi_data = ListProperty([])


class _ManualLog:
    def __init__(self):
        self.data = None
        self.refresh_calls = 0
        self.scroll_y = 1

    def refresh_from_data(self):
        self.refresh_calls += 1


def _probe(popup):
    probe = ProbingPopup.__new__(ProbingPopup)
    probe.preview_popup = popup
    probe._mdi_data_bound = False
    probe._preview_link_event = None
    probe._preview_link_token = 0
    return probe


def _popup():
    return SimpleNamespace(ids=SimpleNamespace(manual_rvPopup=_ManualLog()))


def test_preview_opens_do_not_stack_mdi_binds_and_dismiss_is_idempotent():
    host = _MdiHost()
    host.mdi_data = [{"text": "boot"}]
    popup = _popup()
    probe = _probe(popup)
    log = popup.ids.manual_rvPopup

    with patch("carveracontroller.addons.probing.ProbingPopup.App.get_running_app", return_value=host):
        probe.link_shared_data_with_refresh(popup)
        probe.link_shared_data_with_refresh(popup)
        assert probe._mdi_data_bound is True
        assert log.data is host.mdi_data
        assert host.mdi_data == []

        before = log.refresh_calls
        host.mdi_data.append({"text": "moving"})
        assert log.refresh_calls == before + 1

        probe._on_preview_dismiss()
        assert probe._mdi_data_bound is False
        before = log.refresh_calls
        host.mdi_data.append({"text": "closed"})
        assert log.refresh_calls == before

        probe._on_preview_dismiss()
        assert probe._mdi_data_bound is False
        before = log.refresh_calls
        host.mdi_data.append({"text": "still closed"})
        assert log.refresh_calls == before

        probe.link_shared_data_with_refresh(popup)
        assert probe._mdi_data_bound is True
        before = log.refresh_calls
        host.mdi_data.append({"text": "reopened"})
        assert log.refresh_calls == before + 1
        probe._on_preview_dismiss()
        assert probe._mdi_data_bound is False


def test_dismiss_cancels_scheduled_link_and_ignores_stale_callback():
    host = _MdiHost()
    host.mdi_data = [{"text": "keep"}]
    popup = _popup()
    probe = _probe(popup)

    with patch("carveracontroller.addons.probing.ProbingPopup.App.get_running_app", return_value=host):
        probe._schedule_preview_link()
        first_token = probe._preview_link_token
        first_event = probe._preview_link_event

        probe._schedule_preview_link()
        assert first_event.is_triggered == 0
        second_token = probe._preview_link_token
        second_event = probe._preview_link_event
        assert second_token != first_token

        probe._on_preview_link(first_token)
        assert probe._mdi_data_bound is False
        assert host.mdi_data == [{"text": "keep"}]
        assert probe._preview_link_event is second_event

        probe._on_preview_dismiss()
        assert second_event.is_triggered == 0
        assert probe._preview_link_event is None
        probe._on_preview_link(second_token)
        assert probe._mdi_data_bound is False
        assert host.mdi_data == [{"text": "keep"}]

        probe._on_preview_dismiss()
        assert probe._mdi_data_bound is False


def test_live_scheduled_link_refreshes_manual_log():
    host = _MdiHost()
    popup = _popup()
    probe = _probe(popup)
    log = popup.ids.manual_rvPopup

    with patch("carveracontroller.addons.probing.ProbingPopup.App.get_running_app", return_value=host):
        probe._schedule_preview_link()
        event = probe._preview_link_event
        token = probe._preview_link_token
        event.cancel()
        probe._on_preview_link(token)
        assert probe._mdi_data_bound is True
        assert log.data is host.mdi_data

        before = log.refresh_calls
        host.mdi_data.append({"text": "probe"})
        assert log.refresh_calls == before + 1
        probe._on_preview_dismiss()


def test_preview_popup_dismiss_is_wired_once():
    popup = ProbingPopup(SimpleNamespace())
    Clock.unschedule(popup.delayed_bind)
    calls = []
    original = popup._on_preview_dismiss

    def wrapped(*args):
        calls.append(args)
        return original(*args)

    # Kivy resolves the bound dismiss handler by name, so an instance override is invoked.
    popup._on_preview_dismiss = wrapped

    popup.preview_popup.dispatch("on_dismiss")
    assert len(calls) == 1
    popup.preview_popup.dispatch("on_dismiss")
    assert len(calls) == 2
    assert popup._mdi_data_bound is False
