"""First-run tour: who sees it, what it points at, and what it must not send."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kivy.base import EventLoop
from kivy.config import Config
from kivy.core.window import Window

from carveracontroller.CNC import CNC
from carveracontroller.Controller import Controller
from carveracontroller.main import set_config_defaults
from carveracontroller.ui.tutorial.placement import (
    GAP,
    MARGIN,
    MIN_HOLE,
    Rect,
    merge_overlapping_holes,
    place_card,
)
from carveracontroller.ui.tutorial.policy import (
    ALLOW,
    CONFIRM_DISCONNECT,
    DEMO,
    DISCONNECTED,
    MARK_COMPLETE,
    REFUSE,
    TEARDOWN,
    WELCOME,
    resolve_skip,
    skip_effect,
    tour_start_decision,
)
from carveracontroller.ui.tutorial.session import (
    blocks_machine_io,
    demo_is_active,
    set_demo_active,
    tutorial_blocks_motion,
)
from carveracontroller.ui.tutorial.steps import tour_steps

_ROOT = Path(__file__).resolve().parents[2]
_KV_TEXT = "\n".join(
    (
        (_ROOT / "carveracontroller" / "makera.kv").read_text(encoding="utf-8"),
        (_ROOT / "carveracontroller" / "ui" / "config_run" / "CoordPopup.kv").read_text(encoding="utf-8"),
        (_ROOT / "carveracontroller" / "ui" / "file_browser" / "FileBrowserPopup.kv").read_text(encoding="utf-8"),
    )
)
_BROWSER_PY = (_ROOT / "carveracontroller" / "ui" / "file_browser" / "FileBrowserPopup.py").read_text(encoding="utf-8")
_MAIN_PY = (_ROOT / "carveracontroller" / "main.py").read_text(encoding="utf-8")


def _intersects(a: Rect, b: Rect) -> bool:
    return not (a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y)


def _inside_safe(card: Rect, window_w: float, window_h: float, safe: tuple[float, float, float, float]) -> bool:
    left = safe[0] + MARGIN
    bottom = safe[3] + MARGIN
    right = window_w - safe[2] - MARGIN
    top = window_h - safe[1] - MARGIN
    return (
        card.x >= left - 0.6
        and card.y >= bottom - 0.6
        and card.x + card.w <= right + 0.6
        and card.y + card.h <= top + 0.6
    )


def _button_row_inside(card: Rect, row: Rect) -> bool:
    return (
        row.w > 0
        and row.h > 0
        and row.x >= card.x - 0.6
        and row.y >= card.y - 0.6
        and row.x + row.w <= card.x + card.w + 0.6
        and row.y + row.h <= card.y + card.h + 0.6
    )


def test_adjacent_button_outlines_merge_into_one():
    # 40px buttons, 3px apart, with the spotlight pad. The pads cross.
    buttons = [Rect(index * 43, 10, 40, 30) for index in range(5)]
    holes = [Rect(button.x - 4, button.y - 4, button.w + 8, button.h + 8) for button in buttons]
    separate = Rect(400, 6, 48, 38)
    merged = merge_overlapping_holes([*holes, separate])
    assert len(merged) == 2
    group = min(merged, key=lambda hole: hole.x)
    assert group.x == -4
    assert group.y == 6
    assert group.right() == 4 * 43 + 40 + 4
    assert group.top() == 44
    assert max(merged, key=lambda hole: hole.x) == separate


def test_tour_steps_point_at_real_controls():
    steps = tour_steps()
    assert len(steps) == 26
    for step in steps:
        assert step.screen in ("Control", "File")
        assert step.popup in (None, "coord", "files")
        assert isinstance(step.target_ids, tuple) and step.target_ids
        assert (_ROOT / "carveracontroller" / step.icon).is_file()
        for target_id in step.target_ids:
            in_kv = f"id: {target_id}" in _KV_TEXT
            in_browser = f'tour_id="{target_id}"' in _BROWSER_PY
            assert in_kv or in_browser
        if step.dropdown:
            dd_name, anchor_id = step.dropdown.split(":")
            assert f"id: {anchor_id}" in _KV_TEXT
            assert f"self.{dd_name}" in _MAIN_PY or f"{dd_name} = " in _MAIN_PY


def test_new_install_marks_tutorial_incomplete():
    existed = Config.has_section("carvera")
    snapshot = dict(Config.items("carvera")) if existed else None
    try:
        if existed:
            Config.remove_section("carvera")
        set_config_defaults("en")
        assert Config.get("carvera", "tutorial_completed") == "0"
    finally:
        _restore_carvera(snapshot)


def test_upgrade_marks_tutorial_complete():
    existed = Config.has_section("carvera")
    snapshot = dict(Config.items("carvera")) if existed else None
    try:
        if not existed:
            Config.add_section("carvera")
        Config.set("carvera", "version", "already-installed")
        if Config.has_option("carvera", "tutorial_completed"):
            Config.remove_option("carvera", "tutorial_completed")
        set_config_defaults("en")
        assert Config.get("carvera", "tutorial_completed") == "1"
    finally:
        _restore_carvera(snapshot)


def test_welcome_skip_does_not_start_the_demo():
    set_demo_active(False)
    result = resolve_skip(WELCOME)
    assert skip_effect(WELCOME) == MARK_COMPLETE
    assert result.mark_complete is True
    assert result.teardown is False
    assert result.start_demo is False
    assert demo_is_active() is False


def test_demo_skip_is_the_teardown_path():
    set_demo_active(True)
    try:
        result = resolve_skip(DEMO)
        assert skip_effect(DEMO) == TEARDOWN
        assert result.teardown is True
        assert result.start_demo is False
    finally:
        set_demo_active(False)
    assert demo_is_active() is False


def test_tour_start_policy():
    assert tour_start_decision(DISCONNECTED) == ALLOW
    assert tour_start_decision("N/A") == ALLOW
    for state in ("Run", "Pause", "Hold", "Tool"):
        assert tour_start_decision(state) == REFUSE
    assert tour_start_decision("Idle") == CONFIRM_DISCONNECT
    assert tour_start_decision(DISCONNECTED, link_busy=True) == CONFIRM_DISCONNECT


def test_practice_view_blocks_commands_without_a_stream():
    controller = Controller(CNC(), lambda _line: None, False)
    controller.stream = None
    set_demo_active(True)
    try:
        assert blocks_machine_io(controller.stream) is True
        assert tutorial_blocks_motion() is True
        controller.executeCommand("G0 X0\n")
        controller.executeRealtime(ord("?"))
        controller.executeRealtimeSequence(ord("?"))
        controller.sendGCode("G0 X0")
    finally:
        set_demo_active(False)
    assert blocks_machine_io(None) is False
    assert tutorial_blocks_motion() is False


def test_practice_view_still_sends_when_a_stream_exists():
    class Sink:
        def __init__(self):
            self.sent = []

        def send(self, payload):
            self.sent.append(payload)

    controller = Controller(CNC(), lambda _line: None, False)
    sink = Sink()
    controller.stream = sink
    set_demo_active(True)
    try:
        assert blocks_machine_io(controller.stream) is False
        controller.executeRealtime(0x18)
    finally:
        set_demo_active(False)
        controller.stream = None
    assert sink.sent


def test_card_sits_beside_the_hole_on_a_desktop_window():
    target = Rect(40, 1200, 80, 48)
    placed = place_card(window_width=900, window_height=1440, target=target)
    assert placed.hole is not None
    assert placed.docked is False
    assert not _intersects(placed.card, placed.hole)
    assert placed.card.x >= placed.hole.x + placed.hole.w or placed.hole.x >= placed.card.x + placed.card.w
    assert _inside_safe(placed.card, 900, 1440, (0, 0, 0, 0))
    assert _button_row_inside(placed.card, placed.button_row)


def test_card_sits_between_pads_on_either_side():
    left = Rect(11, 196, 638, 639)
    right = Rect(1271, 196, 638, 639)
    placed = place_card(
        window_width=1920,
        window_height=1032,
        target=Rect(left.x, left.y, right.right() - left.x, left.h),
        holes=(left, right),
        preferred_size=(520, 320),
    )
    assert placed.docked is False
    assert placed.card.w == 520
    assert placed.card.h == 320
    assert placed.card.x > left.right()
    assert placed.card.right() < right.x
    assert not _intersects(placed.card, left)
    assert not _intersects(placed.card, right)
    assert _button_row_inside(placed.card, placed.button_row)


def test_card_between_pads_clears_buttons_in_the_gap():
    left = Rect(11, 196, 638, 639)
    right = Rect(1271, 196, 638, 639)
    speed = Rect(662, 280, 296, 60)
    mode = Rect(962, 280, 296, 60)
    placed = place_card(
        window_width=1920,
        window_height=1032,
        target=Rect(left.x, left.y, right.right() - left.x, left.h),
        holes=(left, right, speed, mode),
        preferred_size=(520, 320),
    )
    assert placed.docked is False
    assert placed.card.h == 320
    assert placed.card.x > left.right()
    assert placed.card.right() < right.x
    assert placed.card.y >= speed.top()
    for hole in (left, right, speed, mode):
        assert not _intersects(placed.card, hole)


def test_card_docks_on_a_narrow_window():
    safe = (0.0, 0.0, 0.0, 0.0)
    target = Rect(20, 720, 40, 36)
    placed = place_card(window_width=360, window_height=800, safe=safe, target=target)
    assert placed.hole is not None
    assert placed.docked is True
    assert placed.card.top() <= placed.hole.y + 0.1
    assert placed.hole.y - placed.card.top() <= GAP + 1
    assert not _intersects(placed.card, placed.hole)
    assert _inside_safe(placed.card, 360, 800, safe)
    assert _button_row_inside(placed.card, placed.button_row)


def test_card_sits_beside_the_hole_on_a_short_window():
    # A high density scale marks this window short. Side room still fits the text.
    target = Rect(30, 420, 80, 40)
    placed = place_card(window_width=900, window_height=500, target=target, short_height=2000)
    assert placed.hole is not None
    assert placed.docked is False
    assert placed.card.h >= 140
    assert not _intersects(placed.card, placed.hole)
    assert _inside_safe(placed.card, 900, 500, (0, 0, 0, 0))
    assert _button_row_inside(placed.card, placed.button_row)


def test_wide_card_shrinks_into_the_gap_between_pads():
    left = Rect(11, 196, 638, 639)
    right = Rect(1271, 196, 638, 639)
    placed = place_card(
        window_width=1920,
        window_height=1032,
        target=Rect(left.x, left.y, right.right() - left.x, left.h),
        holes=(left, right),
        preferred_size=(900, 400),
        min_size=(280, 220),
        short_height=2000,
    )
    assert placed.docked is False
    assert placed.card.w >= 280
    assert placed.card.w <= (right.x - left.right())
    assert placed.card.h >= 220
    assert placed.card.x > left.right()
    assert placed.card.right() < right.x
    assert not _intersects(placed.card, left)
    assert not _intersects(placed.card, right)


def test_wide_card_sits_beside_a_viewer_sized_hole():
    viewer = Rect(700, 40, 1180, 900)
    placed = place_card(
        window_width=1920,
        window_height=1000,
        target=viewer,
        holes=(viewer,),
        preferred_size=(800, 420),
        min_size=(280, 220),
        short_height=2000,
    )
    assert placed.docked is False
    assert placed.card.right() <= viewer.x
    assert placed.card.w >= 280
    assert placed.card.h >= 220
    assert not _intersects(placed.card, viewer)


def test_card_rests_on_a_bottom_toolbar():
    bar = Rect(80, 8, 1760, 48)
    placed = place_card(
        window_width=1920,
        window_height=1032,
        target=bar,
        preferred_size=(520, 280),
        min_size=(280, 200),
    )
    assert placed.docked is True
    assert placed.card.w == 520
    assert placed.card.x <= bar.x + 1
    assert placed.card.y >= bar.top()
    assert placed.card.y - bar.top() < 40
    assert not _intersects(placed.card, bar)
    assert _button_row_inside(placed.card, placed.button_row)


def test_docked_card_keeps_the_explanation_when_the_band_is_short():
    placed = place_card(
        window_width=360,
        window_height=800,
        target=Rect(0, 40, 340, 700),
        preferred_size=(320, 280),
        min_size=(200, 200),
    )
    assert placed.docked is True
    assert placed.card.h >= 200 - 0.1
    assert _inside_safe(placed.card, 360, 800, (0, 0, 0, 0))
    assert _button_row_inside(placed.card, placed.button_row)


def test_card_stays_inside_the_safe_area_on_a_narrow_window():
    safe = (16.0, 24.0, 16.0, 20.0)
    target = Rect(40, 700, 50, 30)
    placed = place_card(window_width=360, window_height=800, safe=safe, target=target)
    assert placed.docked is True
    assert _inside_safe(placed.card, 360, 800, safe)
    assert placed.hole is not None and not _intersects(placed.card, placed.hole)
    assert _button_row_inside(placed.card, placed.button_row)


def test_welcome_doc_link_opens_from_its_on_screen_position():
    from carveracontroller.ui.tutorial.overlay import DOCS_URL, TourOverlay

    EventLoop.ensure_window()
    overlay = TourOverlay()
    overlay.open()
    try:
        overlay.body.markup = True
        overlay.body.text = f"Docs [ref={DOCS_URL}][color=#32a4ce][u]{DOCS_URL}[/u][/color][/ref]"
        overlay.card.pos = (300, 220)
        overlay.card.size = (480, 260)
        for _ in range(8):
            EventLoop.idle()
        overlay._sync_body_width()
        overlay.body.texture_update()
        overlay.body_scroll.update_from_scroll()

        hit = None
        x0, y0 = int(overlay.body_scroll.x), int(overlay.body_scroll.y)
        x1, y1 = int(overlay.body_scroll.right), int(overlay.body_scroll.top)
        for y in range(y0, y1, 2):
            for x in range(x0, x1, 8):
                if overlay._body_ref_at((x, y)) == DOCS_URL:
                    hit = (float(x), float(y))
                    break
            if hit is not None:
                break
        assert hit is not None
        # The label's own origin stays at (0, 0) inside the scroll view.
        assert overlay.body.collide_point(*hit) is False
        assert overlay._body_ref_at((10, 10)) is None

        touch = type("Touch", (), {"pos": hit, "x": hit[0], "y": hit[1]})()
        with patch("carveracontroller.ui.tutorial.overlay.webbrowser.open") as open_url:
            assert overlay.on_touch_down(touch) is True
        open_url.assert_called_once()
        assert str(open_url.call_args.args[0]).startswith("https://carvera-community.gitbook.io/docs")
    finally:
        overlay.close()
        Window.unbind(mouse_pos=overlay._on_mouse_pos)


def test_step_text_scrolls_back_to_the_top():
    from carveracontroller.ui.tutorial.overlay import TourOverlay

    EventLoop.ensure_window()
    overlay = TourOverlay()
    overlay.open()
    overlay._rebuild_buttons = lambda: None
    try:
        overlay.body_scroll.size = (240, 60)
        overlay.body.size_hint = (None, None)
        overlay.body.size = (240, 400)
        overlay.body_scroll.scroll_y = 0
        overlay.body_scroll._update_effect_y_bounds()
        assert overlay.body_scroll.scroll_y == 0

        overlay.show_step(tour_steps()[0], 0, len(tour_steps()))
        for _ in range(4):
            EventLoop.idle()
        assert overlay.body_scroll.scroll_y == 1

        # A late height change can put the view back at the bottom. Placement
        # schedules another reset once the new step's text has been measured.
        overlay.body_scroll.scroll_y = 0
        overlay.layout_targets([])
        for _ in range(4):
            EventLoop.idle()
        assert overlay.body_scroll.scroll_y == 1
    finally:
        overlay.close()
        Window.unbind(mouse_pos=overlay._on_mouse_pos)


def test_help_menu_offers_documentation_then_the_tour():
    from kivy.uix.dropdown import DropDown

    from carveracontroller.main import Makera

    menu_text = (_ROOT / "carveracontroller" / "makera.kv").read_text(encoding="utf-8")
    assert "app.root.open_help_menu(self)" in menu_text
    assert "text: 'Guided tour'" not in menu_text

    menu = DropDown()
    root = SimpleNamespace(
        help_drop_down=menu,
        func_drop_down=SimpleNamespace(dismiss=Mock()),
        open_online_docs=Mock(),
        tutorial=SimpleNamespace(open_from_menu=Mock()),
    )
    root._open_docs_from_help_menu = lambda *_args: Makera._open_docs_from_help_menu(root, *_args)
    root._open_tour_from_help_menu = lambda *_args: Makera._open_tour_from_help_menu(root, *_args)
    with patch.object(DropDown, "open"):
        Makera.open_help_menu(root, object())
    labels = [child.text for child in reversed(menu.container.children)]
    assert labels == ["Documentation", "Guided tour"]

    documentation, getting_started = list(reversed(menu.container.children))
    documentation.dispatch("on_release")
    root.open_online_docs.assert_called_once_with()
    root.tutorial.open_from_menu.assert_not_called()
    root.func_drop_down.dismiss.assert_called_once_with()

    root.func_drop_down.dismiss.reset_mock()
    getting_started.dispatch("on_release")
    root.tutorial.open_from_menu.assert_called_once_with()
    root.func_drop_down.dismiss.assert_called_once_with()


def test_tiny_target_gets_a_minimum_hole():
    placed = place_card(window_width=900, window_height=1440, target=Rect(200, 200, 2, 2))
    assert placed.hole is not None
    assert placed.hole.w >= MIN_HOLE - 0.1
    assert placed.hole.h >= MIN_HOLE - 0.1
    assert placed.hole.x >= -0.1
    assert placed.hole.y >= -0.1
    assert placed.hole.x + placed.hole.w <= 900.1
    assert placed.hole.y + placed.hole.h <= 1440.1


def _restore_carvera(snapshot):
    if Config.has_section("carvera"):
        Config.remove_section("carvera")
    if snapshot is None:
        return
    Config.add_section("carvera")
    for key, value in snapshot.items():
        Config.set("carvera", key, value)
