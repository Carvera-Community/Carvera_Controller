"""Config and Run dialog keeps its widget contract and compact layout."""

import threading

from kivy.input.motionevent import MotionEvent
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

from carveracontroller.Utils import digitize_v
from tests.integration.conftest import pump_frames


class _ProbeTouch(MotionEvent):
    def depack(self, args):
        self.is_touch = True
        self.profile = ["pos"]
        self.sx, self.sy = args
        self.x, self.y = args
        self.pos = args
        super().depack(args)


def test_config_run_widgets_and_layout(kivy_app):
    popup = kivy_app.root.coord_popup
    model = kivy_app.model
    community = kivy_app.is_community_firmware
    firmware = kivy_app.fw_version_digitized
    try:
        popup.load_config()
        pump_frames(3)

        assert popup._cards_bound is True
        assert popup.cnc_workspace is popup.ids.cnc_workspace
        assert "background_image_spinner" in popup.ids
        for switch_id in (
            "vacuum_switch_play",
            "extout_switch_play",
            "autoblow_switch_play",
            "autobedclean_switch_play",
            "ionizer_switch_play",
            "timelapse_switch_play",
        ):
            assert switch_id in popup.ids

        assert isinstance(popup.cbx_margin, CheckBox)
        assert isinstance(popup.cbx_zprobe, CheckBox)
        assert isinstance(popup.cbx_leveling, CheckBox)
        assert isinstance(popup.cbx_startline, CheckBox)
        assert isinstance(popup.txt_startline, TextInput)
        assert popup.txt_startline.hint_text
        assert "Resume File" in popup.ids.resume_card.title_text
        assert any(getattr(w, "text", None) == "Line:" for w in popup.ids.resume_card.walk())
        # No machine toggles until a model or firmware exposes one, and the
        # empty card must not leave a gap under the background selector.
        assert popup.ids.feature_switches_card.height == 0
        assert popup.ids.background_section.spacing == 0
        assert len(popup.ids.background_card.children) == 2
        assert isinstance(popup.lb_origin, Label)
        assert isinstance(popup.lb_zprobe, Label)
        assert isinstance(popup.lb_leveling, Label)
        assert isinstance(popup.btn_origin, Button)
        assert isinstance(popup.btn_zprobe, Button)
        assert isinstance(popup.btn_leveling, Button)
        assert popup.lb_origin.text
        assert popup.lb_leveling.text_size[1] is None

        was_margin = popup.cbx_margin.active
        popup.ids.margin_card.toggle_checkbox()
        assert popup.cbx_margin.active is not was_margin
        popup.cbx_margin.active = was_margin

        popup.mode = "Margin"
        pump_frames(1)
        resume = popup.ids.resume_card
        assert resume.collapsed is True
        assert resume.height == 0
        assert popup.ids.margin_card.section_disabled is False
        assert popup.ids.zprobe_card.section_disabled is True
        # Children keep a real size inside the zero-height card. A touch there
        # must fall through to the card above instead of being swallowed.
        overlap = resume.children[0]
        saved_pos, saved_size = overlap.pos, overlap.size
        overlap.pos = (0, 40)
        overlap.size = (200, 50)
        try:
            touch = _ProbeTouch("probe", 1, (100, 60))
            assert overlap.collide_point(*touch.pos)
            assert resume.on_touch_down(touch) is False
        finally:
            overlap.pos = saved_pos
            overlap.size = saved_size

        popup.mode = "Run"
        kivy_app.model = "Z1"
        kivy_app.lasering = False
        kivy_app.has_4axis = False
        popup.cbx_zprobe.active = False
        pump_frames(1)
        assert popup.btn_zprobe.disabled is True
        assert popup.lb_zprobe.disabled is True
        assert popup.ids.resume_card.collapsed is False
        assert popup.ids.resume_card.height > 0
        assert popup.ids.feature_switches_card.height > 0
        assert popup.ids.background_section.spacing == popup.ids.origin_card.parent.spacing
        assert popup.ids.vacuum_switch_play.parent.height == 0
        assert popup.ids.ionizer_switch_play.parent.height > 0
        assert popup.ids.autoblow_switch_play.parent.height > 0
        assert popup.ids.autobedclean_switch_play.parent.height > 0
        assert popup.ids.timelapse_switch_play.parent.height > 0

        kivy_app.model = "C1"
        pump_frames(1)
        assert popup.ids.feature_switches_card.height > 0
        assert popup.ids.vacuum_switch_play.parent.height > 0
        assert popup.ids.ionizer_switch_play.parent.height == 0
        assert popup.ids.timelapse_switch_play.parent.height == 0
        assert popup.ids.extout_switch_play.parent.height == 0

        kivy_app.model = "CA1"
        kivy_app.is_community_firmware = False
        kivy_app.fw_version_digitized = 0
        pump_frames(1)
        assert popup.ids.feature_switches_card.height == 0
        assert popup.ids.background_section.spacing == 0

        kivy_app.is_community_firmware = True
        kivy_app.fw_version_digitized = digitize_v("2.1.0")
        pump_frames(1)
        assert popup.ids.feature_switches_card.height == 0

        popup.mode = "Run"
        popup.open(animation=False)
        pump_frames(2)
        assert popup.ids.feature_switches_card.height == 0
        # Flags are already stored before the dialog opens. Clear the row first
        # so this checks the open refresh, not a kv update from assigning them.
        kivy_app.fw_version_digitized = digitize_v("2.2.0c")
        popup.dismiss(animation=False)
        row = popup.ids.extout_switch_row
        row.height = 0
        row.opacity = 0
        row.disabled = True
        popup.open(animation=False)
        pump_frames(2)
        switch = popup.ids.extout_switch_play
        label = next(w for w in row.children if getattr(w, "text", None) == "Auto Ext. Out")
        assert kivy_app.is_community_firmware is True
        assert kivy_app.fw_version_digitized == digitize_v("2.2.0c")
        assert popup.ids.feature_switches_card.height > 0
        assert popup.ids.feature_switches_card.opacity == 1
        assert row.height > 0
        assert row.opacity == 1
        assert row.disabled is False
        assert switch.width > 0 and switch.height > 0 and switch.opacity == 1
        assert label.width > 0 and label.height > 0 and label.opacity == 1
        assert popup.ids.vacuum_switch_row.height == 0
        assert popup.ids.vacuum_switch_row.opacity == 0
        assert popup.ids.ionizer_switch_row.height == 0
        assert popup.ids.ionizer_switch_row.opacity == 0
        assert popup.ids.timelapse_switch_row.height == 0
        assert popup.ids.timelapse_switch_row.opacity == 0

        popup.set_compact_from_window(width=1920)
        assert popup.compact is False
        assert tuple(popup.size_hint) == (0.8, 0.8)
        popup.set_compact_from_window(width=480)
        assert popup.compact is True
        assert tuple(popup.size_hint) == (0.96, 0.94)
    finally:
        if popup._is_open:
            popup.dismiss()
        popup.mode = "Run"
        kivy_app.model = model
        kivy_app.is_community_firmware = community
        kivy_app.fw_version_digitized = firmware
        kivy_app.lasering = False
        kivy_app.has_4axis = False
        popup.set_compact_from_window(width=1920)


