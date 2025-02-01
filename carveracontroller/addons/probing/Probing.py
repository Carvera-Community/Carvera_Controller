from kivy.uix.modalview import ModalView

# from carveracontroller.Controller import Controller
from carveracontroller.addons.probing.ProbingConstants import ProbingConstants


class ProbingPopup(ModalView):
    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        # self.controller = controller
        super(ProbingPopup, self).__init__(**kwargs)

    def get_probe_switch_type(self):
        if self.cb_probe_normally_closed.active:
            return ProbingConstants.switch_type_nc

        if self.cb_probe_normally_open.active:
            return ProbingConstants.switch_type_no

        return 0

    def on_minus_y(self):
        self.root.start_probing(txt_x.text, txt_y.text, txt_z.text, txt_a.text, root.get_probe_switch_type())

    def update_preview(self):
        switch_type = self.get_probe_switch_type();
        generator = ProbeGcodeGenerator()
        gcode = generator.get_straight_probe(self.txt_x.text, self.txt_y.text, self.txt_z.text, self.txt_a.text, switch_type)

        if len(gcode) > 0:
            self.probe_preview_label.text = gcode
        else:
            self.probe_preview_label.text = "N/A"

    # def start_probing(self, x, y, z, a, switch_type):
    #     gcode = ProbeGcodeGenerator(x, y, z, a, switch_type)
    #     if len(gcode) > 0:
    #         self.controller.executeCommand(gcode + "\n")

class ProbeGcodeGenerator():
    @staticmethod
    def get_straight_probe(x, y, z, a, switch_type):
        if switch_type == ProbingConstants.switch_type_nc:
            command = "G38.4"
        else:
            command = "G38.2"

        suffix = ""
        if len(x) > 0:
            suffix += f" X{x}"
        if len(y) > 0:
            suffix += f" Y{y}"
        if len(z) > 0:
            suffix += f" Z{z}"
        if len(a) > 0:
            suffix += f" A{a}"

        if len(suffix) > 0:
            return command + suffix

        return ""