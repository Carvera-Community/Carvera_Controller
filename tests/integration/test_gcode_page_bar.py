"""UI tests for the G-code file pager on the File workspace."""

import threading

from kivy.metrics import dp

from carveracontroller.ui.GCodePageBar import GCodePageBarButton
from tests.integration.conftest import pump_frames


def _reset_pager(app):
    app.curr_page = 1
    app.total_pages = 1
    app.root.selected_file_line_count = 0
    pump_frames(5)


class TestGCodePageBar:
    def test_hidden_when_file_fits_on_one_page(self, kivy_app):
        kivy_app.root.content.current = "File"
        _reset_pager(kivy_app)
        bar = kivy_app.root.gcode_page_bar
        assert bar.bar_visible is False
        assert bar.height == 0
        assert bar.opacity == 0

    def test_shows_page_and_line_range(self, kivy_app):
        kivy_app.root.content.current = "File"
        kivy_app.root.cmd_manager.current = "gcode_cmd_page"
        kivy_app.root.selected_file_line_count = 25000
        kivy_app.curr_page = 2
        kivy_app.total_pages = 3
        pump_frames(5)
        try:
            bar = kivy_app.root.gcode_page_bar
            assert bar.bar_visible is True
            assert bar.height == dp(40)
            assert bar.opacity == 1
            assert bar.page_label == "2 / 3"
            assert bar.range_label == "10001–20000"
            buttons = {child.icon: child for child in bar.children if isinstance(child, GCodePageBarButton)}
            assert buttons["data/to_start.png"].disabled is False
            assert buttons["data/previous.png"].disabled is False
            assert buttons["data/start.png"].disabled is False
            assert buttons["data/to_end.png"].disabled is False
        finally:
            _reset_pager(kivy_app)

    def test_first_page_disables_backward_buttons(self, kivy_app):
        kivy_app.root.content.current = "File"
        kivy_app.root.cmd_manager.current = "gcode_cmd_page"
        kivy_app.root.selected_file_line_count = 25000
        kivy_app.curr_page = 1
        kivy_app.total_pages = 3
        pump_frames(5)
        try:
            bar = kivy_app.root.gcode_page_bar
            buttons = {child.icon: child for child in bar.children if isinstance(child, GCodePageBarButton)}
            assert buttons["data/to_start.png"].disabled is True
            assert buttons["data/previous.png"].disabled is True
            assert buttons["data/start.png"].disabled is False
            assert buttons["data/to_end.png"].disabled is False
        finally:
            _reset_pager(kivy_app)

    def test_loader_thread_updates_do_not_break_single_page_files(self, kivy_app):
        kivy_app.root.content.current = "File"
        kivy_app.root.cmd_manager.current = "gcode_cmd_page"
        kivy_app.root.gcode_cannot_visualise = False
        kivy_app.root.selected_file_line_count = 25000
        kivy_app.curr_page = 1
        kivy_app.total_pages = 3
        pump_frames(5)
        assert kivy_app.root.gcode_page_bar.bar_visible is True

        def mutate():
            kivy_app.root.selected_file_line_count = 500
            kivy_app.curr_page = 1
            kivy_app.total_pages = 1

        thread = threading.Thread(target=mutate)
        thread.start()
        thread.join()
        pump_frames(10, sleep=0.05)
        try:
            bar = kivy_app.root.gcode_page_bar
            assert kivy_app.root.selected_file_line_count == 500
            assert kivy_app.total_pages == 1
            assert bar.bar_visible is False
            assert bar.page_label == "1 / 1"
            assert bar.range_label == "1–500"
            assert kivy_app.root.gcode_cannot_visualise is False
        finally:
            _reset_pager(kivy_app)
