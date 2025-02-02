from kivy.uix.modalview import ModalView

from carveracontroller.addons.probing.ProbeGcodeGenerator import ProbeGcodeGenerator
from carveracontroller.addons.probing.ProbingConstants import ProbingConstants
from carveracontroller.addons.probing.ProbingPreview import ProbingPreviewPopup

class ProbingPopup(ModalView):

    def __init__(self, config, controller, **kwargs):
        self.config = config
        self.preview_popup = ProbingPreviewPopup(config, controller)
        super(ProbingPopup, self).__init__(**kwargs)

    def get_probe_switch_type(self):
        if self.cb_probe_normally_closed.active:
            return ProbingConstants.switch_type_nc
        if self.cb_probe_normally_open.active:
            return ProbingConstants.switch_type_no
        return 0

    def on_probing_pressed(self, probe_type):
        print("Probing pressed: " + probe_type)
        self.preview_popup.title = "pt " + probe_type
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

    # def on_minus_y(self):
    #     self.root.start_probing(txt_x.text, txt_y.text, txt_z.text, txt_a.text, root.get_probe_switch_type())

    def update_preview(self):
        switch_type = self.get_probe_switch_type();
        generator = ProbeGcodeGenerator()
        gcode = generator.get_straight_probe(self.txt_x.text, self.txt_y.text, self.txt_z.text, self.txt_a.text,
                                             switch_type)

        if len(gcode) > 0:
            self.probe_preview_label.text = gcode
        else:
            self.probe_preview_label.text = "N/A"

    # def start_probing(self, x, y, z, a, switch_type):
    #     gcode = ProbeGcodeGenerator(x, y, z, a, switch_type)
    #     if len(gcode) > 0:
    #         self.controller.executeCommand(gcode + "\n")
