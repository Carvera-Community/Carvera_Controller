from kivy.properties import ObjectProperty
from kivy.uix.modalview import ModalView
from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase
from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerOperationType import OutsideCornerOperationType
from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerSettings import OutsideCornerSettings
from carveracontroller.addons.probing.preview.ProbingPreviewPopup import ProbingPreviewPopup

class ProbingPopup(ModalView):
    outside_corner_settings = ObjectProperty()

    def __init__(self, controller, **kwargs):
        self.preview_popup = ProbingPreviewPopup(controller)

        self.outside_corner_settings = OutsideCornerSettings()
        super(ProbingPopup, self).__init__(**kwargs)

    # def on_single_axis_probing_pressed(self, operation: SingleAxisOperation):
    # def on_inside_corner_probing_pressed(self, operation: CornerProbeOperation):
    # def on_bore_boss_corner_probing_pressed(self, operation: BoreBossOperationType):

    def on_outside_corner_probing_pressed(self, operation_key: str):

        cfg = self.outside_corner_settings.get_config()
        the_op = OperationsBase(OutsideCornerOperationType[operation_key].value) # down cast

        self.preview_popup.update_operation(the_op, cfg)
        self.preview_popup.open()

    # def set_config(self, key1, key2, value):
    #     self.config[key1][key2] = value
    #     # self.cnc_workspace.draw()

    def load_config(self):
        # todo
        pass

