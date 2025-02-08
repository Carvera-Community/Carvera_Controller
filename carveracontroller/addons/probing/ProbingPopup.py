from kivy.clock import Clock
from kivy.uix.modalview import ModalView

from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase
from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerOperationType import OutsideCornerOperationType
from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerSettings import OutsideCornerSettings
from carveracontroller.addons.probing.operations.InsideCorner.InsideCornerSettings import InsideCornerSettings
from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeOperationType import \
    SingleAxisProbeOperationType
from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeSettings import SingleAxisProbeSettings
from carveracontroller.addons.probing.preview.ProbingPreviewPopup import ProbingPreviewPopup

from carveracontroller.addons.probing.operations.InsideCorner.InsideCornerOperationType import InsideCornerOperationType


class ProbingPopup(ModalView):

    def __init__(self, controller, **kwargs):
        self.outside_corner_settings = None
        self.inside_corner_settings = None
        self.single_axis_settings = None

        self.preview_popup = ProbingPreviewPopup(controller)

        # wait on UI to finish loading
        Clock.schedule_once(self.delayed_bind, 0.1)

        super(ProbingPopup, self).__init__(**kwargs)

    def delayed_bind(self, dt):
        self.outside_corner_settings = self.ids.outside_corner_settings
        self.inside_corner_settings = self.ids.inside_corner_settings
        self.single_axis_settings = self.ids.single_axis_settings

    # def on_bore_boss_corner_probing_pressed(self, operation_key: str):

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

    def load_config(self):
        # todo
        pass
