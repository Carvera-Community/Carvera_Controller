from kivy.clock import Clock
from kivy.uix.modalview import ModalView
from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerOperationType import OutsideCornerOperationType
from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerSettings import OutsideCornerSettings
from carveracontroller.addons.probing.operations.InsideCorner.InsideCornerSettings import InsideCornerSettings
from carveracontroller.addons.probing.preview.ProbingPreviewPopup import ProbingPreviewPopup

from carveracontroller.addons.probing.operations.InsideCorner.InsideCornerOperationType import InsideCornerOperationType


class ProbingPopup(ModalView):

    def __init__(self, controller, **kwargs):
        self.outside_corner_settings = None
        self.inside_corner_settings = None
        self.preview_popup = ProbingPreviewPopup(controller)

        Clock.schedule_once(self.delayed_bind, 0.1)
        super(ProbingPopup, self).__init__(**kwargs)

    def delayed_bind(self, dt):
        self.outside_corner_settings = self.ids.outside_corner_settings
        self.inside_corner_settings = self.ids.inside_corner_settings

    # def on_single_axis_probing_pressed(self, operation_key: str):
    #     self.preview_popup.open()

    # def on_bore_boss_corner_probing_pressed(self, operation_key: str):

    def on_inside_corner_probing_pressed(self, operation_key: str):
        cfg = self.inside_corner_settings.get_config()
        the_op = InsideCornerOperationType[operation_key].value
        missing_definition = the_op.get_missing_config(cfg)

        if missing_definition is None:
            self.preview_popup.gcode = the_op.generate(cfg)
            self.preview_popup.probe_preview_label = self.preview_popup.gcode
        else:
            self.preview_popup.gcode = ""
            self.preview_popup.probe_preview_label = "Missing required parameter " + missing_definition.label

        self.preview_popup.open()

    def on_outside_corner_probing_pressed(self, operation_key: str):

        cfg = self.outside_corner_settings.get_config()
        the_op = OutsideCornerOperationType[operation_key].value
        missing_definition = the_op.get_missing_config(cfg)

        if missing_definition is None:
            gcode = the_op.generate(cfg)
            self.preview_popup.gcode = gcode
            self.preview_popup.probe_preview_label = gcode
            print("setting gcode to " + gcode)
        else:
            self.preview_popup.gcode = ""
            self.preview_popup.probe_preview_label = "Missing required parameter " + missing_definition.label

        self.preview_popup.open()

    def load_config(self):
        # todo
        pass
