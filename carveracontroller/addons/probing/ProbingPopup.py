from kivy.clock import Clock
from kivy.uix.modalview import ModalView

from ... import Controller
from .operations.OperationsBase import OperationsBase
from .operations.OutsideCorner.OutsideCornerOperationType import OutsideCornerOperationType
from .operations.OutsideCorner.OutsideCornerSettings import OutsideCornerSettings
from .operations.InsideCorner.InsideCornerSettings import InsideCornerSettings
from .operations.SingleAxis.SingleAxisProbeOperationType import \
    SingleAxisProbeOperationType
from .operations.SingleAxis.SingleAxisProbeSettings import SingleAxisProbeSettings
from .preview.ProbingPreviewPopup import ProbingPreviewPopup

from .operations.InsideCorner.InsideCornerOperationType import InsideCornerOperationType

from .operations.Bore.BoreOperationType import BoreOperationType
from .operations.Bore.BoreSettings import BoreSettings

from .operations.Boss.BossOperationType import BossOperationType
from .operations.Boss.BossSettings import BossSettings

from .operations.Angle.AngleOperationType import AngleOperationType
from .operations.Angle.AngleSettings import AngleSettings


from .operations.ProbeTip.ProbeTipOperationType import ProbeTipOperationType
from .operations.ProbeTip.ProbeTipSettings import ProbeTipSettings

from kivy.app import App

import webbrowser

class ProbingPopup(ModalView):

    controller: Controller

    def __init__(self, controller, **kwargs):
        self.outside_corner_settings = None
        self.inside_corner_settings = None
        self.single_axis_settings = None
        self.bore_settings = None
        self.boss_settings = None
        self.angle_settings = None
        self.probeTipSettings = None
        self.controller = controller

        self.preview_popup = ProbingPreviewPopup(controller)

        # wait on UI to finish loading
        Clock.schedule_once(self.delayed_bind, 0.1)

        super(ProbingPopup, self).__init__(**kwargs)

    def open_probe_info_url(self):
        webbrowser.open("https://carvera-community.gitbook.io/docs/firmware/features/3d-probe-support")

    def delayed_bind(self, dt):
        self.outside_corner_settings = self.ids.outside_corner_settings
        self.inside_corner_settings = self.ids.inside_corner_settings
        self.single_axis_settings = self.ids.single_axis_settings
        self.bore_settings = self.ids.bore_settings
        self.boss_settings = self.ids.boss_settings

    def delayed_bind_complete(self, dt):
        self.angle_settings = self.ids.angle_settings
        self.probeTipSettings = self.ids.probeTipSettings


    def on_single_axis_probing_pressed(self, operation_key: str):
        cfg = self.single_axis_settings.get_config()
        the_op = SingleAxisProbeOperationType[operation_key].value
        self.show_preview(the_op, cfg)

    def on_inside_corner_probing_pressed(self, operation_key: str):
        cfg = self.inside_corner_settings.get_config()
        the_op = InsideCornerOperationType[operation_key].value
        self.show_preview(the_op, cfg)

    def on_outside_corner_probing_pressed(self, operation_key: str):

        cfg = self.outside_corner_settings.get_config()
        the_op = OutsideCornerOperationType[operation_key].value
        self.show_preview(the_op, cfg)

    def on_bore_probing_pressed(self, operation_key: str):

        cfg = self.bore_settings.get_config()
        the_op = BoreOperationType[operation_key].value
        self.show_preview(the_op, cfg)

    def on_boss_probing_pressed(self, operation_key: str):

        cfg = self.boss_settings.get_config()
        the_op = BossOperationType[operation_key].value
        self.show_preview(the_op, cfg)

    def on_angle_probing_pressed(self, operation_key: str):

        cfg = self.angle_settings.get_config()
        the_op = AngleOperationType[operation_key].value
        self.show_preview(the_op, cfg)

    def on_probeTip_probing_pressed(self, operation_key: str):
        cfg = self.probeTipSettings.get_config()
        the_op = ProbeTipOperationType[operation_key].value
        self.show_preview(the_op,cfg)


    def show_preview(self, operation: OperationsBase, cfg):
        missing_definition = operation.get_missing_config(cfg)

        if missing_definition is None:
            gcode = operation.generate(cfg)
            self.preview_popup.gcode = gcode
            self.preview_popup.probe_preview_label = gcode
        else:
            self.preview_popup.gcode = ""
            self.preview_popup.probe_preview_label = "Missing required parameter " + missing_definition.label

        self.preview_popup.open()

        Clock.schedule_once(lambda dt: self.link_shared_data_with_refresh(self.preview_popup), 0.1)

    def link_shared_data_with_refresh(self, popup):
        app = App.get_running_app()
        popup.ids.manual_rvPopup.data = app.mdi_data

        # Clear old data
        app.mdi_data.clear()

        app.bind(mdi_data=lambda instance, value: self.on_mdi_data_changed(popup))
    
    def on_mdi_data_changed(self, popup):
        try:
            popup.ids.manual_rvPopup.refresh_from_data()
            Clock.schedule_once(lambda dt: self.scroll_to_bottom(popup.ids.manual_rvPopup), 0.01)
        except Exception as e:
            print("Popup refresh failed:", e)

    def scroll_to_bottom(self, rv):
        try:
            Clock.schedule_once(lambda dt: setattr(rv, 'scroll_y', 0), 0.01)
        except Exception as e:
            print("Scroll failed:", e)