def test_extout_switch_enables_when_firmware_flags_are_set_off_ui_thread(kivy_app):
    popup = kivy_app.root.coord_popup
    model = kivy_app.model
    community = kivy_app.is_community_firmware
    firmware = kivy_app.fw_version_digitized
    try:
        if popup._is_open:
            popup.dismiss(animation=False)
        kivy_app.model = "CA1"
        kivy_app.is_community_firmware = False
        kivy_app.fw_version_digitized = 0
        pump_frames(2)

        def set_flags():
            # Theme canvas instructions raise once the value is already stored.
            # One try around both writes skips the firmware version, and the
            # dialog then keeps this row hidden. The dialog reads the stored flags.
            for assign in (
                lambda: setattr(kivy_app, "is_community_firmware", True),
                lambda: setattr(kivy_app, "fw_version_digitized", digitize_v("2.2.0c")),
            ):
                try:
                    assign()
                except Exception:
                    pass

        worker = threading.Thread(target=set_flags)
        worker.start()
        worker.join()
        pump_frames(2)
        popup.open(animation=False)
        pump_frames(2)
        switch = popup.ids.extout_switch_play
        assert switch.parent.height > 0
        assert switch.disabled is False
        assert popup.ids.feature_switches_card.disabled is False
    finally:
        if popup._is_open:
            popup.dismiss(animation=False)
        kivy_app.model = model
        kivy_app.is_community_firmware = community
        kivy_app.fw_version_digitized = firmware
