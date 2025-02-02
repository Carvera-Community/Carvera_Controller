from kivy.uix.modalview import ModalView
from carveracontroller.addons.probing.ProbeGcodeGenerator import ProbeOperation, M464Params
from carveracontroller.addons.probing.ProbingConstants import ProbingConstants
from carveracontroller.addons.probing.preview.ProbingPreviewPopup import ProbingPreviewPopup

class ProbingPopup(ModalView):

    def __init__(self, config, controller, **kwargs):
        self.config = config
        self.preview_popup = ProbingPreviewPopup(config, controller)
        super(ProbingPopup, self).__init__(**kwargs)

    def on_probing_pressed(self, operation: ProbeOperation):

        cfg = {
            M464Params.XAxisDistance: 1.2,
            M464Params.YAxisDistance: 2.5
        }

        self.preview_popup.update_operation(operation, cfg)
        self.preview_popup.open()

    # nicked from CoordPopup
    def set_config(self, key1, key2, value):
        self.config[key1][key2] = value
        # self.cnc_workspace.draw()

    def load_config(self):
        # init probing options
        self.probing_popup.cb_probe_normally_open.active = self.config[
                                                               ProbingConstants.config_section][
                                                               ProbingConstants.probe_switch_type] == 1
        self.probing_popup.txt_x_offset.text = str(
            self.config[ProbingConstants.config_section][ProbingConstants.x_axis])
        self.probing_popup.txt_y_offset.text = str(
            self.config[ProbingConstants.config_section][ProbingConstants.y_axis])
        self.probing_popup.txt_z_offset.text = str(
            self.config[ProbingConstants.config_section][ProbingConstants.z_axis])
        self.probing_popup.txt_a_offset.text = str(
            self.config[ProbingConstants.config_section][ProbingConstants.a_axis])

